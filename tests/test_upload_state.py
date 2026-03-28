"""
Tests for upload/upload_state.py

Covers:
  - StateManager.add_upload: creates a record, returns integer ID
  - StateManager.add_upload: idempotent — duplicate path returns same ID
  - StateManager.get_record: returns UploadRecord with correct fields
  - StateManager.get_by_path: finds record by file path
  - StateManager.is_processed: False before upload, True after mark_uploaded
  - Status transitions: pending → uploading → uploaded → scheduled
  - mark_upload_failed: increments upload_attempts, sets error message
  - reset_failed: resets status to pending
  - try_claim: returns True on first call, False on second (atomic)
  - try_claim: returns False if record is not in PENDING state
  - get_failed / get_uploading / get_retryable: filter correctly
  - count_scheduled_for_date: counts only the requested account and day
  - get_last_scheduled_time: returns latest scheduled time for account
  - get_stats: counts per-status and per-account-today
  - purge_old: deletes uploaded+scheduled records older than N days
  - crash recovery: stuck UPLOADING records are identifiable via get_uploading
  - compute_file_hash: deterministic SHA-256 of file content
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Ensure upload/ is importable
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "upload"))

from upload_state import (
    StateManager,
    UploadRecord,
    UploadStatus,
    ScheduleStatus,
    compute_file_hash,
)


# ===========================================================================
# add_upload
# ===========================================================================

class TestAddUpload:
    def test_returns_integer_id(self, upload_state: StateManager):
        rid = upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        assert isinstance(rid, int)
        assert rid > 0

    def test_record_exists_after_add(self, upload_state: StateManager):
        rid = upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        record = upload_state.get_record(rid)
        assert record is not None
        assert isinstance(record, UploadRecord)

    def test_record_fields_set_correctly(self, upload_state: StateManager):
        rid = upload_state.add_upload(
            "/renders/song.mp4",
            "aurora",
            "aurora",
            file_hash="abc123",
            file_size=1024,
        )
        record = upload_state.get_record(rid)
        assert record.template == "aurora"
        assert record.account == "aurora"
        assert record.file_hash == "abc123"
        assert record.file_size == 1024
        assert record.upload_status == UploadStatus.PENDING

    def test_duplicate_path_returns_same_id(self, upload_state: StateManager):
        r1 = upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/renders/song.mp4", "mono", "mono")
        assert r1 == r2

    def test_different_paths_get_different_ids(self, upload_state: StateManager):
        r1 = upload_state.add_upload("/renders/a.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/renders/b.mp4", "aurora", "aurora")
        assert r1 != r2

    def test_file_name_extracted_from_path(self, upload_state: StateManager):
        rid = upload_state.add_upload("/deep/nested/path/song.mp4", "aurora", "aurora")
        record = upload_state.get_record(rid)
        assert record.file_name == "song.mp4"


# ===========================================================================
# get_by_path / is_processed
# ===========================================================================

class TestGetByPath:
    def test_get_by_path_finds_record(self, upload_state: StateManager):
        upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        record = upload_state.get_by_path("/renders/song.mp4")
        assert record is not None
        assert record.file_path == "/renders/song.mp4"

    def test_get_by_path_returns_none_for_unknown(self, upload_state: StateManager):
        assert upload_state.get_by_path("/nonexistent.mp4") is None

    def test_is_processed_false_before_upload(self, upload_state: StateManager):
        upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        assert upload_state.is_processed("/renders/song.mp4") is False

    def test_is_processed_true_after_mark_uploaded(self, upload_state: StateManager):
        rid = upload_state.add_upload("/renders/song.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "yt_vid_123")
        assert upload_state.is_processed("/renders/song.mp4") is True

    def test_is_processed_false_for_unknown_path(self, upload_state: StateManager):
        assert upload_state.is_processed("/not/registered.mp4") is False


# ===========================================================================
# Status transitions
# ===========================================================================

class TestStatusTransitions:
    def test_pending_to_uploading(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploading(rid)
        assert upload_state.get_record(rid).upload_status == UploadStatus.UPLOADING

    def test_uploading_to_uploaded(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploading(rid)
        upload_state.mark_uploaded(rid, "vid_abc")
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.UPLOADED
        assert record.video_id == "vid_abc"
        assert record.uploaded_at is not None

    def test_mark_scheduled(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "vid_abc")
        upload_state.mark_scheduled(rid, "2026-03-18T12:00:00")
        record = upload_state.get_record(rid)
        assert record.schedule_status == ScheduleStatus.SCHEDULED
        assert "12:00:00" in record.scheduled_at

    def test_full_lifecycle(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploading(rid)
        upload_state.mark_uploaded(rid, "vid_123")
        upload_state.mark_scheduled(rid, "2026-03-18T14:00:00")

        r = upload_state.get_record(rid)
        assert r.upload_status == UploadStatus.UPLOADED
        assert r.video_id == "vid_123"
        assert r.schedule_status == ScheduleStatus.SCHEDULED


# ===========================================================================
# Failures and retries
# ===========================================================================

class TestFailuresAndRetries:
    def test_mark_upload_failed_sets_status(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(rid, "connection timeout")
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.FAILED
        assert "timeout" in record.upload_error.lower()

    def test_mark_upload_failed_increments_attempts(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(rid, "err1")
        upload_state.mark_upload_failed(rid, "err2")
        record = upload_state.get_record(rid)
        assert record.upload_attempts == 2

    def test_reset_failed_restores_pending(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(rid, "timeout")
        upload_state.reset_failed(rid)
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.PENDING

    def test_mark_schedule_failed(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "vid")
        upload_state.mark_schedule_failed(rid, "API error")
        record = upload_state.get_record(rid)
        assert record.schedule_status == ScheduleStatus.FAILED

    def test_get_failed_returns_failed_records(self, upload_state: StateManager):
        r1 = upload_state.add_upload("/a.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/b.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(r1, "err")
        # r2 stays pending
        failed = upload_state.get_failed()
        assert len(failed) == 1
        assert failed[0].file_path == "/a.mp4"

    def test_get_retryable_respects_max_attempts(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        for _ in range(3):
            upload_state.mark_upload_failed(rid, "err")
        # Exhausted — should not be retryable at max_attempts=3
        retryable = upload_state.get_retryable(max_attempts=3)
        assert all(r.id != rid for r in retryable)

    def test_get_retryable_includes_attempts_under_max(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(rid, "err")
        retryable = upload_state.get_retryable(max_attempts=3)
        assert any(r.id == rid for r in retryable)


# ===========================================================================
# try_claim (atomic PENDING → UPLOADING)
# ===========================================================================

class TestTryClaim:
    def test_first_claim_returns_true(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        assert upload_state.try_claim(rid) is True

    def test_second_claim_returns_false(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.try_claim(rid)
        assert upload_state.try_claim(rid) is False

    def test_claim_sets_status_to_uploading(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.try_claim(rid)
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.UPLOADING

    def test_claim_fails_if_already_uploaded(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "vid_done")
        assert upload_state.try_claim(rid) is False

    def test_claim_fails_if_already_failed(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_upload_failed(rid, "some error")
        assert upload_state.try_claim(rid) is False


# ===========================================================================
# get_uploading (crash recovery)
# ===========================================================================

class TestCrashRecovery:
    def test_get_uploading_returns_stuck_records(self, upload_state: StateManager):
        """Simulates a crash: mark_uploading was called but upload never completed."""
        r1 = upload_state.add_upload("/stuck_a.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/stuck_b.mp4", "aurora", "aurora")
        upload_state.mark_uploading(r1)
        upload_state.mark_uploading(r2)
        # Simulate crash — neither was marked uploaded

        stuck = upload_state.get_uploading()
        assert len(stuck) == 2
        paths = {r.file_path for r in stuck}
        assert "/stuck_a.mp4" in paths
        assert "/stuck_b.mp4" in paths

    def test_after_marking_uploaded_no_longer_stuck(self, upload_state: StateManager):
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploading(rid)
        upload_state.mark_uploaded(rid, "vid_abc")

        stuck = upload_state.get_uploading()
        assert all(r.id != rid for r in stuck)


# ===========================================================================
# Schedule slot counting
# ===========================================================================

class TestScheduleSlotCounting:
    def test_count_scheduled_zero_initially(self, upload_state: StateManager):
        today = datetime.now()
        assert upload_state.count_scheduled_for_date("aurora", today) == 0

    def test_count_scheduled_increments(self, upload_state: StateManager):
        today = datetime.now()
        for i in range(3):
            rid = upload_state.add_upload(f"/v{i}.mp4", "aurora", "aurora")
            upload_state.mark_uploaded(rid, f"vid_{i}")
            upload_state.mark_scheduled(
                rid,
                today.replace(hour=11 + i, minute=0, second=0, microsecond=0).isoformat(),
            )
        assert upload_state.count_scheduled_for_date("aurora", today) == 3

    def test_count_scheduled_is_account_specific(self, upload_state: StateManager):
        today = datetime.now()
        rid = upload_state.add_upload("/aurora.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "a_vid")
        upload_state.mark_scheduled(
            rid, today.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        )
        assert upload_state.count_scheduled_for_date("aurora", today) == 1
        assert upload_state.count_scheduled_for_date("mono", today) == 0

    def test_count_scheduled_ignores_other_days(self, upload_state: StateManager):
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        rid = upload_state.add_upload("/tomorrow.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "t_vid")
        upload_state.mark_scheduled(
            rid, tomorrow.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        )
        assert upload_state.count_scheduled_for_date("aurora", today) == 0
        assert upload_state.count_scheduled_for_date("aurora", tomorrow) == 1

    def test_get_last_scheduled_time_returns_latest(self, upload_state: StateManager):
        today = datetime.now()
        r1 = upload_state.add_upload("/a.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/b.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(r1, "v1")
        upload_state.mark_uploaded(r2, "v2")
        t1 = today.replace(hour=11, minute=0, second=0, microsecond=0)
        t2 = today.replace(hour=14, minute=0, second=0, microsecond=0)
        upload_state.mark_scheduled(r1, t1.isoformat())
        upload_state.mark_scheduled(r2, t2.isoformat())

        last = upload_state.get_last_scheduled_time("aurora", today)
        assert last is not None
        assert last.hour == 14

    def test_get_last_scheduled_time_returns_none_when_empty(self, upload_state: StateManager):
        today = datetime.now()
        assert upload_state.get_last_scheduled_time("aurora", today) is None


# ===========================================================================
# get_stats
# ===========================================================================

class TestGetStats:
    def test_stats_empty_db(self, upload_state: StateManager):
        stats = upload_state.get_stats()
        assert stats["pending"] == 0
        assert stats["uploaded"] == 0
        assert stats["failed"] == 0
        assert stats["total"] == 0

    def test_stats_counts_correctly(self, upload_state: StateManager):
        r1 = upload_state.add_upload("/a.mp4", "aurora", "aurora")
        r2 = upload_state.add_upload("/b.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(r1, "vid_1")
        upload_state.mark_upload_failed(r2, "err")

        stats = upload_state.get_stats()
        assert stats["pending"] == 0
        assert stats["uploaded"] == 1
        assert stats["failed"] == 1
        assert stats["total"] == 2

    def test_stats_includes_aurora_today(self, upload_state: StateManager):
        today = datetime.now()
        rid = upload_state.add_upload("/v.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "vid")
        upload_state.mark_scheduled(
            rid, today.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        )
        stats = upload_state.get_stats()
        assert stats.get("aurora_today", 0) == 1


# ===========================================================================
# purge_old
# ===========================================================================

class TestPurgeOld:
    def test_purges_old_uploaded_records(self, upload_state: StateManager):
        rid = upload_state.add_upload("/old.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "old_vid")
        upload_state.mark_scheduled(rid, "2020-01-01T12:00:00")

        # Force created_at to be very old AND clear the upload_log rows that
        # would trigger the FK constraint, so purge_old can DELETE the upload.
        import sqlite3 as _sqlite3
        actual_path = str(upload_state.db_path)
        conn = _sqlite3.connect(actual_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "UPDATE uploads SET created_at = '2020-01-01T00:00:00' WHERE id = ?", (rid,)
        )
        conn.execute("DELETE FROM upload_log WHERE upload_id = ?", (rid,))
        conn.commit()
        conn.close()

        deleted = upload_state.purge_old(days=30)
        assert deleted >= 1

    def test_does_not_purge_recent_records(self, upload_state: StateManager):
        rid = upload_state.add_upload("/recent.mp4", "aurora", "aurora")
        upload_state.mark_uploaded(rid, "r_vid")
        upload_state.mark_scheduled(rid, datetime.now().isoformat())

        deleted = upload_state.purge_old(days=30)
        assert deleted == 0
        assert upload_state.get_record(rid) is not None


# ===========================================================================
# compute_file_hash
# ===========================================================================

class TestComputeFileHash:
    def test_returns_64_char_hex(self, tmp_path: Path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"fake video data" * 1000)
        h = compute_file_hash(str(f))
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self, tmp_path: Path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"same content" * 500)
        assert compute_file_hash(str(f)) == compute_file_hash(str(f))

    def test_different_content_different_hash(self, tmp_path: Path):
        f1 = tmp_path / "a.mp4"
        f2 = tmp_path / "b.mp4"
        f1.write_bytes(b"content A" * 100)
        f2.write_bytes(b"content B" * 100)
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))

    def test_empty_file_has_known_hash(self, tmp_path: Path):
        f = tmp_path / "empty.mp4"
        f.write_bytes(b"")
        h = compute_file_hash(str(f))
        # SHA-256 of empty input is well-known
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
