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
import sys
import time
import uuid
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from upload_state import StateManager, UploadStatus, ScheduleStatus, compute_file_hash
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
        start_hour = self.config.schedule_day_start_hour
        end_hour = self.config.schedule_day_end_hour
        interval = self.config.schedule_interval_minutes

        # What's the last scheduled time on this day?
        last_time = self.state.get_last_scheduled_time(account, date)

        if last_time:
            # Schedule `interval` minutes after the last one
            candidate = last_time + timedelta(minutes=interval)
        else:
            # Nothing scheduled yet — start at the start hour
            candidate = date.replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            )

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

    def authenticate(self) -> bool:
        with self._auth_lock:
            if self.test_mode:
                self._authenticated = True
                return True
            try:
                resp = self.session.post(
                    f"{self.config.api_base_url}/api/auth/gate",
                    json={"password": self.config.gate_password},
                    timeout=self.config.api_timeout,
                )
                self._authenticated = resp.status_code == 200
                if self._authenticated:
                    logger.info("Authenticated with website")
                else:
                    logger.error(f"Auth failed: HTTP {resp.status_code}")
                return self._authenticated
            except requests.RequestException as e:
                logger.error(f"Auth error: {e}")
                return False

    def _ensure_auth(self) -> bool:
        if not self._authenticated:
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

    def upload_video(self, file_path: str, account: str) -> Optional[dict]:
        """Upload with exponential backoff retries (2s → 4s → 8s)."""
        if self.test_mode:
            fake_id = f"test_{uuid.uuid4().hex[:8]}"
            logger.info(f"TEST: Would upload {Path(file_path).name} → {account}")
            return {"id": fake_id, "filename": Path(file_path).name}

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
                        files={"file": (filename, f, "video/mp4")},
                        data={"account": account},
                        timeout=self.config.upload_timeout,
                    )

                if resp.status_code == 200:
                    result = resp.json()
                    logger.info(f"Uploaded {filename} → {account} (id={result.get('id', '?')})")
                    return result

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
        return None

    def schedule_video(self, video_id: str, scheduled_at: str) -> bool:
        if self.test_mode:
            logger.info(f"TEST: Would schedule {video_id} at {scheduled_at}")
            return True
        try:
            resp = self.session.put(
                f"{self.config.api_base_url}/api/videos/{video_id}",
                json={"scheduledAt": scheduled_at, "status": "scheduled"},
                timeout=self.config.api_timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Schedule error for {video_id}: {e}")
            return False


# ─── Render Watcher ──────────────────────────────────────────────

class FolderWatcher(FileSystemEventHandler):
    """Watches a single renders folder. One instance per template folder.
    
    When a video finishes rendering (file size stabilises), it's immediately
    uploaded and scheduled — no waiting for a batch of 12.
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
        self._seen: dict[str, float] = {}  # debounce tracker

    def on_created(self, event):
        if not event.is_directory:
            self._debounced_handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._debounced_handle(event.src_path)

    def _debounced_handle(self, src_path: str) -> None:
        path = Path(src_path)
        if path.suffix.lower() not in self.config.video_extensions:
            return

        now = time.time()
        if now - self._seen.get(str(path), 0) < self.config.debounce_seconds:
            return
        self._seen[str(path)] = now

        # Process in separate thread so we don't block the observer
        threading.Thread(target=self._process_video, args=(path,), daemon=True).start()

    def _process_video(self, file_path: Path) -> None:
        """Upload and schedule a single video the moment it's ready."""
        # Already done?
        if self.state.is_processed(str(file_path)):
            return

        # Wait for AE to finish writing
        if not self._wait_for_stable(file_path):
            logger.warning(f"File not stable, skipping: {file_path.name}")
            return

        console.print(f"[cyan]📹 {file_path.name}[/cyan] [dim]({self.template} → {self.account})[/dim]")
        logger.info(f"New video: {file_path.name} ({self.template} → {self.account})")

        # Hash + register in DB
        try:
            file_hash = compute_file_hash(str(file_path))
            file_size = file_path.stat().st_size
        except OSError as e:
            logger.error(f"Cannot read {file_path.name}: {e}")
            return

        record_id = self.state.add_upload(
            file_path=str(file_path),
            template=self.template,
            account=self.account,
            file_hash=file_hash,
            file_size=file_size,
        )

        # ── Upload ───────────────────────────────────────────────
        self.state.mark_uploading(record_id)
        result = self.uploader.upload_video(str(file_path), self.account)

        if not result or "id" not in result:
            error = "Upload returned no result"
            self.state.mark_upload_failed(record_id, error)
            console.print(f"  [red]✗ Upload failed[/red]")
            self.notifications.video_failed(file_path.name, error)
            return

        video_id = result["id"]
        self.state.mark_uploaded(record_id, video_id)

        # ── Schedule ─────────────────────────────────────────────
        slot = self.scheduler.get_next_slot(self.account)
        slot_iso = slot.isoformat()

        if self.uploader.schedule_video(video_id, slot_iso):
            self.state.mark_scheduled(record_id, slot_iso)
            is_today = slot.date() == datetime.now().date()
            day_label = "today" if is_today else slot.strftime("%a %d %b")
            console.print(
                f"  [green]✓ Uploaded & scheduled → {slot.strftime('%H:%M')} {day_label}[/green]"
            )
            self.notifications.video_uploaded(file_path.name, self.account, slot.strftime("%H:%M %d/%m"))
        else:
            self.state.mark_schedule_failed(record_id, "Schedule API failed")
            console.print(f"  [yellow]⚠ Uploaded but scheduling failed[/yellow]")

    def _wait_for_stable(self, file_path: Path, timeout: float = 120) -> bool:
        """Wait for file size to stop changing (AE finished writing)."""
        start = time.time()
        wait = self.config.file_stable_wait

        for _ in range(self.config.file_stable_checks + 5):  # extra attempts for large files
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
                        return True
                    except (PermissionError, OSError):
                        time.sleep(wait)
                        continue
            except FileNotFoundError:
                return False
        return False

    def scan_unprocessed(self) -> list[Path]:
        """Find videos in this folder that haven't been uploaded yet."""
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

    # Check for existing unprocessed videos
    total_unprocessed = 0
    for w in watchers:
        unprocessed = w.scan_unprocessed()
        if unprocessed:
            total_unprocessed += len(unprocessed)

    if total_unprocessed > 0:
        logger.info(f"Found {total_unprocessed} unprocessed videos")
        should_upload = True
        if not IS_HEADLESS:
            try:
                console.print(f"\n[yellow]Found {total_unprocessed} unprocessed videos across all folders[/yellow]")
                resp = input("Upload them now? (y/N): ").strip().lower()
                should_upload = resp == "y"
            except (EOFError, KeyboardInterrupt, OSError):
                should_upload = False
        else:
            logger.info(f"Headless mode: auto-uploading {total_unprocessed} existing videos")

        if should_upload:
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

    try:
        while True:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Watcher stopped")
    except Exception as e:
        logger.exception(f"Watch loop crashed: {e}")
    finally:
        observer.stop()
        observer.join()


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

    # ── Default: Watch mode ──────────────────────────────────────
    watch_mode(uploader, state, smart_scheduler, notifications, config)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Ensure any crash gets logged — critical for debugging Task Scheduler failures
        logging.getLogger("apollova").exception(f"Fatal crash: {e}")
        # Also write to a crash file in case logging isn't set up yet
        try:
            from pathlib import Path
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