"""
Tests for FolderWatcher watch loop internals.

Covers:
  - File stability polling: file_stable_wait, file_stable_checks config values honoured
  - File changing during stability window is NOT dispatched (size keeps growing)
  - Stable file IS dispatched (size stops changing)
  - Video extension filtering in _enqueue()
  - Non-video files are silently dropped by _enqueue()
  - Zero-byte file during polling is not prematurely treated as stable
  - File disappearing during polling returns False
  - _enqueue deduplicates: two events for the same path produce one pending entry
  - Worker processes files sequentially (no parallel race)
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "upload"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watcher(upload_config, upload_state, watch_dir, *, test_mode=True):
    from render_watcher import FolderWatcher, SmartScheduler, VideoUploader

    uploader = VideoUploader(upload_config, test_mode=test_mode)
    uploader._authenticated = True
    scheduler = SmartScheduler(upload_config, upload_state)
    notifications = MagicMock()

    return FolderWatcher(
        watch_path=watch_dir,
        account="nova",
        template="mono",
        uploader=uploader,
        state=upload_state,
        scheduler=scheduler,
        notifications=notifications,
        config=upload_config,
    )


def _fake_video(directory: Path, name: str = "clip.mp4", size: int = 1024) -> Path:
    p = directory / name
    p.write_bytes(b"\x00" * size)
    return p


# ---------------------------------------------------------------------------
# Extension filtering
# ---------------------------------------------------------------------------

class TestExtensionFiltering:

    def test_mp4_added_to_pending(self, upload_config, upload_state, tmp_path):
        """An .mp4 file must be enqueued."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "music.mp4"
        video.write_bytes(b"data")

        with watcher._lock:
            initial = set(watcher._pending)

        watcher._enqueue(str(video))

        with watcher._lock:
            assert str(video) in watcher._pending

    def test_mov_added_to_pending(self, upload_config, upload_state, tmp_path):
        """An .mov file must be enqueued."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "music.mov"
        video.write_bytes(b"data")
        watcher._enqueue(str(video))

        with watcher._lock:
            assert str(video) in watcher._pending

    def test_txt_not_added_to_pending(self, upload_config, upload_state, tmp_path):
        """A .txt file must be silently ignored."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        text_file = watch_dir / "readme.txt"
        text_file.write_bytes(b"not a video")
        watcher._enqueue(str(text_file))

        with watcher._lock:
            assert str(text_file) not in watcher._pending

    def test_jpg_not_added_to_pending(self, upload_config, upload_state, tmp_path):
        """A .jpg file must be silently ignored."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        img = watch_dir / "thumbnail.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        watcher._enqueue(str(img))

        with watcher._lock:
            assert str(img) not in watcher._pending

    def test_ae_project_file_not_added(self, upload_config, upload_state, tmp_path):
        """An .aep After Effects project file must be silently ignored."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        ae_file = watch_dir / "project.aep"
        ae_file.write_bytes(b"ae project data")
        watcher._enqueue(str(ae_file))

        with watcher._lock:
            assert str(ae_file) not in watcher._pending

    def test_uppercase_extension_is_not_filtered(self, upload_config, upload_state, tmp_path):
        """Extension check must be case-insensitive (.MP4 matches .mp4)."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        # Manually test what suffix.lower() produces for an uppercase ext path
        # Our config.video_extensions are [".mp4", ".mov"] (lowercase)
        # _enqueue does: path.suffix.lower() not in self.config.video_extensions
        video = watch_dir / "VIDEO.MP4"
        video.write_bytes(b"data")
        watcher._enqueue(str(video))

        with watcher._lock:
            assert str(video) in watcher._pending

    def test_enqueue_deduplicates_same_path(self, upload_config, upload_state, tmp_path):
        """Multiple events for the same file must not add duplicates to pending."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "clip.mp4"
        video.write_bytes(b"data")

        watcher._enqueue(str(video))
        watcher._enqueue(str(video))
        watcher._enqueue(str(video))

        with watcher._lock:
            count = sum(1 for p in watcher._pending if p == str(video))

        assert count == 1


# ---------------------------------------------------------------------------
# File stability polling (_wait_for_stable)
# ---------------------------------------------------------------------------

class TestFileStabilityPolling:

    def test_stable_file_returns_true(self, upload_config, upload_state, tmp_path):
        """A file whose size does not change must be reported as stable."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        # file_stable_wait=0, file_stable_checks=1 from upload_config fixture
        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_checks = 1
        upload_config.file_stable_extra_wait = 0.0

        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "stable.mp4"
        video.write_bytes(b"\x00" * 2048)

        result = watcher._wait_for_stable(video, timeout=5)
        assert result is True

    def test_growing_file_returns_false_before_timeout(self, upload_config, upload_state, tmp_path):
        """A file whose size keeps changing must not be considered stable before timeout.

        Strategy: patch stat() so it always returns a different size on each call,
        guaranteeing the stability check never sees two equal sizes within the timeout.
        """
        import os
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_checks = 1
        upload_config.file_stable_extra_wait = 0.0

        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "growing.mp4"
        video.write_bytes(b"\x00" * 1024)

        call_counter = [0]
        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            # Return a different st_size on every call by adding call_counter
            call_counter[0] += 1
            # Use os.stat_result constructor — easier to just monkey-patch st_size
            # via a wrapper object
            class FakeStat:
                def __getattr__(self, name):
                    return getattr(result, name)
                @property
                def st_size(self):
                    return result.st_size + call_counter[0]

            return FakeStat()

        with patch("pathlib.Path.stat", side_effect=lambda self=None: fake_stat(str(video))):
            result = watcher._wait_for_stable(video, timeout=0.15)

        assert result is False

    def test_zero_byte_file_is_not_stable(self, upload_config, upload_state, tmp_path):
        """A file with size 0 must not be treated as stable (write not yet started)."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_extra_wait = 0.0

        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "empty.mp4"
        video.write_bytes(b"")

        # With a short timeout the zero-byte file should not pass stability check
        result = watcher._wait_for_stable(video, timeout=0.1)
        # zero bytes -> keeps retrying -> times out
        assert result is False

    def test_missing_file_returns_false(self, upload_config, upload_state, tmp_path):
        """If the file does not exist at all, _wait_for_stable must return False."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_extra_wait = 0.0

        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        ghost = watch_dir / "nonexistent.mp4"
        result = watcher._wait_for_stable(ghost, timeout=0.1)
        assert result is False

    def test_extra_wait_is_honoured(self, upload_config, upload_state, tmp_path):
        """file_stable_extra_wait must cause a sleep after the file is confirmed stable."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_checks = 1
        upload_config.file_stable_extra_wait = 0.5  # half-second extra wait

        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "stable_extra.mp4"
        video.write_bytes(b"\x00" * 512)

        slept_for = []
        original_sleep = time.sleep

        def tracking_sleep(secs):
            slept_for.append(secs)
            original_sleep(min(secs, 0.01))  # Cap actual sleep for test speed

        with patch("render_watcher.time.sleep", side_effect=tracking_sleep):
            watcher._wait_for_stable(video, timeout=5)

        # The extra wait (0.5) should appear in the recorded sleeps
        assert any(s == 0.5 for s in slept_for), f"extra_wait 0.5 not found in sleeps: {slept_for}"


# ---------------------------------------------------------------------------
# Event dispatch integration (on_created / on_modified)
# ---------------------------------------------------------------------------

class TestEventDispatch:

    def test_on_created_enqueues_video(self, upload_config, upload_state, tmp_path):
        """on_created for a video file must add it to _pending."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "new.mp4"
        video.write_bytes(b"data")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(video)

        watcher.on_created(event)

        with watcher._lock:
            assert str(video) in watcher._pending

    def test_on_modified_enqueues_video(self, upload_config, upload_state, tmp_path):
        """on_modified for a video file must add it to _pending."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        video = watch_dir / "mod.mp4"
        video.write_bytes(b"data")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(video)

        watcher.on_modified(event)

        with watcher._lock:
            assert str(video) in watcher._pending

    def test_directory_event_is_ignored(self, upload_config, upload_state, tmp_path):
        """Directory creation events must not be enqueued."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        watcher = _make_watcher(upload_config, upload_state, watch_dir)

        event = MagicMock()
        event.is_directory = True
        event.src_path = str(watch_dir / "subdir")

        with watcher._lock:
            before = set(watcher._pending)

        watcher.on_created(event)

        with watcher._lock:
            assert watcher._pending == before


# ---------------------------------------------------------------------------
# Worker loop: stable files ARE dispatched
# ---------------------------------------------------------------------------

class TestWorkerLoopDispatch:

    def test_stable_video_is_processed_by_worker(self, upload_config, upload_state, tmp_path):
        """A stable video enqueued via _enqueue() must be processed by the worker."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        upload_config.file_stable_wait = 0.0
        upload_config.file_stable_extra_wait = 0.0
        upload_config.file_stable_checks = 1

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        video = watch_dir / "ready.mp4"
        video.write_bytes(b"\x00" * 512)

        processed = []

        def fake_process_video(path):
            processed.append(path)

        with patch.object(watcher, "_process_video", side_effect=fake_process_video):
            watcher._enqueue(str(video))
            # Give the daemon worker thread time to pick it up
            deadline = time.time() + 3.0
            while not processed and time.time() < deadline:
                time.sleep(0.05)

        assert len(processed) == 1
        assert processed[0] == video

    def test_non_video_is_never_processed(self, upload_config, upload_state, tmp_path):
        """A .log file enqueued indirectly (bypassing _enqueue filter) must not be processed."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        watcher = _make_watcher(upload_config, upload_state, watch_dir)
        log_file = watch_dir / "render.log"
        log_file.write_bytes(b"log data")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(log_file)

        processed = []
        with patch.object(watcher, "_process_video", side_effect=processed.append):
            watcher.on_created(event)
            time.sleep(0.2)  # Worker has ample time to act if it were going to

        assert len(processed) == 0
