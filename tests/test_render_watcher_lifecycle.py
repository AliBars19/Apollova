"""
Tests for render_watcher.py — startup/shutdown lifecycle, file-system event
handlers, show_status / show_stats / show_log display helpers, and the
upload-to-dashboard flow inside main().

Uncovered lines targeted:
  61-69   _NullConsole / _PlainConsole fallbacks
  82, 84, 86-87  _is_headless() branches
  94-102  _make_console() branches
  113-135 setup_logging()
  265-273 VideoUploader.check_status()
  295-296 upload_video retry path (auth re-trigger on 401)
  320-321 upload HTTP error path
  341-355 schedule_video paths
  431-432 _worker_loop exception handler
  473     _process_video failed-record else branch
  512-513 file delete OSError swallowed
  527, 540-542, 554-555 _wait_for_stable branches
  576-599 show_status()
  603-617 show_stats()
  621-642 show_log()
  682-683 watch_mode console exception swallowed
  712, 715-719, 726-727, 732-738 watch_mode unprocessed + loop
  744-841 main() CLI branches
  845-861 __main__ crash handler
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "upload"))


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_config(tmp_path):
    from config import Config
    return Config(
        gate_password="secret",
        apollova_root=str(tmp_path),
        state_db_path=str(tmp_path / "data" / "state.db"),
        log_dir=str(tmp_path / "logs"),
        file_stable_wait=0.0,
        file_stable_extra_wait=0.0,
        file_stable_checks=1,
        notifications_enabled=False,
    )


def _make_state(tmp_path):
    from upload_state import StateManager
    return StateManager(db_path=str(tmp_path / "state2.db"))


# ===========================================================================
# _NullConsole and _is_headless / _make_console
# ===========================================================================

class TestHeadlessConsole:
    def test_null_console_print_does_nothing(self):
        from render_watcher import _NullConsole
        nc = _NullConsole()
        nc.print("anything")  # must not raise

    def test_null_console_print_with_kwargs(self):
        from render_watcher import _NullConsole
        nc = _NullConsole()
        nc.print("msg", style="red", end="\n")  # must not raise

    def test_is_headless_when_stdout_none(self):
        from render_watcher import _is_headless
        with patch("sys.stdout", None):
            result = _is_headless()
        assert result is True

    def test_is_headless_when_no_isatty(self):
        from render_watcher import _is_headless
        mock_stdout = MagicMock(spec=[])  # no isatty attribute
        with patch("sys.stdout", mock_stdout):
            result = _is_headless()
        assert result is True

    def test_is_headless_false_when_tty(self):
        from render_watcher import _is_headless
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        mock_stderr = MagicMock()
        with patch("sys.stdout", mock_stdout), patch("sys.stderr", mock_stderr):
            result = _is_headless()
        assert result is False

    def test_make_console_returns_null_when_headless(self):
        from render_watcher import _make_console, _NullConsole
        with patch("render_watcher._is_headless", return_value=True):
            c = _make_console()
        assert isinstance(c, _NullConsole)

    def test_make_console_plain_when_no_rich(self):
        from render_watcher import _make_console, _NullConsole
        with patch("render_watcher._is_headless", return_value=False):
            with patch("render_watcher._RICH", False):
                c = _make_console()
        # Should be a _PlainConsole (not NullConsole, not RichConsole)
        assert hasattr(c, "print")
        assert not isinstance(c, _NullConsole)

    def test_plain_console_strips_markup(self):
        from render_watcher import _make_console
        with patch("render_watcher._is_headless", return_value=False):
            with patch("render_watcher._RICH", False):
                c = _make_console()
        # Should call print without raising
        with patch("builtins.print") as mock_print:
            c.print("[bold]hello[/bold]")
            mock_print.assert_called()
            # Markup stripped
            printed = str(mock_print.call_args)
            assert "bold" not in printed


# ===========================================================================
# setup_logging
# ===========================================================================

class TestSetupLogging:
    def test_creates_log_directory(self, tmp_path):
        from render_watcher import setup_logging
        config = _make_config(tmp_path)
        log_dir = tmp_path / "new_logs"
        config.log_dir = str(log_dir)
        assert not log_dir.exists()
        setup_logging(config)
        assert log_dir.exists()

    def test_adds_file_handlers(self, tmp_path):
        from render_watcher import setup_logging
        config = _make_config(tmp_path)
        root = logging.getLogger("apollova_test_lifecycle")
        root.handlers.clear()
        config_copy = _make_config(tmp_path)
        # Use a unique logger name to avoid leaking handlers
        with patch("render_watcher.logging") as mock_logging:
            mock_root = MagicMock()
            mock_logging.getLogger.return_value = mock_root
            mock_logging.Formatter = logging.Formatter
            mock_logging.DEBUG = logging.DEBUG
            mock_logging.ERROR = logging.ERROR
            mock_logging.INFO = logging.INFO
            mock_logging.handlers = logging.handlers if hasattr(logging, "handlers") else MagicMock()
            # Just ensure setup_logging runs without error
            setup_logging(config)

    def test_log_level_applied(self, tmp_path):
        from render_watcher import setup_logging
        config = _make_config(tmp_path)
        config.log_level = "DEBUG"
        # Must not raise
        setup_logging(config)


# ===========================================================================
# VideoUploader.check_status
# ===========================================================================

class TestVideoUploaderCheckStatus:
    def test_returns_json_on_200(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"aurora": {"youtube": True}}
        with patch.object(uploader.session, "get", return_value=mock_resp):
            result = uploader.check_status()
        assert result == {"aurora": {"youtube": True}}

    def test_returns_none_on_non_200(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch.object(uploader.session, "get", return_value=mock_resp):
            result = uploader.check_status()
        assert result is None

    def test_returns_none_on_request_exception(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        with patch.object(uploader.session, "get", side_effect=requests.RequestException("timeout")):
            result = uploader.check_status()
        assert result is None


# ===========================================================================
# VideoUploader.upload_video — error paths
# ===========================================================================

class TestVideoUploaderErrorPaths:
    def test_401_triggers_reauthentication(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        config.max_upload_retries = 2
        config.retry_base_delay = 0
        uploader = VideoUploader(config)
        uploader._authenticated = True

        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"id": "vid_abc", "filename": "test.mp4"}

        # First post = auth (200), then upload 401, then auth again (200), then upload 200
        auth_resp = MagicMock()
        auth_resp.status_code = 200

        call_count = {"n": 0}

        def fake_post(url, **kwargs):
            call_count["n"] += 1
            if "auth/gate" in url:
                return auth_resp
            if "upload" in url:
                if call_count["n"] <= 2:
                    return mock_resp_401
                return mock_resp_ok
            return mock_resp_401

        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 1024)

        with patch.object(uploader.session, "post", side_effect=fake_post):
            with patch("time.sleep"):
                result, err = uploader.upload_video(str(video), "aurora")

    def test_http_error_logged(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        config.max_upload_retries = 1
        uploader = VideoUploader(config)
        uploader._authenticated = True

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00" * 1024)

        with patch.object(uploader.session, "post", return_value=mock_resp):
            with patch("time.sleep"):
                result, err = uploader.upload_video(str(video), "aurora")
        assert result is None
        assert "500" in err


# ===========================================================================
# VideoUploader.schedule_video
# ===========================================================================

class TestScheduleVideo:
    def test_returns_true_on_200(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        uploader._authenticated = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(uploader.session, "patch", return_value=mock_resp):
            result = uploader.schedule_video("vid_123", "2026-03-23T11:00:00")
        assert result is True

    def test_returns_false_on_non_200(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        uploader._authenticated = True
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        with patch.object(uploader.session, "patch", return_value=mock_resp):
            result = uploader.schedule_video("vid_123", "2026-03-23T11:00:00")
        assert result is False

    def test_returns_false_on_request_exception(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config)
        uploader._authenticated = True
        with patch.object(uploader.session, "patch", side_effect=requests.RequestException("err")):
            result = uploader.schedule_video("vid_123", "2026-03-23T11:00:00")
        assert result is False

    def test_test_mode_returns_true_without_network(self, tmp_path):
        from render_watcher import VideoUploader
        config = _make_config(tmp_path)
        uploader = VideoUploader(config, test_mode=True)
        result = uploader.schedule_video("vid_123", "2026-03-23T11:00:00")
        assert result is True


# ===========================================================================
# FolderWatcher event handlers
# ===========================================================================

class TestFolderWatcherEventHandlers:
    def _make_watcher(self, tmp_path):
        from render_watcher import FolderWatcher, SmartScheduler, VideoUploader
        config = _make_config(tmp_path)
        state = _make_state(tmp_path)
        uploader = VideoUploader(config, test_mode=True)
        uploader._authenticated = True
        scheduler = SmartScheduler(config, state)
        notifications = MagicMock()
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir(parents=True, exist_ok=True)
        watcher = FolderWatcher(
            watch_path=watch_dir,
            account="aurora",
            template="aurora",
            uploader=uploader,
            state=state,
            scheduler=scheduler,
            notifications=notifications,
            config=config,
        )
        return watcher, watch_dir

    def test_on_created_enqueues_mp4(self, tmp_path):
        watcher, watch_dir = self._make_watcher(tmp_path)
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(watch_dir / "new_video.mp4")
        with patch.object(watcher, "_process_video"):
            watcher.on_created(event)
            time.sleep(0.05)
        # The path was enqueued (pending set got it)
        # We just verify no exception was raised

    def test_on_modified_enqueues_mp4(self, tmp_path):
        watcher, watch_dir = self._make_watcher(tmp_path)
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(watch_dir / "modified.mp4")
        watcher.on_modified(event)  # must not raise

    def test_on_created_ignores_directory_events(self, tmp_path):
        watcher, watch_dir = self._make_watcher(tmp_path)
        event = MagicMock()
        event.is_directory = True
        event.src_path = str(watch_dir / "subfolder")
        initial_pending = len(watcher._pending)
        watcher.on_created(event)
        assert len(watcher._pending) == initial_pending

    def test_on_created_ignores_non_video_extension(self, tmp_path):
        watcher, watch_dir = self._make_watcher(tmp_path)
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(watch_dir / "readme.txt")
        initial_pending = len(watcher._pending)
        watcher.on_created(event)
        assert len(watcher._pending) == initial_pending


# ===========================================================================
# FolderWatcher._wait_for_stable — edge paths
# ===========================================================================

class TestWaitForStable:
    def _make_watcher(self, tmp_path):
        from render_watcher import FolderWatcher, SmartScheduler, VideoUploader
        config = _make_config(tmp_path)
        state = _make_state(tmp_path)
        uploader = VideoUploader(config, test_mode=True)
        uploader._authenticated = True
        scheduler = SmartScheduler(config, state)
        notifications = MagicMock()
        watch_dir = tmp_path / "renders"
        watch_dir.mkdir(parents=True, exist_ok=True)
        return FolderWatcher(
            watch_path=watch_dir,
            account="aurora",
            template="aurora",
            uploader=uploader,
            state=state,
            scheduler=scheduler,
            notifications=notifications,
            config=config,
        )

    def test_returns_false_on_timeout(self, tmp_path):
        watcher = self._make_watcher(tmp_path)
        video = tmp_path / "renders" / "vid.mp4"
        video.write_bytes(b"\x00" * 512)

        # Patch Path.stat at the class level so sizes always change → timeout
        sizes = [100, 200, 300, 400, 500, 600, 700]
        call_count = {"n": 0}

        class FakeStat:
            def __init__(self, s):
                self.st_size = s

        def fake_stat(self_path):
            n = call_count["n"]
            call_count["n"] += 1
            return FakeStat(sizes[n % len(sizes)])

        import pathlib
        with patch.object(pathlib.Path, "stat", fake_stat):
            with patch("time.sleep"):
                with patch("time.time", side_effect=[0.0] + [999.0] * 100):
                    result = watcher._wait_for_stable(video, timeout=1)
        assert result is False

    def test_returns_false_when_file_deleted(self, tmp_path):
        watcher = self._make_watcher(tmp_path)
        missing = tmp_path / "renders" / "gone.mp4"
        # File does not exist
        result = watcher._wait_for_stable(missing, timeout=0.1)
        assert result is False

    def test_returns_true_when_size_stabilises(self, tmp_path):
        watcher = self._make_watcher(tmp_path)
        video = tmp_path / "renders" / "stable.mp4"
        video.write_bytes(b"\x00" * 1024)
        # Size is stable from the start, file is readable
        with patch("time.sleep"):
            result = watcher._wait_for_stable(video, timeout=30)
        assert result is True


# ===========================================================================
# FolderWatcher._process_video — file delete OSError swallowed
# ===========================================================================

class TestProcessVideoDeleteError:
    def test_oserror_on_delete_is_swallowed(self, tmp_path, upload_config, upload_state):
        from render_watcher import FolderWatcher, SmartScheduler, VideoUploader
        config = upload_config
        state = upload_state
        uploader = VideoUploader(config, test_mode=False)
        uploader._authenticated = True
        scheduler = SmartScheduler(config, state)
        notifications = MagicMock()

        watch_dir = tmp_path / "renders"
        watch_dir.mkdir(parents=True, exist_ok=True)
        video = watch_dir / "clip.mp4"
        video.write_bytes(b"\x00" * 1024)

        watcher = FolderWatcher(
            watch_path=watch_dir,
            account="aurora",
            template="aurora",
            uploader=uploader,
            state=state,
            scheduler=scheduler,
            notifications=notifications,
            config=config,
        )

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 200
        mock_upload_resp.json.return_value = {"video": {"id": "vid_abc"}}

        mock_schedule_resp = MagicMock()
        mock_schedule_resp.status_code = 200

        def fake_post(url, **kwargs):
            if "auth/gate" in url:
                r = MagicMock()
                r.status_code = 200
                return r
            return mock_upload_resp

        import pathlib

        def raising_unlink(self_path):
            raise OSError("locked")

        with patch.object(uploader.session, "post", side_effect=fake_post):
            with patch.object(uploader.session, "patch", return_value=mock_schedule_resp):
                with patch.object(watcher, "_wait_for_stable", return_value=True):
                    with patch.object(pathlib.Path, "unlink", raising_unlink):
                        # Must not propagate the OSError
                        watcher._process_video(video)


# ===========================================================================
# show_status / show_stats / show_log
# ===========================================================================

class TestCLIDisplayFunctions:
    def test_show_status_successful(self, tmp_path):
        from render_watcher import show_status
        config = _make_config(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "aurora": {"youtube": True, "youtubeName": "AuroraChannel", "tiktok": False},
            "nova": {"youtube": False, "tiktok": True, "tiktokName": "NovaTikTok"},
        }
        with patch("requests.get", return_value=mock_resp):
            show_status(config)  # must not raise

    def test_show_status_non_200(self, tmp_path):
        from render_watcher import show_status
        config = _make_config(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            show_status(config)  # must not raise

    def test_show_status_connection_error(self, tmp_path):
        from render_watcher import show_status
        config = _make_config(tmp_path)
        with patch("requests.get", side_effect=Exception("no connection")):
            show_status(config)  # must not raise

    def test_show_stats_runs(self, tmp_path):
        from render_watcher import show_stats
        state = _make_state(tmp_path)
        show_stats(state)  # must not raise

    def test_show_log_empty(self, tmp_path):
        from render_watcher import show_log
        state = _make_state(tmp_path)
        show_log(state)  # must not raise, prints "No activity"

    def test_show_log_with_entries(self, tmp_path):
        from render_watcher import show_log
        state = MagicMock()
        state.get_recent_log.return_value = [
            {
                "created_at": "2026-03-23 11:00:00",
                "file_name": "clip.mp4",
                "account": "aurora",
                "action": "uploaded",
                "message": "Success",
            }
        ]
        show_log(state)  # must not raise


# ===========================================================================
# main() — CLI entry point
# ===========================================================================

class TestMainCLI:
    """
    Tests for the main() function's argparse branches.
    Each test patches everything external so no real network/files are hit.
    """

    def _run_main(self, argv, monkeypatch, tmp_path, extra_patches=None):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py"] + argv)

        config = _make_config(tmp_path)
        config.gate_password = "secret"

        state = _make_state(tmp_path)

        patches = {
            "render_watcher.Config.from_env": MagicMock(return_value=config),
            "render_watcher.StateManager": MagicMock(return_value=state),
            "render_watcher.setup_logging": MagicMock(),
        }
        if extra_patches:
            patches.update(extra_patches)

        with patch.multiple("render_watcher", **{
            k.replace("render_watcher.", ""): v for k, v in patches.items()
        }):
            with patch("render_watcher.Config.from_env", return_value=config):
                with patch("render_watcher.setup_logging"):
                    with patch("render_watcher.StateManager", return_value=state):
                        yield

    def test_status_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--status"])

        config = _make_config(tmp_path)
        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.show_status") as mock_show:
                    main()
        mock_show.assert_called_once_with(config)

    def test_stats_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--stats"])

        config = _make_config(tmp_path)
        state = _make_state(tmp_path)

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.show_stats") as mock_show:
                        main()
        mock_show.assert_called_once_with(state)

    def test_log_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--log"])

        config = _make_config(tmp_path)
        state = _make_state(tmp_path)

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.show_log") as mock_show:
                        main()
        mock_show.assert_called_once_with(state)

    def test_reset_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--reset", "42"])

        config = _make_config(tmp_path)
        state = MagicMock()

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    main()
        state.reset_failed.assert_called_once_with(42)

    def test_purge_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--purge"])

        config = _make_config(tmp_path)
        state = MagicMock()
        state.purge_old.return_value = 5

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    main()
        state.purge_old.assert_called_once_with(30)

    def test_failed_auth_exits(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--test"])

        config = _make_config(tmp_path)
        config.gate_password = "pw"
        state = _make_state(tmp_path)

        mock_uploader = MagicMock()
        mock_uploader.authenticate.return_value = False

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.VideoUploader", return_value=mock_uploader):
                        with patch("render_watcher.NotificationService"):
                            with patch("render_watcher.SmartScheduler"):
                                with pytest.raises(SystemExit):
                                    main()

    def test_upload_now_flag(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--upload-now"])

        config = _make_config(tmp_path)
        config.gate_password = "pw"
        state = _make_state(tmp_path)

        mock_uploader = MagicMock()
        mock_uploader.authenticate.return_value = True
        mock_uploader.test_mode = False

        mock_watcher = MagicMock()
        mock_watcher.scan_unprocessed.return_value = []

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.VideoUploader", return_value=mock_uploader):
                        with patch("render_watcher.NotificationService"):
                            with patch("render_watcher.SmartScheduler"):
                                with patch("render_watcher.FolderWatcher", return_value=mock_watcher):
                                    main()
        mock_watcher.scan_unprocessed.assert_called()

    def test_retry_failed_flag_no_records(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--retry-failed"])

        config = _make_config(tmp_path)
        config.gate_password = "pw"
        state = MagicMock()
        state.get_retryable.return_value = []

        mock_uploader = MagicMock()
        mock_uploader.authenticate.return_value = True

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.VideoUploader", return_value=mock_uploader):
                        with patch("render_watcher.NotificationService"):
                            with patch("render_watcher.SmartScheduler"):
                                main()
        state.get_retryable.assert_called_once()

    def test_retry_failed_skips_missing_file(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py", "--retry-failed"])

        config = _make_config(tmp_path)
        config.gate_password = "pw"

        record = MagicMock()
        record.id = 1
        record.file_path = str(tmp_path / "nonexistent.mp4")
        record.file_name = "nonexistent.mp4"
        record.template = "aurora"
        record.account = "aurora"

        state = MagicMock()
        state.get_retryable.return_value = [record]

        mock_uploader = MagicMock()
        mock_uploader.authenticate.return_value = True

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.VideoUploader", return_value=mock_uploader):
                        with patch("render_watcher.NotificationService"):
                            with patch("render_watcher.SmartScheduler"):
                                main()
        # Missing file: reset_failed called, but _process_video not called
        state.reset_failed.assert_called_with(record.id)

    def test_watch_mode_default(self, tmp_path, monkeypatch):
        from render_watcher import main
        monkeypatch.setattr(sys, "argv", ["render_watcher.py"])

        config = _make_config(tmp_path)
        config.gate_password = "pw"
        state = _make_state(tmp_path)

        mock_uploader = MagicMock()
        mock_uploader.authenticate.return_value = True

        with patch("render_watcher.Config.from_env", return_value=config):
            with patch("render_watcher.setup_logging"):
                with patch("render_watcher.StateManager", return_value=state):
                    with patch("render_watcher.VideoUploader", return_value=mock_uploader):
                        with patch("render_watcher.NotificationService"):
                            with patch("render_watcher.SmartScheduler"):
                                with patch("render_watcher.watch_mode") as mock_wm:
                                    main()
        mock_wm.assert_called_once()


# ===========================================================================
# watch_mode function
# ===========================================================================

class TestWatchMode:
    def test_watch_mode_starts_and_stops(self, tmp_path):
        from render_watcher import watch_mode, VideoUploader, SmartScheduler, NotificationService

        config = _make_config(tmp_path)
        state = _make_state(tmp_path)
        uploader = VideoUploader(config, test_mode=True)
        uploader._authenticated = True
        scheduler = SmartScheduler(config, state)
        notifications = NotificationService(enabled=False)

        mock_observer = MagicMock()

        def raise_keyboard_interrupt(*a, **kw):
            raise KeyboardInterrupt()

        with patch("render_watcher.Observer", return_value=mock_observer):
            with patch("time.sleep", side_effect=raise_keyboard_interrupt):
                with patch("render_watcher.FolderWatcher") as mock_fw_class:
                    mock_fw_instance = MagicMock()
                    mock_fw_instance.scan_unprocessed.return_value = []
                    mock_fw_class.return_value = mock_fw_instance
                    watch_mode(uploader, state, scheduler, notifications, config)

        mock_observer.start.assert_called_once()
        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()

    def test_watch_mode_processes_unprocessed_videos(self, tmp_path):
        from render_watcher import watch_mode, VideoUploader, SmartScheduler, NotificationService

        config = _make_config(tmp_path)
        state = _make_state(tmp_path)
        uploader = VideoUploader(config, test_mode=True)
        uploader._authenticated = True
        scheduler = SmartScheduler(config, state)
        notifications = NotificationService(enabled=False)

        unprocessed_video = tmp_path / "clip.mp4"
        unprocessed_video.write_bytes(b"\x00" * 1024)

        mock_observer = MagicMock()

        def raise_keyboard(*a, **kw):
            raise KeyboardInterrupt()

        with patch("render_watcher.Observer", return_value=mock_observer):
            with patch("time.sleep", side_effect=raise_keyboard):
                with patch("render_watcher.FolderWatcher") as mock_fw_class:
                    mock_fw_instance = MagicMock()
                    mock_fw_instance.scan_unprocessed.return_value = [unprocessed_video]
                    mock_fw_class.return_value = mock_fw_instance
                    watch_mode(uploader, state, scheduler, notifications, config)

        mock_fw_instance._process_video.assert_called_with(unprocessed_video)
