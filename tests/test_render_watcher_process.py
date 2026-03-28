"""
Tests for FolderWatcher._process_video() state machine and crash recovery.

Covers:
  - Claim -> upload -> schedule happy path
  - Upload failure (mark_upload_failed called, no schedule attempted)
  - Schedule failure after successful upload (mark_schedule_failed called)
  - Already-processed file is skipped (is_processed guard)
  - Claim contested by another worker (try_claim returns False)
  - Failed record reset-and-retry path
  - Crash recovery: stuck UPLOADING records are reset in watch_mode
  - File deleted between stability check and upload
  - File read error during hash computation
  - Test-mode skips real file deletion
  - Local file deleted after successful upload (non-test mode)
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "upload"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watcher(upload_config, upload_state, watch_dir, *, test_mode=False):
    """Build a FolderWatcher with all heavyweight deps mocked."""
    from render_watcher import FolderWatcher, SmartScheduler, VideoUploader

    uploader = VideoUploader(upload_config, test_mode=test_mode)
    # Always treat as authenticated so upload logic is reached
    uploader._authenticated = True

    scheduler = SmartScheduler(upload_config, upload_state)
    notifications = MagicMock()

    watcher = FolderWatcher(
        watch_path=watch_dir,
        account="aurora",
        template="aurora",
        uploader=uploader,
        state=upload_state,
        scheduler=scheduler,
        notifications=notifications,
        config=upload_config,
    )
    return watcher


def _fake_video(directory: Path, name: str = "clip.mp4") -> Path:
    p = directory / name
    p.write_bytes(b"\x00" * 1024)
    return p


# ---------------------------------------------------------------------------
# Happy path: claim -> upload -> schedule
# ---------------------------------------------------------------------------

class TestProcessVideoHappyPath:

    def test_claim_upload_schedule_sequence(self, upload_config, upload_state, tmp_path):
        """Full happy path: file enters DB as PENDING, gets claimed, uploaded, scheduled."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        # Patch stability wait so test runs instantly
        with patch.object(watcher, "_wait_for_stable", return_value=True):
            watcher._process_video(video)

        record = upload_state.get_by_path(str(video))
        assert record is not None
        # In test_mode the file is not deleted, but state should be UPLOADED
        from upload_state import UploadStatus, ScheduleStatus
        assert record.upload_status == UploadStatus.UPLOADED
        assert record.schedule_status == ScheduleStatus.SCHEDULED

    def test_video_id_stored_after_upload(self, upload_config, upload_state, tmp_path):
        """video_id returned by API must be persisted in the state record."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        with patch.object(watcher, "_wait_for_stable", return_value=True):
            watcher._process_video(video)

        record = upload_state.get_by_path(str(video))
        assert record is not None
        assert record.video_id.startswith("test_")

    def test_notification_sent_on_success(self, upload_config, upload_state, tmp_path):
        """video_uploaded notification is sent after successful upload + schedule."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        with patch.object(watcher, "_wait_for_stable", return_value=True):
            watcher._process_video(video)

        watcher.notifications.video_uploaded.assert_called_once()

    def test_local_file_deleted_in_non_test_mode(self, upload_config, upload_state, tmp_path):
        """Non-test mode: local video file is unlinked after upload + schedule."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        fake_video_data = {"id": "real_v001", "filename": video.name}

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=(fake_video_data, "")), \
             patch.object(watcher.uploader, "schedule_video", return_value=True):
            watcher._process_video(video)

        assert not video.exists(), "File should have been deleted after successful upload"

    def test_test_mode_does_not_delete_file(self, upload_config, upload_state, tmp_path):
        """Test mode: local video file must NOT be deleted."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        with patch.object(watcher, "_wait_for_stable", return_value=True):
            watcher._process_video(video)

        assert video.exists(), "File must survive in test_mode"


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

class TestProcessVideoSkipConditions:

    def test_already_processed_file_is_skipped(self, upload_config, upload_state, tmp_path):
        """is_processed guard: file already in UPLOADED state is never re-uploaded."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        # Pre-register as already uploaded
        rid = upload_state.add_upload(
            file_path=str(video), template="aurora", account="aurora",
            file_hash="abc", file_size=1024,
        )
        upload_state.try_claim(rid)
        upload_state.mark_uploaded(rid, "existing_video_id")

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        upload_spy = MagicMock(return_value=({"id": "new_id"}, ""))
        with patch.object(watcher.uploader, "upload_video", upload_spy):
            watcher._process_video(video)

        upload_spy.assert_not_called()

    def test_unstable_file_is_skipped(self, upload_config, upload_state, tmp_path):
        """_wait_for_stable returning False must abort processing."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        upload_spy = MagicMock(return_value=({"id": "v1"}, ""))
        with patch.object(watcher, "_wait_for_stable", return_value=False), \
             patch.object(watcher.uploader, "upload_video", upload_spy):
            watcher._process_video(video)

        upload_spy.assert_not_called()

    def test_file_deleted_between_stability_and_upload(self, upload_config, upload_state, tmp_path):
        """File disappearing after stability check must abort silently."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        def delete_then_return_true(path, timeout=180):
            path.unlink()
            return True

        upload_spy = MagicMock(return_value=({"id": "v1"}, ""))
        with patch.object(watcher, "_wait_for_stable", side_effect=delete_then_return_true), \
             patch.object(watcher.uploader, "upload_video", upload_spy):
            watcher._process_video(video)

        upload_spy.assert_not_called()

    def test_file_hash_oserror_aborts_processing(self, upload_config, upload_state, tmp_path):
        """OSError when reading file hash should abort without crashing."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch("render_watcher.compute_file_hash", side_effect=OSError("permission denied")):
            # Must not raise
            watcher._process_video(video)

        # Record should not have been created
        assert upload_state.get_by_path(str(video)) is None


# ---------------------------------------------------------------------------
# Upload failure and retry logic
# ---------------------------------------------------------------------------

class TestProcessVideoUploadFailure:

    def test_upload_failure_marks_failed_state(self, upload_config, upload_state, tmp_path):
        """Upload returning (None, error) must persist FAILED status."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=(None, "Network timeout")):
            watcher._process_video(video)

        from upload_state import UploadStatus
        record = upload_state.get_by_path(str(video))
        assert record is not None
        assert record.upload_status == UploadStatus.FAILED
        assert "Network timeout" in record.upload_error

    def test_upload_failure_sends_failure_notification(self, upload_config, upload_state, tmp_path):
        """video_failed notification must be sent when upload fails."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=(None, "503 Service Unavailable")):
            watcher._process_video(video)

        watcher.notifications.video_failed.assert_called_once()
        _, call_kwargs = watcher.notifications.video_failed.call_args
        # First positional arg is the filename
        args = watcher.notifications.video_failed.call_args[0]
        assert video.name in args

    def test_upload_result_missing_id_treated_as_failure(self, upload_config, upload_state, tmp_path):
        """API response without 'id' key must be treated as upload failure."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        # Return a dict that has no 'id' key
        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=({"filename": "clip.mp4"}, "")):
            watcher._process_video(video)

        from upload_state import UploadStatus
        record = upload_state.get_by_path(str(video))
        assert record.upload_status == UploadStatus.FAILED

    def test_schedule_failure_marks_schedule_failed(self, upload_config, upload_state, tmp_path):
        """schedule_video returning False must persist SCHEDULE_FAILED status."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=({"id": "v99"}, "")), \
             patch.object(watcher.uploader, "schedule_video", return_value=False):
            watcher._process_video(video)

        from upload_state import UploadStatus, ScheduleStatus
        record = upload_state.get_by_path(str(video))
        assert record.upload_status == UploadStatus.UPLOADED
        assert record.schedule_status == ScheduleStatus.FAILED

    def test_schedule_failure_does_not_delete_local_file(self, upload_config, upload_state, tmp_path):
        """File must survive if scheduling fails (so it can be retried)."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=False)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", return_value=({"id": "v99"}, "")), \
             patch.object(watcher.uploader, "schedule_video", return_value=False):
            watcher._process_video(video)

        # File should still exist since scheduling failed
        assert video.exists()


# ---------------------------------------------------------------------------
# Claim contention
# ---------------------------------------------------------------------------

class TestProcessVideoClaimContention:

    def test_contested_claim_prevents_double_upload(self, upload_config, upload_state, tmp_path):
        """Second concurrent call for the same file must not upload again."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        upload_count = []

        original_upload = watcher.uploader.upload_video

        def counting_upload(*args, **kwargs):
            upload_count.append(1)
            return original_upload(*args, **kwargs)

        with patch.object(watcher, "_wait_for_stable", return_value=True), \
             patch.object(watcher.uploader, "upload_video", side_effect=counting_upload):
            # Simulate two concurrent threads hitting the same file
            t1 = threading.Thread(target=watcher._process_video, args=(video,))
            t2 = threading.Thread(target=watcher._process_video, args=(video,))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        # Exactly one upload should have occurred
        assert len(upload_count) == 1

    def test_failed_record_is_reset_and_reclaimed(self, upload_config, upload_state, tmp_path):
        """A FAILED record must be reset to PENDING and claimed again."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()
        video = _fake_video(watch_dir)

        # Pre-register as failed
        rid = upload_state.add_upload(
            file_path=str(video), template="aurora", account="aurora",
            file_hash="abc", file_size=1024,
        )
        upload_state.try_claim(rid)
        upload_state.mark_upload_failed(rid, "previous error")

        watcher = _make_watcher(upload_config, upload_state, watch_dir, test_mode=True)

        with patch.object(watcher, "_wait_for_stable", return_value=True):
            watcher._process_video(video)

        from upload_state import UploadStatus
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.UPLOADED


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

class TestCrashRecovery:

    def test_stuck_uploading_records_reset_in_watch_mode(self, upload_config, upload_state, tmp_path):
        """watch_mode() must reset any UPLOADING records left from a crash."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        # Simulate a crashed upload: record stuck in UPLOADING
        rid = upload_state.add_upload(
            file_path=str(watch_dir / "stuck.mp4"),
            template="aurora",
            account="aurora",
            file_hash="deadbeef",
            file_size=2048,
        )
        upload_state.try_claim(rid)  # Puts it in UPLOADING

        from upload_state import UploadStatus
        assert upload_state.get_record(rid).upload_status == UploadStatus.UPLOADING

        # watch_mode() calls state.get_uploading() and resets each one
        from render_watcher import watch_mode, VideoUploader, SmartScheduler
        uploader = VideoUploader(upload_config, test_mode=True)
        uploader._authenticated = True
        scheduler = SmartScheduler(upload_config, upload_state)
        notifications = MagicMock()

        # Override get_watch_paths to point at our empty temp dir so the observer
        # doesn't try to watch non-existent AE folders, then interrupt immediately.
        upload_config.apollova_root = str(tmp_path)
        upload_config.folder_account_map = {"renders": "aurora"}
        upload_config.renders_subfolder = ""

        # watch_mode() starts an Observer; interrupt it immediately
        import threading as _threading

        def run_watch():
            try:
                watch_mode(uploader, upload_state, scheduler, notifications, upload_config)
            except Exception:
                pass  # KeyboardInterrupt propagated differently in threads

        t = _threading.Thread(target=run_watch, daemon=True)
        t.start()
        time.sleep(0.3)  # Let crash recovery execute before the main loop
        t.join(timeout=2)

        # The stuck record should now be back to PENDING (reset)
        record = upload_state.get_record(rid)
        assert record.upload_status == UploadStatus.PENDING

    def test_get_uploading_returns_stuck_records(self, upload_state, tmp_path):
        """StateManager.get_uploading() must surface records stuck in UPLOADING."""
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir()

        rid = upload_state.add_upload(
            file_path=str(watch_dir / "stuck2.mp4"),
            template="mono", account="nova",
            file_hash="cafebabe", file_size=512,
        )
        upload_state.try_claim(rid)

        stuck = upload_state.get_uploading()
        assert any(r.id == rid for r in stuck)

    def test_reset_failed_restores_pending_status(self, upload_state, tmp_path):
        """reset_failed() must set upload_status back to PENDING."""
        from upload_state import UploadStatus

        rid = upload_state.add_upload(
            file_path=str(tmp_path / "crash.mp4"),
            template="onyx", account="nova",
            file_hash="feed", file_size=256,
        )
        upload_state.try_claim(rid)
        upload_state.mark_upload_failed(rid, "oops")

        upload_state.reset_failed(rid)

        assert upload_state.get_record(rid).upload_status == UploadStatus.PENDING
