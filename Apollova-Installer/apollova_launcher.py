"""
Apollova.exe entry point.
Shows a loading screen, runs full integrity checks, then launches the main app.
Zero terminal output. Every failure shows a friendly GUI dialog.
"""

import os
import sys
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QFrame, QMessageBox, QPushButton,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# Logger setup
_ASSETS = (Path(sys.executable).parent if getattr(sys, "frozen", False)
           else Path(__file__).parent.parent) / "assets"
if _ASSETS.exists():
    sys.path.insert(0, str(_ASSETS))
try:
    from apollova_logger import get_logger as _get_logger
    log = _get_logger("app")
except Exception:
    class _FallbackLog:
        def __getattr__(self, n): return lambda *a, **k: None
    log = _FallbackLog()

SUPPORT_EMAIL = "support@apollova.app"

STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QPushButton {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 7px 20px;
    color: #cdd6f4;
}
QPushButton:hover { background: #45475a; border-color: #89b4fa; }
QPushButton#primary {
    background: #89b4fa; color: #1e1e2e;
    font-weight: bold; padding: 8px 24px;
}
QPushButton#primary:hover { background: #b4befe; }
"""

# Required packages: (import_name, friendly_name, critical)
REQUIRED_PACKAGES = [
    ("PyQt6",          "PyQt6",            True),
    ("torch",          "PyTorch",          True),
    ("whisper",        "openai-whisper",   True),
    ("stable_whisper", "stable-ts",        True),
    ("pytubefix",      "pytubefix",        True),
    ("pydub",          "pydub",            True),
    ("librosa",        "librosa",          True),
    ("lyricsgenius",   "lyricsgenius",     True),
    ("rapidfuzz",      "rapidfuzz",        True),
    ("colorthief",     "colorthief",       True),
    ("PIL",            "Pillow",           True),
    ("requests",       "requests",         True),
    ("numpy",          "numpy",            True),
    ("dotenv",         "python-dotenv",    True),
]

REQUIRED_FILES = [
    "assets/apollova_gui.py",
    "assets/scripts/config.py",
    "assets/scripts/audio_processing.py",
    "assets/scripts/image_processing.py",
    "assets/scripts/lyric_processing.py",
    "assets/scripts/lyric_processing_mono.py",
    "assets/scripts/lyric_processing_onyx.py",
    "assets/scripts/lyric_alignment.py",
    "assets/scripts/song_database.py",
    "assets/scripts/genius_processing.py",
    "assets/scripts/smart_picker.py",
    "assets/requirements/requirements-base.txt",
]

REQUIRED_DIRS = [
    "Apollova-Aurora/jobs",
    "Apollova-Mono/jobs",
    "Apollova-Onyx/jobs",
    "database",
    "templates",
    "whisper_models",
]


# ─────────────────────────────────────────────────────────────────────────────
#  Signals
# ─────────────────────────────────────────────────────────────────────────────
class CheckSignals(QObject):
    item     = pyqtSignal(str, bool)    # label, passed
    progress = pyqtSignal(int)
    done     = pyqtSignal()
    fatal    = pyqtSignal(str, str, str)  # title, body, fix


# ─────────────────────────────────────────────────────────────────────────────
#  Loading Screen
# ─────────────────────────────────────────────────────────────────────────────
class LoadingScreen(QMainWindow):

    def __init__(self, root: Path, python: str, settings: dict):
        super().__init__()
        self.root     = root
        self.python   = python
        self.settings = settings

        self.setWindowTitle("Apollova")
        self.setFixedSize(460, 540)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 460) // 2,
                  (screen.height() - 540) // 2)

        icon = root / "assets" / "icon.ico"
        if not icon.exists():
            icon = root / "icon.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        log.session_start("Apollova")
        log.info(f"Install root: {root}")
        log.info(f"Python: {python}")
        self._abort = False
        self.sig = CheckSignals()
        self.sig.item.connect(self._add_item)
        self.sig.progress.connect(self._set_progress)
        self.sig.done.connect(self._on_checks_passed)
        self.sig.fatal.connect(self._on_fatal)

        # Smooth bar animation
        self._bar_val  = 0
        self._bar_tgt  = 0
        self._anim     = QTimer(self)
        self._anim.setInterval(30)
        self._anim.timeout.connect(self._animate)
        self._anim.start()

        self._build_ui()
        threading.Thread(target=self._run_checks, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(8)

        # Logo / title
        t = QLabel("Apollova")
        f = QFont("Segoe UI")
        f.setPointSize(22)
        f.setWeight(QFont.Weight.Bold)
        t.setFont(f)
        t.setStyleSheet("color:#89b4fa;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(t)

        sub = QLabel("Verifying installation...")
        sub.setStyleSheet("color:#6c7086; font-size:12px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#313244; margin: 4px 0;")
        layout.addWidget(sep)

        # Check items container
        self.checks_layout = QVBoxLayout()
        self.checks_layout.setSpacing(3)
        layout.addLayout(self.checks_layout)

        layout.addStretch()

        self.status_lbl = QLabel("Starting checks...")
        self.status_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)

    def _add_item(self, label: str, passed: bool):
        icon  = "✓" if passed else "⚠"
        color = "#a6e3a1" if passed else "#f9e2af"
        lbl   = QLabel(f"  {icon}  {label}")
        lbl.setStyleSheet(f"color:{color}; font-size:12px;")
        self.checks_layout.addWidget(lbl)
        self.status_lbl.setText(label)

    def _set_progress(self, pct: int):
        self._bar_tgt = pct * 10

    def _animate(self):
        if self._bar_val < self._bar_tgt:
            diff = self._bar_tgt - self._bar_val
            self._bar_val += max(1, int(diff * 0.08))
            self._bar_val = min(self._bar_tgt, self._bar_val)
            self.progress_bar.setValue(self._bar_val)

    def _on_checks_passed(self):
        log.info("All integrity checks passed — launching app")
        self._bar_tgt = 1000
        self.status_lbl.setText("Launching Apollova...")
        QTimer.singleShot(600, self._launch_app)

    def _on_fatal(self, title: str, body: str, fix: str):
        log.error(f"FATAL: {title}\n  {body}")
        log.session_end("Apollova", success=False)
        self._anim.stop()
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk { background:#f38ba8; border-radius:4px; }")

        dlg = QMessageBox(self)
        dlg.setWindowTitle(f"Apollova — {title}")
        dlg.setIcon(QMessageBox.Icon.Critical)
        dlg.setText(f"<b>{title}</b>")
        msg = body
        if fix:
            msg += f"\n\nHow to fix:\n{fix}"
        dlg.setInformativeText(msg)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────────────────
    #  Integrity checks (background thread)
    # ─────────────────────────────────────────────────────────────────────────
    def _checks_cache_valid(self):
        """Return True if checks passed < 24h ago (skip full re-check)."""
        try:
            cache = self.root / "assets" / "logs" / "last_check.json"
            if cache.exists():
                data = json.loads(cache.read_text())
                last = datetime.fromisoformat(data.get("timestamp", ""))
                age_h = (datetime.now() - last).total_seconds() / 3600
                if age_h < 24 and data.get("passed"):
                    return True
        except Exception:
            pass
        return False

    def _save_checks_cache(self, passed: bool):
        try:
            cache = self.root / "assets" / "logs" / "last_check.json"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "passed": passed,
            }))
        except Exception:
            pass

    def _run_checks(self):
        # Fast path: skip full checks if they passed recently
        if self._checks_cache_valid():
            log.info("Integrity checks passed <24h ago — skipping")
            self.sig.item.emit("Checks cached (passed recently)", True)
            self.sig.progress.emit(100)
            self.sig.done.emit()
            return

        checks = [
            ("Python version",      self._check_python),
            ("Required files",      self._check_files),
            ("Required folders",    self._check_dirs),
            ("Python packages",     self._check_packages),
            ("PyTorch",             self._check_torch),
            ("NumPy compatibility", self._check_numpy),
            ("FFmpeg",              self._check_ffmpeg),
            ("Write permissions",   self._check_writable),
        ]
        total = len(checks)
        warnings = []

        for i, (label, fn) in enumerate(checks):
            pct = int((i / total) * 90)
            self.sig.progress.emit(pct)
            try:
                ok, msg = fn()
                log.check(label, ok, msg or "")
                self.sig.item.emit(
                    f"{label}{'  —  ' + msg if msg else ''}",
                    ok)
                if not ok:
                    warnings.append((label, msg))
            except Exception as e:
                log.exception(f"Check '{label}' raised exception: {e}")
                self.sig.item.emit(f"{label}  —  error: {e}", False)
                warnings.append((label, str(e)))
            time.sleep(0.05)

        self.sig.progress.emit(100)
        if self._abort:
            self._save_checks_cache(False)
            return
        self._save_checks_cache(True)
        self.sig.done.emit()

    def _check_python(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            r = subprocess.run(
                [self.python, "-c",
                 "import sys; v=sys.version_info; "
                 "print(v.major, v.minor, v.micro)"],
                capture_output=True, text=True,
                timeout=5, creationflags=flags)
            if r.returncode == 0:
                parts = r.stdout.strip().split()
                if len(parts) >= 3:
                    major, minor, micro = int(parts[0]), int(parts[1]), int(parts[2])
                    ver = f"{major}.{minor}.{micro}"
                    if major == 3 and minor == 11:
                        return True, f"Python {ver}"
                    else:
                        return False, (
                            f"Python {ver} found but 3.11.x is required. "
                            "Re-run Setup.exe.")
        except Exception as e:
            pass
        return False, "Python 3.11 not found — re-run Setup.exe"

    def _check_files(self):
        missing = []
        for rel in REQUIRED_FILES:
            if not (self.root / rel).exists():
                missing.append(rel)
        if missing:
            self._abort = True
            self.sig.fatal.emit(
                "Missing Files",
                "Required files are missing:\n\n" +
                "\n".join(f"  • {m}" for m in missing),
                "Please reinstall Apollova by running Setup.exe."
            )
            return False, f"{len(missing)} file(s) missing"
        return True, f"{len(REQUIRED_FILES)} files OK"

    def _check_dirs(self):
        created = []
        for rel in REQUIRED_DIRS:
            d = self.root / rel
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(rel)
        if created:
            return True, f"Created {len(created)} missing folder(s)"
        return True, "All folders present"

    def _check_packages(self):
        flags   = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        failed  = []
        for import_name, friendly, critical in REQUIRED_PACKAGES:
            if import_name in ("torch", "stable_whisper"):
                continue   # checked separately
            r = subprocess.run(
                [self.python, "-c",
                 f"import warnings; warnings.filterwarnings('ignore'); "
                 f"import {import_name}; print('ok')"],
                capture_output=True, text=True,
                timeout=15, creationflags=flags)
            if r.returncode != 0 or "ok" not in r.stdout:
                failed.append(friendly)

        if failed:
            self._abort = True
            self.sig.fatal.emit(
                "Missing Packages",
                "The following packages are not installed:\n\n" +
                "\n".join(f"  • {p}" for p in failed),
                "Re-run Setup.exe to install all required packages.\n\n"
                f"If this keeps happening, contact {SUPPORT_EMAIL}"
            )
            return False, f"{len(failed)} package(s) missing"
        return True, f"{len(REQUIRED_PACKAGES) - 2} packages OK"

    def _check_torch(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(
            [self.python, "-c",
             "import warnings; warnings.filterwarnings('ignore'); "
             "import torch; torch.tensor([1.0]); print('ok')"],
            capture_output=True, text=True,
            timeout=20, creationflags=flags)

        if r.returncode == 0 and "ok" in r.stdout:
            return True, "PyTorch working"

        err = (r.stderr + r.stdout).lower()
        if "1114" in err or "dll" in err or "c10" in err:
            self._abort = True
            self.sig.fatal.emit(
                "PyTorch DLL Error",
                "PyTorch failed to load due to a conflicting installation.\n\n"
                "This usually means two versions of PyTorch are installed at once.",
                "Re-run Setup.exe — it will automatically detect and fix this.\n\n"
                "You may also need to install Visual C++ Redistributable:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            )
        elif "numpy" in err:
            self._abort = True
            self.sig.fatal.emit(
                "NumPy Conflict",
                "PyTorch failed to load due to a NumPy version conflict.",
                "Re-run Setup.exe — it will automatically fix this."
            )
        else:
            self._abort = True
            self.sig.fatal.emit(
                "PyTorch Not Working",
                f"PyTorch failed to load:\n\n{r.stderr[:400]}",
                "Re-run Setup.exe to repair your installation.\n\n"
                f"If this continues, contact {SUPPORT_EMAIL}"
            )
        return False, "PyTorch failed"

    def _check_numpy(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(
            [self.python, "-c",
             "import numpy; print(numpy.__version__)"],
            capture_output=True, text=True,
            timeout=10, creationflags=flags)
        if r.returncode == 0:
            ver = r.stdout.strip()
            major = int(ver.split(".")[0])
            if major >= 2:
                return False, (
                    f"NumPy {ver} installed but <2 required — "
                    "re-run Setup.exe")
            return True, f"NumPy {ver}"
        return False, "NumPy not found — re-run Setup.exe"

    def _check_ffmpeg(self):
        # Check PATH
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5, creationflags=flags)
            if r.returncode == 0:
                return True, "FFmpeg in PATH"
        except Exception:
            pass

        # Check app folder
        app_ffmpeg = self.root / "assets" / "ffmpeg.exe"
        if app_ffmpeg.exists():
            return True, "FFmpeg in assets folder"

        # Not fatal — warn only
        return False, (
            "FFmpeg not found — audio processing may fail. "
            "Re-run Setup.exe to install it.")

    def _check_writable(self):
        test_dirs = [
            self.root / "database",
            self.root / "Apollova-Aurora" / "jobs",
        ]
        for d in test_dirs:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
            except Exception as e:
                return False, f"Cannot write to {d.name}: {e}"
        return True, "Folders writable"

    # ─────────────────────────────────────────────────────────────────────────
    #  Launch main app
    # ─────────────────────────────────────────────────────────────────────────
    def _launch_app(self):
        gui = self.root / "assets" / "apollova_gui.py"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        # Add assets/ffmpeg to PATH if applicable
        env = os.environ.copy()
        app_ffmpeg = self.root / "assets"
        if (app_ffmpeg / "ffmpeg.exe").exists():
            env["PATH"] = str(app_ffmpeg) + os.pathsep + env.get("PATH", "")

        try:
            os.chdir(str(self.root / "assets"))
            log.info(f"Launching: {self.python} {gui}")
            proc = subprocess.Popen(
                [self.python, str(gui)],
                env=env,
                creationflags=flags)
            self.hide()
            proc.wait()
            log.info(f"App exited with code {proc.returncode}")
            log.session_end("Apollova", success=proc.returncode == 0)
            sys.exit(proc.returncode)
        except FileNotFoundError:
            log.error(f"FileNotFoundError launching Python: {self.python}")
            self._on_fatal(
                "Python Not Found",
                f"Could not find Python at:\n{self.python}",
                "Re-run Setup.exe to repair your installation."
            )
        except Exception as e:
            log.exception(f"Exception launching app: {e}")
            self._on_fatal(
                "Launch Error",
                f"Apollova could not be launched:\n{e}",
                "Re-run Setup.exe to repair your installation."
            )


# ─────────────────────────────────────────────────────────────────────────────
#  Bootstrap — resolve paths, load settings, find Python
# ─────────────────────────────────────────────────────────────────────────────
def _find_python(root: Path, settings: dict) -> str | None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def valid(path):
        try:
            r = subprocess.run(
                [path, "-c",
                 "import sys; v=sys.version_info; print(v.major, v.minor)"],
                capture_output=True, text=True,
                timeout=5, creationflags=flags)
            if r.returncode == 0:
                parts = r.stdout.strip().split()
                return (len(parts) == 2 and
                        int(parts[0]) == 3 and int(parts[1]) == 11)
        except Exception:
            pass
        return False

    # 1. settings.json
    saved = settings.get("python_path")
    if saved and Path(saved).exists() and valid(saved):
        return saved

    # 2. Common locations
    candidates = [
        r"C:\Program Files\Python311\python.exe",
        r"C:\Python311\python.exe",
        os.path.expanduser(
            r"~\AppData\Local\Programs\Python\Python311\python.exe"),
        "python", "python3",
    ]
    for c in candidates:
        if valid(c):
            return c
    return None


def _show_fatal(title: str, body: str, fix: str):
    try:
        log.error(f"Pre-launch fatal: {title} — {body}")
    except Exception:
        pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    dlg = QMessageBox()
    dlg.setWindowTitle(f"Apollova — {title}")
    dlg.setIcon(QMessageBox.Icon.Critical)
    dlg.setText(f"<b>{title}</b>")
    msg = body
    if fix:
        msg += f"\n\nHow to fix:\n{fix}"
    dlg.setInformativeText(msg)
    dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
    dlg.exec()
    sys.exit(1)


def main():
    # Resolve root
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).parent
    else:
        root = Path(__file__).parent

    # Load settings
    settings = {}
    sf = root / "settings.json"
    if sf.exists():
        try:
            settings = json.loads(sf.read_text())
        except Exception:
            pass

    # Check assets folder exists at all
    if not (root / "assets").exists():
        _show_fatal(
            "Missing Assets",
            "The assets folder is missing.\n\n"
            f"Expected: {root / 'assets'}",
            "Please reinstall Apollova by running Setup.exe."
        )

    # Find Python
    python = _find_python(root, settings)
    if not python:
        _show_fatal(
            "Python 3.11 Not Found",
            "Python 3.11.x could not be found on this system.\n\n"
            "Python 3.11 is required to run Apollova.",
            "Run Setup.exe to install Python 3.11 and all dependencies."
        )

    # Launch loading screen
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova")
    app.setStyleSheet(STYLE)
    screen = LoadingScreen(root, python, settings)
    screen.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
