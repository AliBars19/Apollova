#!/usr/bin/env python3
"""
Apollova Render Watcher — Production Grade
============================================

Watches After Effects render output folders for each template (Aurora, Mono, Onyx).
When a video finishes rendering, it's immediately uploaded and auto-scheduled.

Key behaviours:
  - Watches: Apollova-Aurora/jobs/renders/
             Apollova-Mono/jobs/renders/
             Apollova-Onyx/jobs/renders/
  - Folder determines account: Aurora→aurora, Mono/Onyx→nova
  - Each video uploads the instant AE finishes it (no batch waiting)
  - Auto-schedules with 1hr intervals, 11AM–11PM window
  - 12 videos/day/account limit — overflow rolls to next day automatically
  - Crash recovery via SQLite state

Usage:
    python render_watcher.py                 # Watch mode (continuous)
    python render_watcher.py --upload-now    # Upload any unprocessed videos
    python render_watcher.py --retry-failed  # Retry failed uploads
    python render_watcher.py --status        # Check API & OAuth status
    python render_watcher.py --stats         # Upload statistics
    python render_watcher.py --log           # Recent activity log
    python render_watcher.py --reset <id>    # Reset a failed record
    python render_watcher.py --purge         # Clean old records (>30d)
    python render_watcher.py --test          # Dry run (no real uploads)

Requirements:
    pip install requests watchdog rich
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from upload_state import StateManager, UploadStatus, compute_file_hash
from config import Config
from notification import NotificationService

try:
    from rich.console import Console as RichConsole
    from rich.table import Table
    from rich.panel import Panel
    _RICH = True
except ImportError:
    _RICH = False
    class Table:
        def __init__(self, **kw): self._rows = []
        def add_column(self, *a, **kw): pass
        def add_row(self, *a, **kw): self._rows.append(a)
    class Panel:
        def __init__(self, c="", **kw): self.c = c
        def __str__(self): return str(self.c)


class _NullConsole:
    """Silent console that does nothing — used when running headless."""
    def print(self, *a, **kw):
        pass


def _is_headless() -> bool:
    """Detect if we're running without a terminal (Task Scheduler, service, etc.)."""
    try:
        if sys.stdout is None or sys.stderr is None:
            return True
        if not hasattr(sys.stdout, "isatty"):
            return True
        return not sys.stdout.isatty()
    except Exception:
        return True


def _make_console():
    """Create appropriate console: Rich if interactive, silent if headless."""
    if _is_headless():
        return _NullConsole()
    if _RICH:
        return RichConsole()
    # Fallback: plain print with markup stripped
    import re as _re
    class _PlainConsole:
        def print(self, *a, **kw):
            text = " ".join(str(x) for x in a)
            print(_re.sub(r'\[/?[^\]]*\]', '', text))
    return _PlainConsole()


IS_HEADLESS = _is_headless()
console = _make_console()
logger = logging.getLogger("apollova")


# ─── Logging Setup ───────────────────────────────────────────────

def setup_logging(config: Config) -> None:
    root = logging.getLogger("apollova")
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = TimedRotatingFileHandler(
        log_dir / "render_watcher.log", when="midnight",
        backupCount=config.log_max_days, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    eh = TimedRotatingFileHandler(
        log_dir / "errors.log", when="midnight",
        backupCount=config.log_max_days, encoding="utf-8",
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)
    root.addHandler(eh)


# ─── Smart Scheduler ─────────────────────────────────────────────

class SmartScheduler:
    """Finds the next available schedule slot for an account.
    
    Rules:
      - Max 12 videos/day/account
      - 1-hour intervals between videos
      - Publishing window: 11AM – 11PM
      - If today is full, rolls to tomorrow (then day after, etc.)
      - Avoids double-booking a time slot
    """

    def __init__(self, config: Config, state: StateManager):
        self.config = config
        self.state = state

    def get_next_slot(self, account: str) -> datetime:
        """Find the next available schedule time for this account.
        
        Checks today first. If today has 12 already scheduled, moves to tomorrow.
        Within a day, places the video 1 hour after the last scheduled one,
        or at the start hour if nothing is scheduled yet.
        """
        now = datetime.now()
        check_date = now

        # Look up to 7 days ahead (should never need more)
        for day_offset in range(7):
            check_date = now + timedelta(days=day_offset)
            count = self.state.count_scheduled_for_date(account, check_date)

            if count >= self.config.videos_per_day_per_account:
                continue  # This day is full, try next

            # Day has room — find the next slot
            slot = self._find_slot_on_day(account, check_date, is_today=(day_offset == 0))
            if slot:
                return slot

        # Fallback: 7 days from now at start hour (shouldn't happen normally)
        fallback = (now + timedelta(days=7)).replace(
            hour=self.config.schedule_day_start_hour, minute=0, second=0, microsecond=0
        )
        logger.warning(f"All days full for {account}, using fallback: {fallback}")
        return fallback

    def _find_slot_on_day(self, account: str, date: datetime, is_today: bool) -> Optional[datetime]:
        """Find the next available slot on a specific day."""
        import random
        start_hour = self.config.schedule_day_start_hour
        end_hour = self.config.schedule_day_end_hour
        min_gap = self.config.schedule_interval_minutes
        jitter = self.config.schedule_interval_jitter_minutes

        # What's the last scheduled time on this day?
        last_time = self.state.get_last_scheduled_time(account, date)

        if last_time:
            # Random gap: min_gap + random(0, jitter) minutes after last slot
            gap = min_gap + random.randint(0, jitter)
            candidate = last_time + timedelta(minutes=gap)
            # Randomise the minutes too (not always on the hour)
            candidate = candidate.replace(second=0, microsecond=0)
        else:
            # Nothing scheduled yet — start somewhere in the first 2 hours of window
            start_offset = random.randint(0, 120)
            candidate = date.replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            ) + timedelta(minutes=start_offset)

        # If it's today and the candidate is in the past, bump to near-future
        if is_today:
            now = datetime.now()
            min_time = now + timedelta(minutes=10)  # At least 10 min from now
            if candidate < min_time:
                candidate = min_time

        # Check it's within the day's publishing window
        if candidate.hour >= end_hour:
            return None  # Day's window is over, caller will try next day

        # Avoid dead hours
        if self.config.dead_hours_start <= candidate.hour < self.config.dead_hours_end:
            candidate = candidate.replace(
                hour=self.config.dead_hours_end, minute=0, second=0, microsecond=0
            )

        return candidate


# ─── Video Uploader ──────────────────────────────────────────────

class VideoUploader:
    """Uploads videos to the Apollova website API.
    
    Features: exponential backoff retries, auto re-auth on 401, timeout handling.
    """

    def __init__(self, config: Config, test_mode: bool = False):
        self.config = config
        self.test_mode = test_mode
        self.session = requests.Session()
        self._authenticated = False
        self._auth_lock = threading.Lock()
        self._auth_failures = 0

    def authenticate(self) -> bool:
        with self._auth_lock:
            if self.test_mode:
                self._authenticated = True
                self._auth_failures = 0
                return True

            # Try primary URL, then fallback to macbookvisuals.com if DNS fails.
            urls_to_try = [self.config.api_base_url]
            fallback = "https://macbookvisuals.com"
            if fallback != self.config.api_base_url:
                urls_to_try.append(fallback)

            for url in urls_to_try:
                try:
                    resp = self.session.post(
                        f"{url}/api/auth/gate",
                        json={"password": self.config.gate_password},
                        timeout=self.config.api_timeout,
                    )
                    self._authenticated = resp.status_code == 200
                    if self._authenticated:
                        logger.info(f"Authenticated with website ({url})")
                        self._auth_failures = 0
                        # Promote fallback to primary so all requests use it
                        if url != self.config.api_base_url:
                            logger.info(f"Switching to fallback URL: {url}")
                            self.config.api_base_url = url
                        return True
                    else:
                        logger.error(f"Auth failed: HTTP {resp.status_code}")
                        break  # Wrong password — don't retry on different URL
                except requests.exceptions.ConnectionError as e:
                    if "getaddrinfo failed" in str(e) or "NameResolutionError" in str(e):
                        logger.warning(f"DNS failure for {url}, trying fallback...")
                        continue  # Try next URL
                    logger.error(f"Auth connection error: {e}")
                    break
                except requests.RequestException as e:
                    logger.error(f"Auth error: {e}")
                    break

            self._auth_failures = min(self._auth_failures + 1, 10)  # cap at 10 (max 300s backoff)
            return False

    def _ensure_auth(self) -> bool:
        if not self._authenticated:
            if self._auth_failures > 0:
                backoff = min(2 ** self._auth_failures, 300)
                logger.info(f"Auth backoff: waiting {backoff}s (failure #{self._auth_failures})")
                time.sleep(backoff)
            return self.authenticate()
        return True

    def check_status(self) -> Optional[dict]:
        try:
            resp = self.session.get(
                f"{self.config.api_base_url}/api/auth/status",
                timeout=self.config.api_timeout,
            )
            return resp.json() if resp.status_code == 200 else None
        except requests.RequestException as e:
            logger.error(f"Status check failed: {e}")
            return None

    def check_platform_health(self, notifications: "NotificationService") -> None:
        """Check if any platform tokens are disconnected and notify the user."""
        status = self.check_status()
        if not status or "accounts" not in status:
            return

        for account_id, platforms in status["accounts"].items():
            if not platforms.get("youtube"):
                logger.warning(f"YouTube DISCONNECTED for [{account_id}] — re-authenticate on dashboard")
                notifications.platform_disconnected(account_id, "YouTube")
            if not platforms.get("tiktok"):
                logger.warning(f"TikTok DISCONNECTED for [{account_id}] — re-authenticate on dashboard")
                notifications.platform_disconnected(account_id, "TikTok")

    def upload_video(self, file_path: str, account: str) -> tuple[Optional[dict], str]:
        """Upload with exponential backoff retries (2s -> 4s -> 8s).

        Returns (video_data, error_message). On success error_message is empty.
        """
        if self.test_mode:
            fake_id = f"test_{uuid.uuid4().hex[:8]}"
            logger.info(f"TEST: Would upload {Path(file_path).name} → {account}")
            return {"id": fake_id, "filename": Path(file_path).name}, ""

        filename = Path(file_path).name
        last_error = ""

        for attempt in range(self.config.max_upload_retries):
            if attempt > 0:
                delay = self.config.retry_base_delay * (2 ** (attempt - 1))
                logger.info(f"Retry {attempt}/{self.config.max_upload_retries} for {filename} in {delay:.0f}s")
                time.sleep(delay)

            if not self._ensure_auth():
                last_error = "Authentication failed"
                continue

            try:
                with open(file_path, "rb") as f:
                    resp = self.session.post(
                        f"{self.config.api_base_url}/api/upload",
                        files={"video": (filename, f, "video/mp4")},
                        data={"account": account},
                        timeout=self.config.upload_timeout,
                    )

                if resp.status_code == 200:
                    result = resp.json()
                    # API returns { success: true, video: { id: "...", ... } }
                    video_data = result.get("video", result)
                    vid = video_data.get("id", "?")
                    logger.info(f"Uploaded {filename} → {account} (id={vid})")
                    return video_data, ""

                if resp.status_code == 401:
                    self._authenticated = False
                    last_error = "Session expired"
                    continue

                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(f"Upload failed for {filename}: {last_error}")

            except requests.Timeout:
                last_error = "Upload timed out"
                logger.warning(f"Timeout uploading {filename}")
            except requests.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error: {e}")
            except OSError as e:
                last_error = f"File error: {e}"
                logger.error(f"Cannot read {filename}: {e}")
                break  # Don't retry file I/O errors

        logger.error(f"All attempts exhausted for {filename}: {last_error}")
        return None, last_error

    def schedule_video(self, video_id: str, scheduled_at: str) -> bool:
        if self.test_mode:
            logger.info(f"TEST: Would schedule {video_id} at {scheduled_at}")
            return True
        try:
            resp = self.session.patch(
                f"{self.config.api_base_url}/api/videos/{video_id}",
                json={"scheduledAt": scheduled_at, "status": "scheduled"},
                timeout=self.config.api_timeout,
            )
            if resp.status_code == 200:
                logger.info(f"Scheduled {video_id} at {scheduled_at}")
                return True
            else:
                logger.error(f"Schedule failed for {video_id}: HTTP {resp.status_code} - {resp.text[:300]}")
                return False
        except requests.RequestException as e:
            logger.error(f"Schedule error for {video_id}: {e}")
            return False


# ─── Quality Gate ────────────────────────────────────────────────

def validate_video_decodable(file_path: Path) -> tuple[bool, str]:
    """Return (ok, reason). Catches AE renders that pass size checks but
    contain corrupted NAL units / partial frames (machine throttled, GPU
    starved, etc.). Browsers play these as black screen with correct duration.
    """
    if not file_path.exists():
        return False, "file missing"
    if file_path.stat().st_size < 1 * 1024 * 1024:
        return False, f"file too small ({file_path.stat().st_size} bytes)"

    try:
        # 1. Stream count: must be exactly 1 video + 1 audio
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(file_path)],
            capture_output=True, text=True, timeout=30,
        )
        types = [t.strip() for t in probe.stdout.splitlines() if t.strip()]
        if types.count("video") != 1 or types.count("audio") != 1 or len(types) != 2:
            return False, f"bad stream layout: {types}"

        # 2. Decode test: scan for NAL/decode errors on stderr
        decode = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror",
             "-i", str(file_path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        err = decode.stderr.strip()
        if decode.returncode != 0 or err:
            short = err[:300] if err else f"returncode={decode.returncode}"
            return False, f"decode failed: {short}"

    except subprocess.TimeoutExpired:
        return False, "ffprobe/ffmpeg timeout"
    except FileNotFoundError:
        # ffmpeg/ffprobe missing — fail open with warning so uploads don't halt
        logger.warning("ffmpeg/ffprobe not on PATH — skipping decode validation")
        return True, "validation skipped (ffmpeg missing)"

    return True, "ok"


# ─── AE Broken-Render Recovery ───────────────────────────────────

def mux_ae_broken_renders(watch_path: Path) -> list[Path]:
    """Find .aac+.m4v pairs left by a frozen AE render and mux them into .mp4.

    AE renders video (.m4v) and audio (.aac) separately then muxes them.
    If AE freezes or is killed mid-mux it leaves behind files like:
        SongName_ONYX.12536.9760.m4v
        SongName_ONYX.12536.9760.aac
    This function detects those pairs, muxes via ffmpeg, deletes the
    originals, and returns the list of newly created .mp4 files.
    """
    muxed: list[Path] = []

    aac_files = list(watch_path.glob("*.aac"))
    if not aac_files:
        return muxed

    for aac in aac_files:
        m4v = aac.with_suffix(".m4v")
        if not m4v.exists():
            continue

        # Strip AE's numeric temp suffix: "Name.XXXXX.YYYYY" → "Name"
        clean_stem = re.sub(r"\.\d+\.\d+$", "", aac.stem)
        output = watch_path / f"{clean_stem}.mp4"

        # Don't overwrite if .mp4 already exists (e.g. from a previous mux)
        if output.exists():
            logger.info(f"AE mux recovery: {output.name} already exists, deleting broken files")
            aac.unlink(missing_ok=True)
            m4v.unlink(missing_ok=True)
            continue

        # Skip if either file is locked (AE still writing)
        locked = False
        for f in (aac, m4v):
            try:
                with open(f, "r+b"):
                    pass
            except (PermissionError, OSError):
                logger.debug(f"AE mux recovery: {f.name} still locked by AE, skipping")
                locked = True
                break
        if locked:
            continue

        # If either track is empty AE was killed before it finished rendering —
        # nothing to recover, just delete the debris
        aac_size = aac.stat().st_size
        m4v_size = m4v.stat().st_size
        if aac_size == 0 or m4v_size == 0:
            logger.warning(
                f"AE mux recovery: {clean_stem} has empty track "
                f"(aac={aac_size}B m4v={m4v_size}B) — AE died mid-render, "
                f"deleting debris. Re-render this job."
            )
            aac.unlink(missing_ok=True)
            m4v.unlink(missing_ok=True)
            continue

        logger.info(f"AE mux recovery: muxing {m4v.name} + {aac.name} → {output.name}")
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(m4v),
                    "-i", str(aac),
                    "-map", "0:v:0",   # only first video stream from m4v
                    "-map", "1:a:0",   # only audio from aac (ignore any audio in m4v)
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            min_size = 1 * 1024 * 1024  # expect at least 1MB; audio-only files are ~200KB
            if result.returncode == 0 and output.exists() and output.stat().st_size >= min_size:
                aac.unlink(missing_ok=True)
                m4v.unlink(missing_ok=True)
                logger.info(f"AE mux recovery: created {output.name} ({output.stat().st_size // 1024 // 1024}MB)")
                muxed.append(output)
            else:
                size = output.stat().st_size if output.exists() else 0
                logger.error(
                    f"AE mux recovery failed for {output.name}: "
                    f"returncode={result.returncode} size={size}B stderr={result.stderr[-300:]}"
                )
                if output.exists() and size < min_size:
                    output.unlink()  # delete suspiciously small output rather than queue it
        except subprocess.TimeoutExpired:
            logger.error(f"AE mux recovery timed out for {output.name}")
        except FileNotFoundError:
            logger.error("AE mux recovery: ffmpeg not found — install ffmpeg and add to PATH")
            break

    return muxed


# ─── Render Watcher ──────────────────────────────────────────────

class FolderWatcher(FileSystemEventHandler):
    """Watches a single renders folder. One instance per template folder.
    
    When a video finishes rendering (file size stabilises), it's immediately
    uploaded and scheduled — no waiting for a batch of 12.
    
    Uses a queue-based approach: filesystem events just add filenames to a set,
    and a single worker thread processes them one at a time. This eliminates
    all race conditions from multiple events firing for the same file.
    """

    def __init__(
        self,
        watch_path: Path,
        account: str,
        template: str,
        uploader: VideoUploader,
        state: StateManager,
        scheduler: SmartScheduler,
        notifications: NotificationService,
        config: Config,
    ):
        self.watch_path = watch_path
        self.account = account
        self.template = template
        self.uploader = uploader
        self.state = state
        self.scheduler = scheduler
        self.notifications = notifications
        self.config = config

        # Queue: pending filenames to process (set = auto-dedup)
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._event = threading.Event()
        # Single worker thread — no races possible
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def on_created(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def _enqueue(self, src_path: str) -> None:
        path = Path(src_path)
        # If AE drops a broken .aac or .m4v, try to mux it immediately.
        # The mux function is a no-op if the pair isn't complete yet — the
        # periodic health check will pick it up once both files exist.
        if path.suffix.lower() in (".aac", ".m4v"):
            muxed = mux_ae_broken_renders(self.watch_path)
            for mp4 in muxed:
                with self._lock:
                    self._pending.add(str(mp4))
            if muxed:
                self._event.set()
            return
        if path.suffix.lower() not in self.config.video_extensions:
            return
        with self._lock:
            self._pending.add(str(path))
        self._event.set()  # Wake the worker

    def _worker_loop(self) -> None:
        """Single worker: pulls files from the pending set one at a time."""
        while True:
            self._event.wait(timeout=5)
            self._event.clear()

            while True:
                # Grab one file from the pending set
                with self._lock:
                    if not self._pending:
                        break
                    file_str = self._pending.pop()

                file_path = Path(file_str)
                try:
                    self._process_video(file_path)
                except Exception as e:
                    logger.exception(f"Error processing {file_path.name}: {e}")

    def _process_video(self, file_path: Path) -> None:
        """Upload and schedule a single video the moment it's ready."""
        # Already in DB as uploaded? Skip entirely.
        if self.state.is_processed(str(file_path)):
            return

        # Wait for AE to fully finish writing
        if not self._wait_for_stable(file_path):
            logger.warning(f"File not stable, skipping: {file_path.name}")
            return

        # File might have been deleted while we waited
        if not file_path.exists():
            return

        # Hash + register in DB
        try:
            file_hash = compute_file_hash(str(file_path))
            file_size = file_path.stat().st_size
        except OSError as e:
            logger.error(f"Cannot read {file_path.name}: {e}")
            return

        # Atomic claim via DB
        record_id = self.state.add_upload(
            file_path=str(file_path),
            template=self.template,
            account=self.account,
            file_hash=file_hash,
            file_size=file_size,
        )

        if record_id == -1:
            logger.info(f"Skipping duplicate: {file_path.name} already uploaded to {self.account}")
            return

        if not self.state.try_claim(record_id):
            # Record exists but may be stuck in 'failed' — reset and retry
            record = self.state.get_record(record_id)
            if record and record.upload_status == UploadStatus.FAILED.value:
                logger.info(f"Resetting failed record for retry: {file_path.name}")
                self.state.reset_failed(record_id)
                if not self.state.try_claim(record_id):
                    return
            else:
                return  # Already uploading or uploaded

        console.print(f"[cyan]📹 {file_path.name}[/cyan] [dim]({self.template} → {self.account})[/dim]")
        logger.info(f"New video: {file_path.name} ({self.template} → {self.account})")

        # ── Quality gate ─────────────────────────────────────────
        ok, reason = validate_video_decodable(file_path)
        if not ok:
            error = f"corrupted render: {reason}"
            self.state.mark_upload_failed(record_id, error)
            console.print(f"  [red]✗ Quality gate failed: {reason}[/red]")
            console.print(f"  [yellow]Local file kept for re-render: {file_path}[/yellow]")
            logger.error(f"Quality gate FAIL {file_path.name}: {reason}")
            self.notifications.video_failed(file_path.name, error)
            return

        # ── Upload ───────────────────────────────────────────────
        result, upload_error = self.uploader.upload_video(str(file_path), self.account)

        if not result or "id" not in result:
            error = upload_error or "Upload returned no result"
            self.state.mark_upload_failed(record_id, error)
            console.print(f"  [red]✗ Upload failed: {error}[/red]")
            self.notifications.video_failed(file_path.name, error)
            return

        video_id = result["id"]
        self.state.mark_uploaded(record_id, video_id)

        # ── Schedule ─────────────────────────────────────────────
        slot = self.scheduler.get_next_slot(self.account)
        slot_iso = slot.isoformat()
        logger.info(f"Scheduling {file_path.name} (video_id={video_id}) at {slot_iso}")

        if self.uploader.schedule_video(video_id, slot_iso):
            self.state.mark_scheduled(record_id, slot_iso)
            is_today = slot.date() == datetime.now().date()
            day_label = "today" if is_today else slot.strftime("%a %d %b")
            console.print(
                f"  [green]✓ Uploaded & scheduled → {slot.strftime('%H:%M')} {day_label}[/green]"
            )
            self.notifications.video_uploaded(file_path.name, self.account, slot.strftime("%H:%M %d/%m"))

            # ── Auto-delete local file after successful upload + schedule ──
            if not self.uploader.test_mode:
                try:
                    file_path.unlink()
                    logger.info(f"Deleted local file: {file_path.name}")
                except OSError as e:
                    logger.warning(f"Could not delete {file_path.name}: {e}")
            else:
                logger.info(f"TEST: Would delete {file_path.name}")
        else:
            self.state.mark_schedule_failed(record_id, "Schedule API failed")
            console.print(f"  [yellow]⚠ Uploaded but scheduling failed[/yellow]")

    def _wait_for_stable(self, file_path: Path, timeout: float = 180) -> bool:
        """Wait for file size to stop changing, then wait an extra 30s to be safe."""
        start = time.time()
        wait = self.config.file_stable_wait

        for _ in range(self.config.file_stable_checks + 10):  # extra attempts for large files
            if time.time() - start > timeout:
                return False
            try:
                size1 = file_path.stat().st_size
                if size1 == 0:
                    time.sleep(wait)
                    continue
                time.sleep(wait)
                size2 = file_path.stat().st_size
                if size1 == size2:
                    # Confirm file is not locked
                    try:
                        with open(file_path, "rb") as f:
                            f.read(1)
                    except (PermissionError, OSError):
                        time.sleep(wait)
                        continue

                    # File is stable and unlocked — wait for AE to fully move on
                    extra = self.config.file_stable_extra_wait
                    if extra > 0:
                        logger.info(f"File stable, waiting {extra:.0f}s before upload: {file_path.name}")
                        time.sleep(extra)

                    # Final check: file still exists and size unchanged
                    try:
                        if file_path.stat().st_size == size2:
                            return True
                    except FileNotFoundError:
                        return False
            except FileNotFoundError:
                return False
        return False

    def scan_unprocessed(self) -> list[Path]:
        """Find videos in this folder that haven't been uploaded yet.

        Also rescues any .aac+.m4v pairs left by a frozen AE render before
        scanning — so stuck renders are automatically recovered and queued.
        """
        mux_ae_broken_renders(self.watch_path)

        videos = []
        for ext in self.config.video_extensions:
            videos.extend(self.watch_path.glob(f"*{ext}"))
            videos.extend(self.watch_path.glob(f"*{ext.upper()}"))

        return sorted(
            [v for v in set(videos) if not self.state.is_processed(str(v))],
            key=lambda x: x.stat().st_mtime,
        )


# ─── CLI Display ─────────────────────────────────────────────────

def show_status(config: Config) -> None:
    console.print("\n[bold]🔍 Connection Status[/bold]\n")
    try:
        resp = requests.get(f"{config.api_base_url}/api/auth/status", timeout=5)
        if resp.status_code != 200:
            console.print(f"[red]✗ Server returned {resp.status_code}[/red]")
            return
        console.print(f"[green]✓ Connected to {config.api_base_url}[/green]")
        status = resp.json()
    except Exception as e:
        console.print(f"[red]✗ Cannot connect: {e}[/red]")
        return

    table = Table(title="OAuth Status")
    table.add_column("Account", style="cyan")
    table.add_column("YouTube", style="green")
    table.add_column("TikTok", style="magenta")
    for acct in ["aurora", "nova"]:
        if acct in status:
            a = status[acct]
            yt = ("✓ " + a.get("youtubeName", "OK")) if a.get("youtube") else "✗ Not connected"
            tt = ("✓ " + a.get("tiktokName", "OK")) if a.get("tiktok") else "✗ Not connected"
            table.add_row(acct.capitalize(), yt, tt)
    console.print(table)
    console.print()


def show_stats(state: StateManager) -> None:
    stats = state.get_stats()
    table = Table(title="Upload Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")

    style_map = {"pending": "yellow", "uploading": "blue", "uploaded": "green", "failed": "red"}
    for key, count in stats.items():
        if key == "total":
            continue
        style = style_map.get(key, "white")
        label = key.replace("_today", " (today)").replace("_", " ").title()
        table.add_row(f"[{style}]{label}[/{style}]", str(count))
    table.add_row("[bold]Total[/bold]", f"[bold]{stats.get('total', 0)}[/bold]")
    console.print(table)
    console.print()


def show_log(state: StateManager, limit: int = 30) -> None:
    entries = state.get_recent_log(limit)
    if not entries:
        console.print("[dim]No activity[/dim]")
        return

    table = Table(title=f"Recent Activity (last {limit})")
    table.add_column("Time", style="dim", width=19)
    table.add_column("File", style="cyan", max_width=40)
    table.add_column("Account", style="magenta")
    table.add_column("Action", style="yellow")
    table.add_column("Message", max_width=40)

    for e in entries:
        table.add_row(
            (e.get("created_at") or "")[:19],
            e.get("file_name", "?"),
            e.get("account", "?"),
            e.get("action", ""),
            (e.get("message") or "")[:40],
        )
    console.print(table)
    console.print()


# ─── Watch Mode ──────────────────────────────────────────────────

def watch_mode(
    uploader: VideoUploader,
    state: StateManager,
    smart_scheduler: SmartScheduler,
    notifications: NotificationService,
    config: Config,
) -> None:
    """Watch all template render folders simultaneously."""

    # Recover any records stuck in "uploading" from a crash
    for stuck in state.get_uploading():
        state.reset_failed(stuck.id)
        logger.info(f"Recovered interrupted upload: {stuck.file_name}")

    watch_paths = config.get_watch_paths()

    # Display what we're watching (may fail headless — non-fatal)
    try:
        lines = []
        for folder_name, (path, account) in watch_paths.items():
            exists = "✓" if path.exists() else "✗ (will create)"
            template = folder_name.replace("Apollova-", "").lower()
            lines.append(f"  {template.capitalize():8s} → {account:8s}  {path}  {exists}")

        console.print(Panel(
            "[bold]Watching render folders:[/bold]\n" +
            "\n".join(lines) + "\n\n"
            f"[bold]Schedule:[/bold] {config.schedule_interval_minutes}min intervals, "
            f"{config.schedule_day_start_hour}:00–{config.schedule_day_end_hour}:00\n"
            f"[bold]Limit:[/bold] {config.videos_per_day_per_account}/day per account "
            f"(overflow → next day)\n"
            "[dim]Press Ctrl+C to stop[/dim]",
            title="Render Watcher Active",
            border_style="cyan",
        ))
    except Exception:
        pass  # Console output failed (headless) — non-fatal

    config.ensure_dirs()

    # Create a watcher + observer for each folder
    observer = Observer()
    watchers: list[FolderWatcher] = []

    for folder_name, (watch_path, account) in watch_paths.items():
        template = folder_name.replace("Apollova-", "").lower()
        watcher = FolderWatcher(
            watch_path=watch_path,
            account=account,
            template=template,
            uploader=uploader,
            state=state,
            scheduler=smart_scheduler,
            notifications=notifications,
            config=config,
        )
        watchers.append(watcher)
        observer.schedule(watcher, str(watch_path), recursive=False)
        logger.info(f"Watching: {watch_path} ({template} → {account})")

    # Check platform health on startup — notify if any tokens are dead
    uploader.check_platform_health(notifications)

    # Check for existing unprocessed videos
    total_unprocessed = 0
    for w in watchers:
        unprocessed = w.scan_unprocessed()
        if unprocessed:
            total_unprocessed += len(unprocessed)

    if total_unprocessed > 0:
        logger.info(f"Found {total_unprocessed} unprocessed videos — uploading automatically")
        console.print(f"\n[yellow]Found {total_unprocessed} unprocessed videos — uploading now...[/yellow]")
        for w in watchers:
            for video in w.scan_unprocessed():
                w._process_video(video)

    # Start watching
    observer.start()
    logger.info("Render watcher started")
    try:
        console.print("\n[green]Watching for new renders...[/green]\n")
    except Exception:
        pass  # Encoding error in headless mode — non-fatal

    last_health_check = time.monotonic()
    health_check_interval = 3600  # 1 hour
    last_mux_check = time.monotonic()
    mux_check_interval = 60  # check for broken AE renders every minute

    try:
        while True:
            time.sleep(10)

            # Observer liveness check — watchdog can silently die on Windows
            # (e.g. ReadDirectoryChangesW error after sleep/resume).
            if not observer.is_alive():
                logger.warning("Filesystem observer died — signalling restart")
                break

            # Periodic mux recovery — catches .aac+.m4v pairs from frozen AE
            if time.monotonic() - last_mux_check > mux_check_interval:
                for w in watchers:
                    muxed = mux_ae_broken_renders(w.watch_path)
                    for mp4 in muxed:
                        w._process_video(mp4)
                last_mux_check = time.monotonic()
            # Periodic health check every hour
            if time.monotonic() - last_health_check > health_check_interval:
                uploader.check_platform_health(notifications)
                last_health_check = time.monotonic()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Watcher stopped")
        raise  # Let caller know so restart loop doesn't re-enter on clean exit
    except Exception as e:
        logger.exception(f"Watch loop crashed: {e}")
    finally:
        observer.stop()
        observer.join(timeout=10)  # Never hang forever waiting for Observer thread
        if observer.is_alive():
            logger.warning("Observer did not stop cleanly within 10s — forcing exit")


# ─── Main ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apollova Render Watcher — Auto upload & schedule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--upload-now", action="store_true", help="Upload all unprocessed videos now")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed uploads")
    parser.add_argument("--status", action="store_true", help="Check API & OAuth status")
    parser.add_argument("--stats", action="store_true", help="Show upload statistics")
    parser.add_argument("--log", action="store_true", help="Show recent activity log")
    parser.add_argument("--reset", type=int, metavar="ID", help="Reset a failed record")
    parser.add_argument("--purge", action="store_true", help="Purge old records (>30 days)")
    parser.add_argument("--test", action="store_true", help="Test mode (no real uploads)")
    parser.add_argument("--root", type=str, help="Apollova root directory")
    parser.add_argument("--env", type=str, help="Path to .env file")
    args = parser.parse_args()

    config = Config.from_env(env_path=args.env)
    if args.root:
        config.apollova_root = args.root

    setup_logging(config)

    console.print("[bold magenta]🎬 Apollova Render Watcher[/bold magenta]")
    console.print("[dim]v2.0 — Per-video upload with smart scheduling[/dim]\n")

    if args.test:
        console.print("[bold yellow]⚠ TEST MODE — No actual uploads[/bold yellow]\n")

    # ── No-auth commands ─────────────────────────────────────────
    if args.status:
        show_status(config)
        return

    state = StateManager(config.state_db_path)

    if args.stats:
        show_stats(state)
        return
    if args.log:
        show_log(state)
        return
    if args.reset:
        state.reset_failed(args.reset)
        console.print(f"[green]✓ Reset record #{args.reset}[/green]")
        return
    if args.purge:
        n = state.purge_old(30)
        console.print(f"[green]✓ Purged {n} old records[/green]")
        return

    # ── Auth-required commands ───────────────────────────────────
    config.validate_or_exit()

    uploader = VideoUploader(config, test_mode=args.test)
    smart_scheduler = SmartScheduler(config, state)
    notifications = NotificationService(enabled=config.notifications_enabled)

    if not uploader.authenticate():
        console.print("[red]Failed to authenticate. Check GATE_PASSWORD.[/red]")
        notifications.auth_failed()
        sys.exit(1)

    if args.upload_now:
        config.ensure_dirs()
        for folder_name, (watch_path, account) in config.get_watch_paths().items():
            template = folder_name.replace("Apollova-", "").lower()
            watcher = FolderWatcher(
                watch_path, account, template,
                uploader, state, smart_scheduler, notifications, config,
            )
            for video in watcher.scan_unprocessed():
                watcher._process_video(video)
        return

    if args.retry_failed:
        retryable = state.get_retryable(config.max_upload_retries)
        if not retryable:
            console.print("[green]No failed uploads to retry[/green]")
            return
        console.print(f"[cyan]Retrying {len(retryable)} failed uploads...[/cyan]")
        config.ensure_dirs()
        for record in retryable:
            state.reset_failed(record.id)
            if not Path(record.file_path).exists():
                console.print(f"  [dim]Skipping {record.file_name} (file missing)[/dim]")
                continue
            # Determine the right watcher context
            template = record.template
            account = record.account
            fw = FolderWatcher(
                Path(record.file_path).parent, account, template,
                uploader, state, smart_scheduler, notifications, config,
            )
            fw._process_video(Path(record.file_path))
        return

    # ── Default: Watch mode (with self-restart) ──────────────────
    while True:
        try:
            watch_mode(uploader, state, smart_scheduler, notifications, config)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Watcher exiting cleanly")
            break
        except Exception as e:
            logger.exception(f"watch_mode crashed, restarting in 30s: {e}")
            time.sleep(30)
            continue
        else:
            # watch_mode returned normally (observer died and broke out of loop)
            logger.warning("watch_mode exited unexpectedly — restarting in 10s")
            time.sleep(10)
            continue


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Ensure any crash gets logged — critical for debugging Task Scheduler failures
        logging.getLogger("apollova").exception(f"Fatal crash: {e}")
        # Also write to a crash file in case logging isn't set up yet
        try:
            crash_file = Path(__file__).parent / "logs" / "crash.log"
            crash_file.parent.mkdir(parents=True, exist_ok=True)
            with open(crash_file, "a", encoding="utf-8") as f:
                import traceback
                f.write(f"\n{'='*60}\n")
                f.write(f"{datetime.now().isoformat()}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise