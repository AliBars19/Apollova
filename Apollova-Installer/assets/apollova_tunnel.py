"""
Apollova Tunnel Manager — manages cloudflared subprocess for remote access.

Downloads cloudflared on first use (via Setup.exe), starts it pointing at
localhost:7823, captures the tunnel URL, and keeps it alive with auto-restart.
"""

import os
import re
import sys
import time
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional


class TunnelManager:
    """Manage a cloudflared subprocess that tunnels localhost:port to the internet."""

    CLOUDFLARED_URL = (
        "https://github.com/cloudflare/cloudflared/releases/latest/"
        "download/cloudflared-windows-amd64.exe"
    )

    def __init__(self, port: int = 7823, assets_dir: Path = None):
        if assets_dir is None:
            if getattr(sys, "frozen", False):
                assets_dir = Path(sys.executable).parent / "assets"
            else:
                assets_dir = Path(__file__).parent
        self._exe = assets_dir / "cloudflared.exe"
        self._port = port
        self._proc: Optional[subprocess.Popen] = None
        self._url: Optional[str] = None
        self._on_url_change: Optional[Callable] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- Public interface ----------------------------------------------------

    def is_available(self) -> bool:
        """True if cloudflared.exe exists on disk."""
        return self._exe.exists()

    def start(self) -> Optional[str]:
        """Start cloudflared, return tunnel URL. Blocks until URL captured or timeout."""
        if not self.is_available():
            return None

        if self._proc and self._proc.poll() is None:
            return self._url  # Already running

        self._stop_event.clear()
        self._url = None

        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._proc = subprocess.Popen(
                [
                    str(self._exe),
                    "tunnel",
                    "--url", f"http://localhost:{self._port}",
                    "--no-autoupdate",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        except Exception as e:
            print(f"Failed to start cloudflared: {e}")
            return None

        # Capture URL from stdout in a reader thread
        url_captured = threading.Event()

        def _read_stdout():
            for raw_line in self._proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                match = re.search(
                    r"https://[a-z0-9\-]+\.trycloudflare\.com", line
                )
                if match:
                    self._url = match.group(0)
                    url_captured.set()
                    if self._on_url_change:
                        self._on_url_change(self._url)
                if self._stop_event.is_set():
                    break

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()

        # Wait up to 30s for URL
        url_captured.wait(timeout=30)

        # Start watchdog
        self._watchdog_thread = threading.Thread(
            target=self._watchdog, daemon=True
        )
        self._watchdog_thread.start()

        return self._url

    def stop(self):
        """Kill cloudflared subprocess."""
        self._stop_event.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._url = None

    def get_url(self) -> Optional[str]:
        """Return current tunnel URL, or None if not running."""
        return self._url

    def is_running(self) -> bool:
        """True if cloudflared process is alive."""
        return self._proc is not None and self._proc.poll() is None

    def restart(self) -> Optional[str]:
        """stop() then start()."""
        self.stop()
        time.sleep(1)
        return self.start()

    def set_on_url_change(self, callback: Callable):
        """Callback called when tunnel URL changes (e.g. after restart)."""
        self._on_url_change = callback

    # -- Internal ------------------------------------------------------------

    def _watchdog(self):
        """Check process health every 10s, auto-restart on crash."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=10)
            if self._stop_event.is_set():
                break
            if self._proc and self._proc.poll() is not None:
                # Process died — restart
                print("cloudflared died — restarting...")
                self._proc = None
                self.start()
