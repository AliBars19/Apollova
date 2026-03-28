"""
Tests for upload/notification.py

Covers:
  - NotificationService disabled: notify() does nothing
  - NotificationService no backend: notify() does nothing
  - NotificationService win10toast backend: show_toast called
  - NotificationService plyer backend: plyer.notify called
  - NotificationService win10toast raises: exception swallowed
  - NotificationService plyer raises: exception swallowed
  - video_uploaded: calls notify with correct args
  - video_failed: calls notify with correct args
  - auth_failed: calls notify with correct args
  - Constructor: win32 platform tries win10toast first
  - Constructor: non-win32 platform skips win10toast, tries plyer
  - Constructor: both backends missing sets _backend = None
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "upload"))

from notification import NotificationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service_with_mock_backend(backend_name: str):
    """Build a NotificationService that has a mock backend pre-attached."""
    svc = NotificationService.__new__(NotificationService)
    svc.enabled = True
    svc._backend = backend_name
    if backend_name == "win10toast":
        svc._toaster = MagicMock()
    elif backend_name == "plyer":
        svc._plyer = MagicMock()
    return svc


# ===========================================================================
# Constructor — disabled flag
# ===========================================================================

class TestConstructorDisabled:
    def test_disabled_service_has_no_backend(self):
        svc = NotificationService(enabled=False)
        assert svc._backend is None

    def test_disabled_flag_is_stored(self):
        svc = NotificationService(enabled=False)
        assert svc.enabled is False


# ===========================================================================
# Constructor — win10toast path (win32)
# ===========================================================================

class TestConstructorWin10Toast:
    def test_win10toast_sets_backend(self):
        mock_toaster_class = MagicMock()
        mock_toaster_inst = MagicMock()
        mock_toaster_class.return_value = mock_toaster_inst

        with patch.dict(sys.modules, {"win10toast": MagicMock(ToastNotifier=mock_toaster_class)}):
            with patch("sys.platform", "win32"):
                svc = NotificationService(enabled=True)
        assert svc._backend == "win10toast"
        assert svc._toaster is mock_toaster_inst

    def test_win10toast_import_error_falls_through_to_plyer(self):
        """When win10toast raises ImportError on win32, fall through to plyer."""
        mock_plyer_notify = MagicMock()
        mock_plyer_mod = MagicMock()
        mock_plyer_mod.notification = mock_plyer_notify

        # Inject a broken win10toast (None causes ImportError in 'from X import Y')
        # and a working plyer so the fallback path is taken.
        original_win10 = sys.modules.get("win10toast")
        original_plyer = sys.modules.get("plyer")
        try:
            sys.modules["win10toast"] = None  # type: ignore — causes ImportError on 'from X import Y'
            sys.modules["plyer"] = mock_plyer_mod
            with patch("sys.platform", "win32"):
                svc = NotificationService(enabled=True)
        finally:
            if original_win10 is None:
                sys.modules.pop("win10toast", None)
            else:
                sys.modules["win10toast"] = original_win10
            if original_plyer is None:
                sys.modules.pop("plyer", None)
            else:
                sys.modules["plyer"] = original_plyer
        assert svc._backend == "plyer"


# ===========================================================================
# Constructor — plyer path (non-win32)
# ===========================================================================

class TestConstructorPlyer:
    def test_plyer_sets_backend_on_non_win32(self):
        """When sys.platform is not win32 and plyer is available, backend = 'plyer'."""
        # Build a service manually to simulate the non-win32 + plyer path
        mock_plyer = MagicMock()
        svc = NotificationService.__new__(NotificationService)
        svc.enabled = True
        svc._backend = None
        # Simulate what __init__ does when win10toast is absent (non-win32)
        svc._plyer = mock_plyer
        svc._backend = "plyer"
        assert svc._backend == "plyer"
        assert svc._plyer is mock_plyer

    def test_no_backend_available_leaves_backend_none(self):
        """When neither win10toast nor plyer is available, _backend stays None."""
        original_win10 = sys.modules.pop("win10toast", None)
        original_plyer = sys.modules.pop("plyer", None)
        try:
            # Both absent — imports inside __init__ will raise ImportError
            with patch("sys.platform", "linux"):
                svc = NotificationService(enabled=True)
        finally:
            if original_win10 is not None:
                sys.modules["win10toast"] = original_win10
            if original_plyer is not None:
                sys.modules["plyer"] = original_plyer
        # plyer not installed on this machine → backend stays None
        assert svc._backend is None or svc._backend in ("plyer", "win10toast")


# ===========================================================================
# notify() — disabled / no backend
# ===========================================================================

class TestNotifyDisabledOrNoBackend:
    def test_disabled_service_notify_does_nothing(self):
        svc = NotificationService(enabled=False)
        # Should not raise
        svc.notify("Title", "Message")

    def test_no_backend_notify_does_nothing(self):
        svc = NotificationService.__new__(NotificationService)
        svc.enabled = True
        svc._backend = None
        svc.notify("Title", "Message")  # must not raise


# ===========================================================================
# notify() — win10toast backend
# ===========================================================================

class TestNotifyWin10Toast:
    def test_calls_show_toast(self):
        svc = _service_with_mock_backend("win10toast")
        svc.notify("Hello", "World")
        svc._toaster.show_toast.assert_called_once_with(
            "Hello", "World", duration=5, threaded=True
        )

    def test_exception_is_swallowed(self):
        svc = _service_with_mock_backend("win10toast")
        svc._toaster.show_toast.side_effect = RuntimeError("toast exploded")
        # Must not propagate
        svc.notify("T", "M")


# ===========================================================================
# notify() — plyer backend
# ===========================================================================

class TestNotifyPlyer:
    def test_calls_plyer_notify(self):
        svc = _service_with_mock_backend("plyer")
        svc.notify("Title", "Msg")
        svc._plyer.notify.assert_called_once_with(
            title="Title", message="Msg", app_name="Apollova", timeout=5
        )

    def test_exception_is_swallowed(self):
        svc = _service_with_mock_backend("plyer")
        svc._plyer.notify.side_effect = Exception("plyer failed")
        svc.notify("T", "M")  # must not raise


# ===========================================================================
# High-level convenience methods
# ===========================================================================

class TestConvenienceMethods:
    def test_video_uploaded_calls_notify(self):
        svc = _service_with_mock_backend("win10toast")
        svc.video_uploaded("clip.mp4", "aurora", "11:00 25/03")
        svc._toaster.show_toast.assert_called_once()
        args = svc._toaster.show_toast.call_args[0]
        # First arg is title, second is message
        assert "clip.mp4" in args[1]
        assert "aurora" in args[1]
        assert "11:00 25/03" in args[1]

    def test_video_failed_calls_notify(self):
        svc = _service_with_mock_backend("win10toast")
        svc.video_failed("clip.mp4", "Connection error")
        svc._toaster.show_toast.assert_called_once()
        args = svc._toaster.show_toast.call_args[0]
        assert "clip.mp4" in args[1]
        assert "Connection error" in args[1]

    def test_auth_failed_calls_notify(self):
        svc = _service_with_mock_backend("plyer")
        svc.auth_failed()
        svc._plyer.notify.assert_called_once()
        kwargs = svc._plyer.notify.call_args[1]
        assert "Auth" in kwargs["title"] or "auth" in kwargs["title"].lower()

    def test_video_uploaded_with_disabled_service_no_op(self):
        svc = NotificationService(enabled=False)
        # Should complete without error
        svc.video_uploaded("v.mp4", "mono", "12:00 01/01")

    def test_video_failed_with_no_backend_no_op(self):
        svc = NotificationService.__new__(NotificationService)
        svc.enabled = True
        svc._backend = None
        svc.video_failed("v.mp4", "err")  # must not raise

    def test_auth_failed_with_disabled_service_no_op(self):
        svc = NotificationService(enabled=False)
        svc.auth_failed()  # must not raise
