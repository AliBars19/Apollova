"""
Tests for upload/render_watcher.py — scheduler, uploader, and watcher edge cases.

Covers:
  - SmartScheduler: first slot, subsequent +1hr, day full rolls, 7-day fallback, dead hours
  - VideoUploader: auth success/failure, upload retry logic, test_mode
  - FolderWatcher: video extension filtering, scan sorted by mtime
"""
from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add upload/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "upload"))


# ---------------------------------------------------------------------------
# SmartScheduler
# ---------------------------------------------------------------------------

class TestSmartScheduler:

    def _make_scheduler(self, upload_config, upload_state):
        from render_watcher import SmartScheduler
        return SmartScheduler(upload_config, upload_state)

    def test_first_slot_at_start_hour(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        slot = scheduler.get_next_slot("aurora")
        assert slot.hour >= upload_config.schedule_day_start_hour

    def test_subsequent_slot_plus_interval(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        # Schedule first slot
        slot1 = scheduler.get_next_slot("aurora")
        # Simulate a video scheduled at slot1
        upload_state.count_scheduled_for_date = MagicMock(return_value=1)
        upload_state.get_last_scheduled_time = MagicMock(return_value=slot1)
        slot2 = scheduler.get_next_slot("aurora")
        diff = (slot2 - slot1).total_seconds() / 60
        assert diff >= upload_config.schedule_interval_minutes

    def test_day_full_rolls_to_next(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        # Make today full
        upload_state.count_scheduled_for_date = MagicMock(return_value=12)
        slot = scheduler.get_next_slot("aurora")
        # Should be tomorrow or later
        today = datetime.now().date()
        assert slot.date() > today

    def test_seven_day_fallback(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        # Make all days full
        upload_state.count_scheduled_for_date = MagicMock(return_value=999)
        slot = scheduler.get_next_slot("aurora")
        now = datetime.now()
        fallback_date = (now + timedelta(days=7)).date()
        assert slot.date() == fallback_date

    def test_dead_hours_avoided(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        slot = scheduler.get_next_slot("aurora")
        assert not (upload_config.dead_hours_start <= slot.hour < upload_config.dead_hours_end)

    def test_past_candidate_bumped(self, upload_config, upload_state):
        scheduler = self._make_scheduler(upload_config, upload_state)
        # Last scheduled time was yesterday
        yesterday = datetime.now() - timedelta(days=1)
        upload_state.get_last_scheduled_time = MagicMock(return_value=yesterday)
        upload_state.count_scheduled_for_date = MagicMock(return_value=1)
        slot = scheduler.get_next_slot("aurora")
        assert slot > datetime.now()


# ---------------------------------------------------------------------------
# VideoUploader
# ---------------------------------------------------------------------------

class TestVideoUploaderAuth:

    def test_auth_success(self, upload_config):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        with patch.object(uploader.session, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            mock_post.return_value = resp
            assert uploader.authenticate() is True

    def test_auth_failure_401(self, upload_config):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        with patch.object(uploader.session, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 401
            mock_post.return_value = resp
            assert uploader.authenticate() is False

    def test_auth_network_error(self, upload_config):
        import requests
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        with patch.object(uploader.session, "post", side_effect=requests.RequestException("fail")):
            assert uploader.authenticate() is False

    def test_test_mode_skip_auth(self, upload_config):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config, test_mode=True)
        assert uploader.authenticate() is True


class TestVideoUploaderUpload:

    def test_upload_success(self, upload_config, tmp_path):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        uploader._authenticated = True

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video_data")

        with patch.object(uploader.session, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"video": {"id": "v123", "filename": "test.mp4"}}
            mock_post.return_value = resp
            result, error = uploader.upload_video(str(video), "aurora")

        assert result is not None
        assert result["id"] == "v123"
        assert error == ""

    def test_upload_401_reauth_retry(self, upload_config, tmp_path):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        uploader._authenticated = True

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video_data")

        call_count = 0

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 1:
                resp.status_code = 401
                resp.text = "Unauthorized"
            elif "gate" in str(args):
                resp.status_code = 200  # Re-auth
            else:
                resp.status_code = 200
                resp.json.return_value = {"video": {"id": "v456"}}
            return resp

        with patch.object(uploader.session, "post", side_effect=fake_post):
            with patch("render_watcher.time.sleep"):
                result, error = uploader.upload_video(str(video), "aurora")

        assert result is not None

    def test_upload_timeout_retry(self, upload_config, tmp_path):
        import requests
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        uploader._authenticated = True

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video_data")

        call_count = 0

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.Timeout("timed out")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"video": {"id": "v789"}}
            return resp

        with patch.object(uploader.session, "post", side_effect=fake_post):
            with patch("render_watcher.time.sleep"):
                result, error = uploader.upload_video(str(video), "aurora")

        assert result is not None

    def test_upload_file_error_no_retry(self, upload_config, tmp_path):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config)
        uploader._authenticated = True

        # Non-existent file
        result, error = uploader.upload_video(str(tmp_path / "missing.mp4"), "aurora")
        assert result is None
        assert "File error" in error or "No such file" in error

    def test_upload_all_retries_exhausted(self, upload_config, tmp_path):
        import requests
        from render_watcher import VideoUploader
        upload_config.max_upload_retries = 2
        uploader = VideoUploader(upload_config)
        uploader._authenticated = True

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video_data")

        with patch.object(uploader.session, "post", side_effect=requests.ConnectionError("fail")):
            with patch("render_watcher.time.sleep"):
                result, error = uploader.upload_video(str(video), "aurora")

        assert result is None
        assert "Connection error" in error

    def test_test_mode_fake_upload(self, upload_config, tmp_path):
        from render_watcher import VideoUploader
        uploader = VideoUploader(upload_config, test_mode=True)

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video_data")

        result, error = uploader.upload_video(str(video), "aurora")
        assert result is not None
        assert result["id"].startswith("test_")


# ---------------------------------------------------------------------------
# FolderWatcher — extension filtering and scan
# ---------------------------------------------------------------------------

class TestFolderWatcher:

    def _make_watcher(self, upload_config, upload_state, watch_path):
        from render_watcher import FolderWatcher, SmartScheduler, VideoUploader
        uploader = VideoUploader(upload_config, test_mode=True)
        scheduler = SmartScheduler(upload_config, upload_state)
        notifications = MagicMock()
        watcher = FolderWatcher(
            watch_path=watch_path,
            account="aurora",
            template="aurora",
            uploader=uploader,
            state=upload_state,
            scheduler=scheduler,
            notifications=notifications,
            config=upload_config,
        )
        return watcher

    def test_ignores_non_video_extensions(self, upload_config, upload_state, tmp_path):
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        (watch_dir / "file.txt").write_bytes(b"not a video")
        (watch_dir / "file.jpg").write_bytes(b"not a video")

        watcher = self._make_watcher(upload_config, upload_state, watch_dir)
        unprocessed = watcher.scan_unprocessed()
        assert len(unprocessed) == 0

    def test_accepts_mp4_and_mov(self, upload_config, upload_state, tmp_path):
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        (watch_dir / "video1.mp4").write_bytes(b"mp4 data")
        (watch_dir / "video2.mov").write_bytes(b"mov data")

        watcher = self._make_watcher(upload_config, upload_state, watch_dir)
        unprocessed = watcher.scan_unprocessed()
        assert len(unprocessed) == 2

    def test_scan_sorted_by_mtime(self, upload_config, upload_state, tmp_path):
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        v1 = watch_dir / "first.mp4"
        v1.write_bytes(b"data1")
        time.sleep(0.05)
        v2 = watch_dir / "second.mp4"
        v2.write_bytes(b"data2")

        watcher = self._make_watcher(upload_config, upload_state, watch_dir)
        unprocessed = watcher.scan_unprocessed()
        assert len(unprocessed) == 2
        assert unprocessed[0].name == "first.mp4"
        assert unprocessed[1].name == "second.mp4"

    def test_empty_folder_returns_empty(self, upload_config, upload_state, tmp_path):
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        watcher = self._make_watcher(upload_config, upload_state, watch_dir)
        unprocessed = watcher.scan_unprocessed()
        assert len(unprocessed) == 0
