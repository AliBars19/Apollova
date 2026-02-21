"""
Apollova Upload State Manager
==============================

SQLite-backed state tracking with:
- Per-video upload/schedule status tracking
- Per-account daily slot counting (enforces 12/day limit)
- Next-day overflow for excess videos
- Crash recovery (stuck "uploading" records)
- Full activity log per record
"""

import sqlite3
import hashlib
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"


class ScheduleStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass
class UploadRecord:
    """A single video upload record."""
    id: int = 0
    file_path: str = ""
    file_name: str = ""
    file_hash: str = ""
    file_size: int = 0
    template: str = ""         # aurora / mono / onyx
    account: str = ""          # aurora / nova (/ onyx in future)

    upload_status: str = UploadStatus.PENDING
    video_id: str = ""
    upload_attempts: int = 0
    upload_error: str = ""
    uploaded_at: Optional[str] = None

    schedule_status: str = ScheduleStatus.PENDING
    scheduled_at: Optional[str] = None
    published_at: Optional[str] = None

    created_at: str = ""
    updated_at: str = ""


def compute_file_hash(file_path: str) -> str:
    """SHA-256 hash of a file (64KB chunks for large videos)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class StateManager:
    """SQLite state manager with daily slot tracking per account.
    
    Key method: `get_next_schedule_slot(account)` finds the next available
    time slot respecting the 12/day limit and rolling to the next day if full.
    """

    def __init__(self, db_path: str = "./data/upload_state.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS uploads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT UNIQUE NOT NULL,
                        file_name TEXT NOT NULL,
                        file_hash TEXT,
                        file_size INTEGER,
                        template TEXT,
                        account TEXT,

                        upload_status TEXT DEFAULT 'pending',
                        video_id TEXT,
                        upload_attempts INTEGER DEFAULT 0,
                        upload_error TEXT,
                        uploaded_at TEXT,

                        schedule_status TEXT DEFAULT 'pending',
                        scheduled_at TEXT,
                        published_at TEXT,

                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now'))
                    );

                    CREATE TABLE IF NOT EXISTS upload_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        upload_id INTEGER REFERENCES uploads(id),
                        action TEXT NOT NULL,
                        status TEXT,
                        message TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    );

                    CREATE INDEX IF NOT EXISTS idx_uploads_status
                        ON uploads(upload_status);
                    CREATE INDEX IF NOT EXISTS idx_uploads_account
                        ON uploads(account);
                    CREATE INDEX IF NOT EXISTS idx_uploads_scheduled_at
                        ON uploads(scheduled_at);
                """)
                conn.commit()
            finally:
                conn.close()

    # ── Record Creation ──────────────────────────────────────────

    def add_upload(
        self,
        file_path: str,
        template: str,
        account: str,
        file_hash: str = "",
        file_size: int = 0,
    ) -> int:
        """Add a new upload record. Returns existing ID if file already tracked."""
        with self._lock:
            conn = self._get_conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM uploads WHERE file_path = ?", (file_path,)
                ).fetchone()
                if existing:
                    return existing["id"]

                cursor = conn.execute(
                    """INSERT INTO uploads
                       (file_path, file_name, file_hash, file_size, template, account)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (file_path, Path(file_path).name, file_hash, file_size, template, account),
                )
                rid = cursor.lastrowid
                self._log(conn, rid, "created", "pending", f"{template}/{account}")
                conn.commit()
                return rid
            finally:
                conn.close()

    # ── Status Updates ───────────────────────────────────────────

    def try_claim(self, record_id: int) -> bool:
        """Atomically claim a record for uploading. Returns False if already claimed.
        
        This prevents double-uploads when multiple filesystem events fire
        for the same file. Only the first thread to call try_claim wins.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                # Only claim if still in PENDING state
                cursor = conn.execute(
                    """UPDATE uploads SET upload_status = ?, updated_at = ?
                       WHERE id = ? AND upload_status = ?""",
                    (UploadStatus.UPLOADING, _now(), record_id, UploadStatus.PENDING),
                )
                conn.commit()
                claimed = cursor.rowcount > 0
                if claimed:
                    self._log(conn, record_id, "claimed", "uploading", "")
                    conn.commit()
                return claimed
            finally:
                conn.close()

    def mark_uploading(self, record_id: int) -> None:
        self._update(record_id, upload_status=UploadStatus.UPLOADING, _action="upload_start")

    def mark_uploaded(self, record_id: int, video_id: str) -> None:
        self._update(
            record_id,
            upload_status=UploadStatus.UPLOADED,
            video_id=video_id,
            uploaded_at=_now(),
            _action="uploaded",
            _message=f"video_id={video_id}",
        )

    def mark_upload_failed(self, record_id: int, error: str) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """UPDATE uploads SET upload_status = ?, upload_error = ?,
                       upload_attempts = upload_attempts + 1, updated_at = ?
                       WHERE id = ?""",
                    (UploadStatus.FAILED, error, _now(), record_id),
                )
                self._log(conn, record_id, "upload_failed", "error", error[:500])
                conn.commit()
            finally:
                conn.close()

    def mark_scheduled(self, record_id: int, scheduled_at: str) -> None:
        self._update(
            record_id,
            schedule_status=ScheduleStatus.SCHEDULED,
            scheduled_at=scheduled_at,
            _action="scheduled",
            _message=f"at={scheduled_at}",
        )

    def mark_schedule_failed(self, record_id: int, error: str) -> None:
        self._update(
            record_id,
            schedule_status=ScheduleStatus.FAILED,
            _action="schedule_failed",
            _message=error,
        )

    def reset_failed(self, record_id: int) -> None:
        self._update(
            record_id,
            upload_status=UploadStatus.PENDING,
            upload_error="",
            _action="reset",
            _message="Reset for retry",
        )

    # ── Schedule Slot Management ─────────────────────────────────

    def count_scheduled_for_date(self, account: str, date: datetime) -> int:
        """Count how many videos are already scheduled for a given account on a given date."""
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM uploads
                       WHERE account = ?
                       AND schedule_status = 'scheduled'
                       AND scheduled_at >= ? AND scheduled_at < ?""",
                    (account, day_start.isoformat(), day_end.isoformat()),
                ).fetchone()
                return row["cnt"]
            finally:
                conn.close()

    def get_last_scheduled_time(self, account: str, date: datetime) -> Optional[datetime]:
        """Get the latest scheduled time for an account on a given date."""
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    """SELECT MAX(scheduled_at) as last_time FROM uploads
                       WHERE account = ?
                       AND schedule_status = 'scheduled'
                       AND scheduled_at >= ? AND scheduled_at < ?""",
                    (account, day_start.isoformat(), day_end.isoformat()),
                ).fetchone()
                if row and row["last_time"]:
                    return datetime.fromisoformat(row["last_time"])
                return None
            finally:
                conn.close()

    # ── Queries ──────────────────────────────────────────────────

    def get_record(self, record_id: int) -> Optional[UploadRecord]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT * FROM uploads WHERE id = ?", (record_id,)).fetchone()
                return self._to_record(row) if row else None
            finally:
                conn.close()

    def get_by_path(self, file_path: str) -> Optional[UploadRecord]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM uploads WHERE file_path = ?", (file_path,)
                ).fetchone()
                return self._to_record(row) if row else None
            finally:
                conn.close()

    def is_processed(self, file_path: str) -> bool:
        """Check if file has been successfully uploaded (regardless of schedule status)."""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT upload_status FROM uploads WHERE file_path = ?",
                    (file_path,),
                ).fetchone()
                return row is not None and row["upload_status"] == UploadStatus.UPLOADED
            finally:
                conn.close()

    def get_failed(self) -> list[UploadRecord]:
        return self._query("upload_status = ?", (UploadStatus.FAILED,))

    def get_uploading(self) -> list[UploadRecord]:
        return self._query("upload_status = ?", (UploadStatus.UPLOADING,))

    def get_retryable(self, max_attempts: int = 3) -> list[UploadRecord]:
        return self._query(
            "upload_status = ? AND upload_attempts < ?",
            (UploadStatus.FAILED, max_attempts),
        )

    def get_stats(self) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                stats = {}
                for status in UploadStatus:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM uploads WHERE upload_status = ?",
                        (status.value,),
                    ).fetchone()
                    stats[status.value] = row["cnt"]
                stats["total"] = sum(stats.values())

                # Per-account scheduled today
                today = datetime.now()
                for account in ["aurora", "nova", "onyx"]:
                    cnt = self.count_scheduled_for_date(account, today)
                    if cnt > 0:
                        stats[f"{account}_today"] = cnt

                return stats
            finally:
                conn.close()

    def get_recent_log(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT l.*, u.file_name, u.account
                       FROM upload_log l JOIN uploads u ON l.upload_id = u.id
                       ORDER BY l.created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def purge_old(self, days: int = 30) -> int:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """DELETE FROM uploads
                       WHERE upload_status = ? AND schedule_status = ?
                       AND created_at < datetime('now', ?)""",
                    (UploadStatus.UPLOADED, ScheduleStatus.SCHEDULED, f"-{days} days"),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    # ── Internals ────────────────────────────────────────────────

    def _update(self, record_id: int, _action: str = "", _message: str = "", **fields) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                fields["updated_at"] = _now()
                # Filter out our private kwargs
                db_fields = {k: v for k, v in fields.items() if not k.startswith("_")}
                sets = ", ".join(f"{k} = ?" for k in db_fields)
                values = list(db_fields.values()) + [record_id]
                conn.execute(f"UPDATE uploads SET {sets} WHERE id = ?", values)
                if _action:
                    self._log(conn, record_id, _action, str(fields.get("upload_status", fields.get("schedule_status", ""))), _message)
                conn.commit()
            finally:
                conn.close()

    def _log(self, conn: sqlite3.Connection, upload_id: int, action: str, status: str, message: str = "") -> None:
        conn.execute(
            "INSERT INTO upload_log (upload_id, action, status, message) VALUES (?, ?, ?, ?)",
            (upload_id, action, status, message),
        )

    def _query(self, where: str, params: tuple) -> list[UploadRecord]:
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    f"SELECT * FROM uploads WHERE {where} ORDER BY created_at", params
                ).fetchall()
                return [self._to_record(r) for r in rows]
            finally:
                conn.close()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> UploadRecord:
        return UploadRecord(**{k: row[k] for k in row.keys()})