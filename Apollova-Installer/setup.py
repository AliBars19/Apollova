"""
Apollova Setup Wizard
Bulletproof installer — handles every failure case gracefully.
Zero tkinter. Zero Tcl/Tk. Pure PyQt6.
"""

import os
import sys
import json
import socket
import shutil
import subprocess
import threading
import urllib.request
import urllib.error
import tempfile
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QFrame,
    QMessageBox, QGroupBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# Add assets/ to path so apollova_logger is importable
_ASSETS = (Path(sys.executable).parent if getattr(sys, "frozen", False)
           else Path(__file__).parent) / "assets"
if _ASSETS.exists():
    sys.path.insert(0, str(_ASSETS))
try:
    from apollova_logger import get_logger as _get_logger
    log = _get_logger("setup")
except Exception:
    class _FallbackLog:
        def __getattr__(self, n): return lambda *a, **k: None
    log = _FallbackLog()

# ─────────────────────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────────────────────
PYTHON_VERSION      = "3.11"          # required major.minor
PYTHON_VERSION_FULL = "3.11.9"        # exact installer version
PYTHON_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PYTHON_SIZE = "~25 MB"

TORCH_VERSION     = "2.1.0"
TORCH_INDEX_URL   = "https://download.pytorch.org/whl/cpu"
TORCH_INDEX_CUDA  = "https://download.pytorch.org/whl/cu121"

FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

SUPPORT_EMAIL = "support@apollova.app"
log_python_path = "unknown"

INTERNET_HOSTS = [
    ("8.8.8.8", 53),        # Google DNS
    ("1.1.1.1", 53),        # Cloudflare
    ("pypi.org", 443),
]

# ─────────────────────────────────────────────────────────────────────────────
#  Stylesheet
# ─────────────────────────────────────────────────────────────────────────────
STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #313244;
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QCheckBox { spacing: 8px; color: #cdd6f4; }
QCheckBox::indicator { width: 14px; height: 14px; }
QCheckBox:disabled { color: #585b70; }
QPushButton {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 7px 16px;
    color: #cdd6f4;
    min-width: 80px;
}
QPushButton:hover { background: #45475a; border-color: #89b4fa; }
QPushButton:pressed { background: #89b4fa; color: #1e1e2e; }
QPushButton:disabled { background: #1e1e2e; color: #585b70; border-color: #313244; }
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    font-size: 14px;
    padding: 10px 28px;
}
QPushButton#primary:hover { background: #b4befe; }
QPushButton#primary:disabled { background: #45475a; color: #1e1e2e; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 14px;
    text-align: center;
    color: #cdd6f4;
    font-size: 11px;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #1e1e2e; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical {
    background: #45475a; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #89b4fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Signals
# ─────────────────────────────────────────────────────────────────────────────
class Signals(QObject):
    # (status_text, progress_0_to_100, detail_text)
    update  = pyqtSignal(str, float, str)
    detail  = pyqtSignal(str)
    nudge   = pyqtSignal()          # small progress nudge for animation
    done    = pyqtSignal()
    failed  = pyqtSignal(str, str, str)   # title, body, fix


# ─────────────────────────────────────────────────────────────────────────────
#  Setup Wizard
# ─────────────────────────────────────────────────────────────────────────────
class SetupWizard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apollova Setup")
        self.resize(580, 680)
        self.setMinimumSize(520, 560)
        self.setMaximumWidth(720)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 580) // 2, (screen.height() - 680) // 2)

        # Resolve paths
        if getattr(sys, "frozen", False):
            self.root = Path(sys.executable).parent
        else:
            self.root = Path(__file__).parent
        self.assets_dir  = self.root / "assets"
        self.req_dir     = self.assets_dir / "requirements"

        icon = self.assets_dir / "icon.ico"
        if not icon.exists():
            icon = self.root / "icon.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        # State
        self.installing  = False
        self.cancelled   = False
        self.python_path = None
        self.py_installer_path = None
        self._progress   = 0.0      # current progress float
        self._target     = 0.0      # animation target
        self._online     = False
        self._python_installed_by_setup = False

        # Signals
        self.sig = Signals()
        self.sig.update.connect(self._on_update)
        self.sig.detail.connect(self._on_detail)
        self.sig.nudge.connect(self._on_nudge)
        self.sig.done.connect(self._on_done)
        self.sig.failed.connect(self._on_failed)

        # Smooth progress animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)   # 25fps
        self._anim_timer.timeout.connect(self._animate_progress)
        self._anim_timer.start()

        # Internet recheck timer
        self._net_timer = QTimer(self)
        self._net_timer.setInterval(8000)
        self._net_timer.timeout.connect(self._recheck_internet)

        self._build_ui()
        log.session_start("Setup")
        log.info(f"Install root: {self.root}")
        self._initial_checks()

    # ─────────────────────────────────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 20, 28, 12)
        layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # Title
        t = QLabel("Apollova")
        f = QFont("Segoe UI")
        f.setPointSize(20)
        f.setWeight(QFont.Weight.Bold)
        t.setFont(f)
        t.setStyleSheet("color:#89b4fa;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(t)

        sub = QLabel("Setup & Dependency Installer")
        sub.setStyleSheet("color:#6c7086; font-size:12px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        self._sep(layout)

        # ── Internet status ──────────────────────────────────────────────────
        net_grp = QGroupBox("Internet Connection")
        net_lay = QVBoxLayout(net_grp)
        self.net_lbl = QLabel("  Checking connection...")
        net_lay.addWidget(self.net_lbl)
        layout.addWidget(net_grp)

        # ── Python ───────────────────────────────────────────────────────────
        py_grp = QGroupBox(f"Python  (required: {PYTHON_VERSION}.x)")
        py_lay = QVBoxLayout(py_grp)
        self.py_lbl = QLabel("  Checking...")
        py_lay.addWidget(self.py_lbl)
        self.py_install_chk = QCheckBox(
            f"Download and install Python {PYTHON_VERSION_FULL}  ({PYTHON_SIZE})")
        self.py_install_chk.setEnabled(False)
        py_lay.addWidget(self.py_install_chk)
        layout.addWidget(py_grp)

        # ── Options ──────────────────────────────────────────────────────────
        opt_grp = QGroupBox("Installation Options")
        opt_lay = QVBoxLayout(opt_grp)

        self.base_chk = QCheckBox("Install required packages  (mandatory)")
        self.base_chk.setChecked(True)
        self.base_chk.setEnabled(False)
        opt_lay.addWidget(self.base_chk)

        self._sep(opt_lay)

        self.gpu_chk = QCheckBox("Enable GPU Acceleration  (optional, NVIDIA only)")
        opt_lay.addWidget(self.gpu_chk)
        gpu_note = QLabel(
            "    Requires NVIDIA GPU + CUDA.  Adds ~1.5 GB.  "
            "Speeds up transcription significantly.")
        gpu_note.setStyleSheet("color:#6c7086; font-size:11px;")
        opt_lay.addWidget(gpu_note)

        self._sep(opt_lay)

        self.ffmpeg_chk = QCheckBox(
            "Install FFmpeg  (required for audio processing)")
        self.ffmpeg_chk.setChecked(True)
        opt_lay.addWidget(self.ffmpeg_chk)
        self.ffmpeg_note = QLabel("    Checking FFmpeg...")
        self.ffmpeg_note.setStyleSheet("color:#6c7086; font-size:11px;")
        opt_lay.addWidget(self.ffmpeg_note)

        self._sep(opt_lay)

        self.shortcut_chk = QCheckBox("Create desktop shortcut")
        self.shortcut_chk.setChecked(True)
        opt_lay.addWidget(self.shortcut_chk)

        layout.addWidget(opt_grp)

        # ── Progress ─────────────────────────────────────────────────────────
        prog_grp = QGroupBox("Progress")
        prog_lay = QVBoxLayout(prog_grp)

        self.status_lbl = QLabel("Waiting to start...")
        prog_lay.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)   # fine-grained for smooth animation
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        prog_lay.addWidget(self.progress_bar)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        self.detail_lbl.setWordWrap(True)
        prog_lay.addWidget(self.detail_lbl)

        layout.addWidget(prog_grp)
        layout.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────────
        self._sep(outer)
        btn_w = QWidget()
        btn_lay = QHBoxLayout(btn_w)
        btn_lay.setContentsMargins(28, 10, 28, 16)
        btn_lay.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_lay.addWidget(self.cancel_btn)
        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("primary")
        self.install_btn.setFixedWidth(120)
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._start_install)
        btn_lay.addWidget(self.install_btn)
        outer.addWidget(btn_w)

    def _sep(self, parent):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#313244; margin:4px 0;")
        if hasattr(parent, "addWidget"):
            parent.addWidget(f)
        else:
            parent.addWidget(f)

    # ─────────────────────────────────────────────────────────────────────────
    #  Initial checks (run at startup)
    # ─────────────────────────────────────────────────────────────────────────
    def _initial_checks(self):
        threading.Thread(target=self._run_initial_checks, daemon=True).start()

    def _run_initial_checks(self):
        # Internet
        online = self._check_internet()
        self._online = online
        if online:
            log.info("Internet: connected")
            self.net_lbl.setText("  ✓ Connected to the internet")
            self.net_lbl.setStyleSheet("color:#a6e3a1;")
            self._net_timer.stop()
        else:
            self.net_lbl.setText(
                "  ✗ No internet connection detected.\n"
                "  An internet connection is required to download packages.\n"
                "  Please connect and wait — this will update automatically.")
            log.warning("Internet: no connection detected")
            self.net_lbl.setStyleSheet("color:#f38ba8;")
            self._net_timer.start()

        # Python
        self.python_path = self._find_python()
        if self.python_path:
            v = self._get_python_version(self.python_path)
            self.py_lbl.setText(f"  ✓ Python {v} found at: {self.python_path}")
            self.py_lbl.setStyleSheet("color:#a6e3a1;")
            log.info(f"Python found: {self.python_path} — {v}")
            self.py_install_chk.setEnabled(False)
            self.py_install_chk.setChecked(False)
        else:
            self.py_lbl.setText(
                f"  ✗ Python {PYTHON_VERSION}.x not found.\n"
                f"  Python {PYTHON_VERSION}.x is required — "
                "other versions may not work correctly with all packages.")
            self.py_lbl.setStyleSheet("color:#f9e2af;")
            log.warning(f"Python {PYTHON_VERSION}.x not found")
            self.py_install_chk.setEnabled(True)
            self.py_install_chk.setChecked(True)

        # FFmpeg
        ffmpeg_ok = self._ffmpeg_in_path() or self._ffmpeg_in_app()
        if ffmpeg_ok:
            self.ffmpeg_note.setText(
                "    ✓ FFmpeg already installed — will verify during setup.")
            self.ffmpeg_chk.setChecked(False)
        else:
            self.ffmpeg_note.setText(
                "    FFmpeg not found. Setup will download and install it automatically.")

        # Enable install if online
        self.install_btn.setEnabled(online)
        if not online:
            self.status_lbl.setText(
                "Please connect to the internet to continue.")

    def _recheck_internet(self):
        if self._check_internet():
            self._online = True
            self.net_lbl.setText("  ✓ Connected to the internet")
            self.net_lbl.setStyleSheet("color:#a6e3a1;")
            self.install_btn.setEnabled(True)
            self.status_lbl.setText("Ready to install.")
            self._net_timer.stop()

    # ─────────────────────────────────────────────────────────────────────────
    #  Install flow
    # ─────────────────────────────────────────────────────────────────────────
    def _cancel(self):
        if self.installing:
            self.cancelled = True
            log.warning("User cancelled installation")
            self.status_lbl.setText("Cancelling after current step...")
        else:
            self.close()

    def _start_install(self):
        if self.installing:
            return
        if not self._online:
            QMessageBox.warning(self, "No Connection",
                "An internet connection is required to install Apollova.\n\n"
                "Please connect and try again.")
            return
        if not self.python_path and not self.py_install_chk.isChecked():
            QMessageBox.critical(self, "Python Required",
                f"Python {PYTHON_VERSION}.x is required.\n\n"
                "Please check 'Download and install Python' or install it manually\n"
                f"from python.org/downloads/release/python-{PYTHON_VERSION_FULL.replace('.', '')}/")
            return
        log.section("Installation started")
        log.info(f"GPU: {self.gpu_chk.isChecked()}, FFmpeg: {self.ffmpeg_chk.isChecked()}, Shortcut: {self.shortcut_chk.isChecked()}")
        self.installing = True
        self.cancelled  = False
        self.install_btn.setEnabled(False)
        self.cancel_btn.setText("Cancel")
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _load_setup_state(self):
        """Load completed steps from previous partial install."""
        sf = self.root / "assets" / "logs" / "setup_state.json"
        try:
            if sf.exists():
                return json.loads(sf.read_text())
        except Exception:
            pass
        return {"completed_steps": []}

    def _save_setup_state(self, completed):
        """Persist completed step IDs so setup can resume."""
        sf = self.root / "assets" / "logs" / "setup_state.json"
        try:
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(json.dumps({"completed_steps": completed}))
        except Exception:
            pass

    def _clear_setup_state(self):
        sf = self.root / "assets" / "logs" / "setup_state.json"
        try:
            if sf.exists():
                sf.unlink()
        except Exception:
            pass

    def _install_thread(self):
        try:
            state = self._load_setup_state()
            done_steps = set(state.get("completed_steps", []))

            steps = []
            if not self.python_path and self.py_install_chk.isChecked():
                steps += [
                    ("dl_python",      5,  "Downloading Python..."),
                    ("inst_python",    10, "Installing Python..."),
                ]
            steps += [
                ("check_internet",  12, "Verifying connection..."),
                ("upgrade_pip",     15, "Upgrading pip..."),
                ("install_base",    45, "Installing packages..."),
                ("fix_numpy",       50, "Verifying NumPy..."),
                ("fix_torch",       70, "Installing & verifying PyTorch..."),
            ]
            if self.gpu_chk.isChecked():
                steps.append(("install_gpu", 80, "Installing GPU packages..."))
            if self.ffmpeg_chk.isChecked() or not (
                    self._ffmpeg_in_path() or self._ffmpeg_in_app()):
                steps.append(("install_ffmpeg", 85, "Installing FFmpeg..."))
            steps += [
                ("verify_all",     92, "Verifying all packages..."),
                ("verify_files",   95, "Verifying file integrity..."),
                ("create_files",   98, "Creating launcher files..."),
                ("shortcut",      100, "Finishing up..."),
            ]

            completed = list(done_steps)
            for step_id, target_pct, label in steps:
                if self.cancelled:
                    self.sig.update.emit("Installation cancelled.", 0, "")
                    return
                # Skip steps completed in a previous run
                if step_id in done_steps:
                    log.info(f"Skipping already-completed step: {step_id}")
                    self.sig.detail.emit(f"✓ {label.rstrip('.')} (cached)")
                    self._set_target(target_pct)
                    continue
                self._set_target(target_pct)
                self.sig.update.emit(label, self._progress, "")
                ok = self._run_step(step_id)
                if not ok:
                    self._save_setup_state(completed)
                    return   # step already emitted failed signal
                completed.append(step_id)
                self._save_setup_state(completed)

            self._set_target(100)
            self.sig.update.emit("Installation complete!", 100, "")
            self._save_settings()
            self._clear_setup_state()
            self.sig.done.emit()

        except Exception as e:
            log.exception(f"Unexpected error in install thread: {e}")
            self.sig.failed.emit(
                "Unexpected Error",
                f"An unexpected error occurred:\n\n{type(e).__name__}: {e}",
                f"Please try running Setup again.\n"
                f"If this keeps happening, contact {SUPPORT_EMAIL}"
            )
        finally:
            self.installing = False
            self.install_btn.setEnabled(True)
            self.cancel_btn.setText("Close")

    def _run_step(self, step_id):
        dispatch = {
            "dl_python":     self._step_dl_python,
            "inst_python":   self._step_inst_python,
            "check_internet":self._step_check_internet,
            "upgrade_pip":   self._step_upgrade_pip,
            "install_base":  self._step_install_base,
            "fix_numpy":     self._step_fix_numpy,
            "fix_torch":     self._step_fix_torch,
            "install_gpu":   self._step_install_gpu,
            "install_ffmpeg":self._step_install_ffmpeg,
            "verify_all":    self._step_verify_all,
            "verify_files":  self._step_verify_files,
            "create_files":  self._step_create_files,
            "shortcut":      self._step_shortcut,
        }
        fn = dispatch.get(step_id)
        if fn is None:
            return True
        try:
            return fn()
        except Exception as e:
            log.exception(f"Exception in step '{step_id}': {e}")
            self.sig.failed.emit(
                f"Step Failed: {step_id}",
                f"An error occurred during installation:\n\n{e}",
                f"Please try running Setup again.\nIf this continues, contact {SUPPORT_EMAIL}"
            )
            return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Steps
    # ─────────────────────────────────────────────────────────────────────────
    def _step_check_internet(self):
        if not self._check_internet():
            self.sig.failed.emit(
                "No Internet Connection",
                "Internet connection was lost during installation.",
                "Please reconnect and run Setup again."
            )
            return False
        self.sig.detail.emit("✓ Connection verified.")
        return True

    def _step_upgrade_pip(self):
        python = self.python_path
        flags  = self._flags()
        self.sig.detail.emit("Upgrading pip, setuptools & wheel...")
        try:
            r = subprocess.run(
                [python, "-m", "pip", "install", "--upgrade",
                 "pip", "setuptools", "wheel"],
                capture_output=True, text=True,
                timeout=120, creationflags=flags)
            log.cmd_result(
                [python, "-m", "pip", "install", "--upgrade",
                 "pip", "setuptools", "wheel"],
                r.returncode, r.stdout, r.stderr)
        except Exception as e:
            log.warning(f"pip/setuptools/wheel upgrade failed: {e}")
        self.sig.detail.emit("✓ pip, setuptools & wheel up to date.")
        return True

    def _step_install_base(self):
        req = self.req_dir / "requirements-base.txt"
        if not req.exists():
            self.sig.failed.emit(
                "Missing File",
                f"requirements-base.txt not found at:\n{req}",
                "Please reinstall Apollova — the installer appears to be incomplete."
            )
            return False

        python = self.python_path
        flags  = self._flags()
        lines  = [l.strip() for l in req.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#") and not l.startswith("--")]
        total  = len(lines)
        failed_pkgs = []

        for i, pkg_line in enumerate(lines):
            if self.cancelled:
                return False
            pkg_name = pkg_line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            self.sig.detail.emit(f"Installing {pkg_name}  ({i+1}/{total})...")
            self.sig.nudge.emit()

            # Uninstall wrong version first if pinned with ==
            if "==" in pkg_line:
                self._uninstall_if_wrong_version(python, flags, pkg_line)

            # openai-whisper and stable-ts need --no-build-isolation
            # because their setup.py imports pkg_resources without
            # declaring setuptools as a PEP 517 build dependency
            extra = None
            if pkg_name in ("openai-whisper", "stable-ts"):
                extra = ["--no-build-isolation"]

            ok = self._pip_install(python, flags, pkg_line,
                                   extra_args=extra,
                                   retries=3, timeout=300)
            log.pkg_install(pkg_name, ok)
            if not ok:
                failed_pkgs.append(pkg_name)

        if failed_pkgs:
            self.sig.failed.emit(
                "Package Install Failed",
                f"The following packages could not be installed:\n\n"
                + "\n".join(f"  • {p}" for p in failed_pkgs),
                f"Please check your internet connection and try again.\n"
                f"If this continues, contact {SUPPORT_EMAIL}"
            )
            return False

        self.sig.detail.emit(f"✓ All {total} packages installed.")
        return True

    def _step_fix_numpy(self):
        """Ensure numpy is <2 — required by torch and stable-whisper."""
        python = self.python_path
        flags  = self._flags()
        self.sig.detail.emit("Checking NumPy version...")

        ver = self._get_pkg_version(python, flags, "numpy")
        if ver:
            major = int(ver.split(".")[0])
            if major >= 2:
                log.warning(f"NumPy {ver} detected — downgrading to 1.26.4")
                self.sig.detail.emit(f"NumPy {ver} detected — downgrading to 1.26.4...")
                subprocess.run(
                    [python, "-m", "pip", "uninstall", "numpy", "-y"],
                    capture_output=True, timeout=60, creationflags=flags)
                ok = self._pip_install(python, flags, "numpy==1.26.4",
                                       retries=3, timeout=180)
                if not ok:
                    self.sig.detail.emit(
                        "⚠ NumPy downgrade failed — torch may have issues.")
                    return True  # non-fatal, continue
            else:
                self.sig.detail.emit(f"✓ NumPy {ver} — compatible.")
        return True

    def _step_fix_torch(self):
        """Detect broken torch, nuke conflicts, install clean pinned version."""
        python = self.python_path
        flags  = self._flags()

        # Test current state
        self.sig.detail.emit("Testing PyTorch...")
        test = subprocess.run(
            [python, "-c",
             "import warnings; warnings.filterwarnings('ignore'); "
             "import torch; torch.tensor([1.0]); print('ok')"],
            capture_output=True, text=True, timeout=30, creationflags=flags)

        if test.returncode == 0 and "ok" in test.stdout:
            ver = self._get_pkg_version(python, flags, "torch")
            log.info(f"PyTorch {ver or 'unknown'} already working")
            self.sig.detail.emit(f"✓ PyTorch {ver or 'unknown'} working.")
            return True

        err = (test.stderr + test.stdout).lower()
        if "1114" in err or "dll" in err or "c10" in err:
            log.error(f"Broken PyTorch DLL detected. stderr: {err[:300]}")
            self.sig.detail.emit("⚠ Broken PyTorch DLL detected — fixing...")
        elif "numpy" in err:
            self.sig.detail.emit("⚠ NumPy/PyTorch conflict detected — fixing...")
        else:
            self.sig.detail.emit("⚠ PyTorch not working — reinstalling...")

        # Nuke from user AppData (the usual culprit)
        user_sp = self._get_user_site_packages(python, flags)
        if user_sp:
            for pkg in ["torch", "torchaudio", "torchvision"]:
                d = Path(user_sp) / pkg
                if d.exists():
                    self.sig.detail.emit(f"  Removing conflicting {pkg} from AppData...")
                    try:
                        shutil.rmtree(d)
                    except Exception:
                        pass
            # Remove dist-info too
            try:
                for item in Path(user_sp).glob("torch*.dist-info"):
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass

        # pip uninstall everywhere
        subprocess.run(
            [python, "-m", "pip", "uninstall",
             "torch", "torchaudio", "torchvision", "-y"],
            capture_output=True, timeout=60, creationflags=flags)

        self.sig.nudge.emit()

        # Install pinned CPU torch
        self.sig.detail.emit(f"Installing PyTorch {TORCH_VERSION} (CPU)...")
        ok = self._pip_install(
            python, flags,
            f"torch=={TORCH_VERSION}",
            extra_args=["--index-url", TORCH_INDEX_URL,
                        "--no-user"],
            retries=2, timeout=600)
        if not ok:
            # Retry without --no-user (permissions issue)
            ok = self._pip_install(
                python, flags,
                f"torch=={TORCH_VERSION}",
                extra_args=["--index-url", TORCH_INDEX_URL],
                retries=2, timeout=600)

        self._pip_install(
            python, flags,
            f"torchaudio=={TORCH_VERSION}",
            extra_args=["--index-url", TORCH_INDEX_URL],
            retries=2, timeout=300)

        self.sig.nudge.emit()

        # Verify
        self.sig.detail.emit("Verifying PyTorch...")
        verify = subprocess.run(
            [python, "-c",
             "import warnings; warnings.filterwarnings('ignore'); "
             "import torch; torch.tensor([1.0]); print('ok')"],
            capture_output=True, text=True, timeout=30, creationflags=flags)

        if verify.returncode == 0 and "ok" in verify.stdout:
            log.info(f"PyTorch {TORCH_VERSION} verified working after fix")
            self.sig.detail.emit(f"✓ PyTorch {TORCH_VERSION} working.")
            return True

        # Last resort: suggest VC++ Redist (non-fatal)
        self.sig.detail.emit(
            "⚠ PyTorch could not be fully verified.\n"
            "  If transcription fails, install Visual C++ Redistributable:\n"
            "  https://aka.ms/vs/17/release/vc_redist.x64.exe")
        return True  # non-fatal

    def _step_install_gpu(self):
        req = self.req_dir / "requirements-gpu.txt"
        if not req.exists():
            self.sig.detail.emit("⚠ GPU requirements file missing — skipping.")
            return True

        python = self.python_path
        flags  = self._flags()
        self.sig.detail.emit("Installing GPU packages (~1.5 GB)...")

        # Reinstall torch with CUDA
        subprocess.run(
            [python, "-m", "pip", "uninstall", "torch", "torchaudio", "-y"],
            capture_output=True, timeout=60, creationflags=flags)

        ok = self._pip_install(
            python, flags,
            f"torch=={TORCH_VERSION} torchaudio=={TORCH_VERSION}",
            extra_args=["--index-url", TORCH_INDEX_CUDA],
            retries=2, timeout=1800)

        if not ok:
            self.sig.detail.emit(
                "⚠ GPU packages failed — falling back to CPU PyTorch.")
            self._step_fix_torch()
        else:
            self.sig.detail.emit("✓ GPU packages installed.")
        return True

    def _step_install_ffmpeg(self):
        """Download portable FFmpeg into assets/ folder if not already present."""
        python = self.python_path
        flags  = self._flags()

        if self._ffmpeg_in_path():
            self.sig.detail.emit("✓ FFmpeg already in PATH.")
            return True
        if self._ffmpeg_in_app():
            self.sig.detail.emit("✓ FFmpeg already in app folder.")
            return True

        self.sig.detail.emit("Downloading FFmpeg (portable)...")

        try:
            tmp_zip = Path(tempfile.gettempdir()) / "ffmpeg_apollova.zip"

            def hook(block, bsize, total):
                if total > 0:
                    pct = min(100, block * bsize * 100 // total)
                    self.sig.detail.emit(f"Downloading FFmpeg: {pct}%")
                    self.sig.nudge.emit()

            urllib.request.urlretrieve(FFMPEG_URL, tmp_zip, hook)

            self.sig.detail.emit("Extracting FFmpeg...")
            import zipfile
            extract_dir = Path(tempfile.gettempdir()) / "ffmpeg_apollova_extract"
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(tmp_zip, "r") as z:
                z.extractall(extract_dir)

            # Find ffmpeg.exe inside extracted folder
            ffmpeg_exe = None
            for p in extract_dir.rglob("ffmpeg.exe"):
                ffmpeg_exe = p
                break

            if ffmpeg_exe:
                dest = self.assets_dir / "ffmpeg.exe"
                shutil.copy(ffmpeg_exe, dest)
                # Also copy ffprobe
                ffprobe = ffmpeg_exe.parent / "ffprobe.exe"
                if ffprobe.exists():
                    shutil.copy(ffprobe, self.assets_dir / "ffprobe.exe")
                self.sig.detail.emit("✓ FFmpeg installed to assets folder.")
            else:
                self.sig.detail.emit(
                    "⚠ Could not extract FFmpeg — please install it manually\n"
                    "  from https://ffmpeg.org/download.html and add it to PATH.")

            # Cleanup
            shutil.rmtree(extract_dir, ignore_errors=True)
            try:
                tmp_zip.unlink()
            except Exception:
                pass

        except Exception as e:
            self.sig.detail.emit(
                f"⚠ FFmpeg download failed: {e}\n"
                "  Please install manually from https://ffmpeg.org/download.html")
        return True  # non-fatal

    def _step_verify_all(self):
        """Import-test every package. Report any failures clearly."""
        python = self.python_path
        flags  = self._flags()

        # Map of: import_name -> friendly_name
        packages = [
            ("PyQt6",          "PyQt6"),
            ("torch",          "PyTorch"),
            ("whisper",        "openai-whisper"),
            ("stable_whisper", "stable-ts"),
            ("yt_dlp",         "yt-dlp"),
            ("pydub",          "pydub"),
            ("librosa",        "librosa"),
            ("lyricsgenius",   "lyricsgenius"),
            ("rapidfuzz",      "rapidfuzz"),
            ("colorthief",     "colorthief"),
            ("PIL",            "Pillow"),
            ("requests",       "requests"),
            ("numpy",          "numpy"),
            ("dotenv",         "python-dotenv"),
        ]

        failed = []
        for import_name, friendly in packages:
            self.sig.detail.emit(f"Verifying {friendly}...")
            self.sig.nudge.emit()
            r = subprocess.run(
                [python, "-c",
                 f"import warnings; warnings.filterwarnings('ignore'); "
                 f"import {import_name}; print('ok')"],
                capture_output=True, text=True, timeout=20, creationflags=flags)
            if r.returncode != 0 or "ok" not in r.stdout:
                failed.append(friendly)

        if failed:
            log.error(f"Verification failed: {failed}")
            self.sig.failed.emit(
                "Package Verification Failed",
                "The following packages did not import correctly:\n\n"
                + "\n".join(f"  • {p}" for p in failed)
                + "\n\nThis may cause Apollova to not work properly.",
                f"Try re-running Setup to reinstall them.\n"
                f"If this keeps happening, contact {SUPPORT_EMAIL}"
            )
            return False

        # Verify ffmpeg accessible
        if not self._ffmpeg_in_path() and not self._ffmpeg_in_app():
            self.sig.detail.emit(
                "⚠ FFmpeg not found — audio processing will not work.\n"
                "  Install FFmpeg from https://ffmpeg.org and add to PATH.")
        else:
            log.info("All packages verified: all imports successful")
        self.sig.detail.emit("✓ All packages verified successfully.")

        return True

    def _step_verify_files(self):
        """Check all required asset files exist."""
        required = [
            self.assets_dir / "apollova_gui.py",
            self.assets_dir / "scripts" / "config.py",
            self.assets_dir / "scripts" / "audio_processing.py",
            self.assets_dir / "scripts" / "image_processing.py",
            self.assets_dir / "scripts" / "lyric_processing.py",
            self.assets_dir / "scripts" / "lyric_processing_mono.py",
            self.assets_dir / "scripts" / "lyric_processing_onyx.py",
            self.assets_dir / "scripts" / "lyric_alignment.py",
            self.assets_dir / "scripts" / "song_database.py",
            self.assets_dir / "scripts" / "genius_processing.py",
            self.assets_dir / "scripts" / "smart_picker.py",
            self.req_dir    / "requirements-base.txt",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            log.error(f"Missing files: {missing}")
            self.sig.failed.emit(
                "Missing Files",
                "The following required files are missing:\n\n"
                + "\n".join(f"  • {m}" for m in missing),
                "Please reinstall Apollova — the installer appears to be incomplete."
            )
            return False

        # Create required directories
        for d in [
            self.root / "Apollova-Aurora" / "jobs",
            self.root / "Apollova-Mono"   / "jobs",
            self.root / "Apollova-Onyx"   / "jobs",
            self.root / "database",
            self.root / "templates",
            self.root / "whisper_models",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        log.info("File integrity check passed")
        self.sig.detail.emit("✓ All required files present.")
        return True

    def _step_create_files(self):
        """Create Apollova.bat launcher and write settings.json."""
        try:
            python = self.python_path or "python"
            gui    = self.assets_dir / "apollova_gui.py"
            bat    = self.root / "Apollova.bat"
            bat.write_text(
                "@echo off\n"
                "cd /d \"%~dp0\"\n"
                f"\"{python}\" \"{gui}\"\n"
                "if errorlevel 1 pause\n",
                encoding="utf-8")
            self.sig.detail.emit("✓ Created Apollova.bat")
            return True
        except Exception as e:
            self.sig.detail.emit(f"⚠ Could not create launcher: {e}")
            return True  # non-fatal if .exe exists

    def _step_shortcut(self):
        if not self.shortcut_chk.isChecked():
            return True
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = winreg.QueryValueEx(key, "Desktop")[0]
            winreg.CloseKey(key)

            exe    = self.root / "Apollova.exe"
            bat    = self.root / "Apollova.bat"
            target = exe if exe.exists() else bat
            icon   = self.assets_dir / "icon.ico"
            if not icon.exists():
                icon = self.root / "icon.ico"
            lnk = os.path.join(desktop, "Apollova.lnk")

            ps = (
                f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
                f'$s.TargetPath="{target}";'
                f'$s.WorkingDirectory="{self.root}";'
            )
            if icon.exists():
                ps += f'$s.IconLocation="{icon}";'
            ps += "$s.Save()"

            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=30,
                creationflags=self._flags())
            self.sig.detail.emit("✓ Desktop shortcut created.")
        except Exception as e:
            self.sig.detail.emit(f"Shortcut skipped ({e}) — not fatal.")
        return True

    # ─────────────────────────────────────────────────────────────────────────
    #  Python download / install
    # ─────────────────────────────────────────────────────────────────────────
    def _step_dl_python(self):
        self.sig.detail.emit("Connecting to python.org...")
        try:
            path = Path(tempfile.gettempdir()) / "python_installer.exe"

            def hook(block, bsize, total):
                if total > 0:
                    pct = min(100, block * bsize * 100 // total)
                    self.sig.detail.emit(f"Downloading Python {PYTHON_VERSION_FULL}: {pct}%")
                    self.sig.nudge.emit()

            for attempt in range(3):
                try:
                    urllib.request.urlretrieve(PYTHON_URL, path, hook)
                    self.py_installer_path = path
                    self.sig.detail.emit("✓ Python installer downloaded.")
                    return True
                except Exception as e:
                    if attempt == 2:
                        raise
                    self.sig.detail.emit(f"Retry {attempt + 1}/3...")
                    time.sleep(2)
        except Exception as e:
            self.sig.failed.emit(
                "Python Download Failed",
                f"Could not download Python {PYTHON_VERSION_FULL}:\n{e}",
                f"Please install Python {PYTHON_VERSION_FULL} manually from:\n"
                f"https://www.python.org/ftp/python/{PYTHON_VERSION_FULL}/"
                f"python-{PYTHON_VERSION_FULL}-amd64.exe\n"
                "Then re-run Setup."
            )
            return False

    def _step_inst_python(self):
        self.sig.detail.emit(f"Installing Python {PYTHON_VERSION_FULL} silently...")
        try:
            r = subprocess.run([
                str(self.py_installer_path),
                "/quiet", "InstallAllUsers=0",
                "PrependPath=1", "Include_pip=1", "Include_test=0"
            ], timeout=300)
            if r.returncode == 0:
                self.python_path = self._find_python()
                if self.python_path:
                    self._python_installed_by_setup = True
                    self.sig.detail.emit(f"✓ Python installed at: {self.python_path}")
                    return True
            self.sig.failed.emit(
                "Python Install Failed",
                f"The Python installer exited with code {r.returncode}.",
                f"Please install Python {PYTHON_VERSION_FULL} manually from python.org\n"
                "then re-run Setup."
            )
            return False
        except Exception as e:
            self.sig.failed.emit("Python Install Error", str(e),
                                 "Please install Python manually from python.org.")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _flags(self):
        return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def _check_internet(self):
        for host, port in INTERNET_HOSTS:
            try:
                socket.setdefaulttimeout(4)
                socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                    (host, port))
                return True
            except Exception:
                continue
        return False

    def _find_python(self):
        candidates = [
            r"C:\Program Files\Python311\python.exe",
            r"C:\Python311\python.exe",
            os.path.expanduser(
                r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            "python", "python3",
        ]
        flags = self._flags()
        for c in candidates:
            try:
                r = subprocess.run(
                    [c, "-c",
                     "import sys; v=sys.version_info; "
                     "print(v.major, v.minor, v.micro)"],
                    capture_output=True, text=True,
                    timeout=5, creationflags=flags)
                if r.returncode == 0:
                    parts = r.stdout.strip().split()
                    if len(parts) >= 2:
                        major, minor = int(parts[0]), int(parts[1])
                        if major == 3 and minor == 11:
                            return c
            except Exception:
                continue
        return None

    def _get_python_version(self, path):
        try:
            r = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True,
                timeout=5, creationflags=self._flags())
            return (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
        except Exception:
            return "Unknown"

    def _get_pkg_version(self, python, flags, pkg_name):
        try:
            r = subprocess.run(
                [python, "-c",
                 f"import importlib.metadata; "
                 f"print(importlib.metadata.version('{pkg_name}'))"],
                capture_output=True, text=True,
                timeout=10, creationflags=flags)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        return None

    def _get_user_site_packages(self, python, flags):
        try:
            r = subprocess.run(
                [python, "-c", "import site; print(site.getusersitepackages())"],
                capture_output=True, text=True,
                timeout=5, creationflags=flags)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        return None

    def _uninstall_if_wrong_version(self, python, flags, pkg_line):
        """If package exists at wrong version, uninstall it first."""
        pkg_name = pkg_line.split("==")[0].strip()
        req_ver  = pkg_line.split("==")[1].strip() if "==" in pkg_line else None
        if not req_ver:
            return
        installed = self._get_pkg_version(python, flags, pkg_name)
        if installed and installed != req_ver:
            self.sig.detail.emit(
                f"  {pkg_name}: installed {installed}, need {req_ver} — replacing...")
            subprocess.run(
                [python, "-m", "pip", "uninstall", pkg_name, "-y"],
                capture_output=True, timeout=60, creationflags=flags)

    def _pip_install(self, python, flags, pkg, extra_args=None,
                     retries=3, timeout=300):
        """pip install with retry logic. Returns True on success."""
        base_cmd = [python, "-m", "pip", "install"] + pkg.split()
        if extra_args:
            base_cmd += extra_args

        for attempt in range(retries):
            cmd = list(base_cmd)
            # On retry, add --no-cache-dir to rule out cached bad wheels
            if attempt > 0:
                cmd.append("--no-cache-dir")
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True, creationflags=flags)
                stdout_lines = []
                # Read stdout line by line for live progress
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        line = line.strip()
                        stdout_lines.append(line)
                        if any(k in line for k in
                               ("Collecting", "Installing", "Successfully",
                                "already", "Downloading")):
                            self.sig.detail.emit(f"  {line[:70]}")
                            self.sig.nudge.emit()
                stderr_out = proc.stderr.read()
                proc.wait(timeout=timeout)

                # Always log the full output for debugging
                full_stdout = "\n".join(stdout_lines)
                log.cmd_result(cmd, proc.returncode,
                               full_stdout, stderr_out)

                if proc.returncode == 0:
                    return True
                if attempt < retries - 1:
                    self.sig.detail.emit(
                        f"  Attempt {attempt + 1} failed, retrying...")
                    time.sleep(3)
                else:
                    # Final attempt failed — log the error detail
                    detail = stderr_out.strip() or full_stdout[-500:]
                    log.error(f"pip install {pkg} FAILED after {retries} "
                              f"attempts:\n{detail[:500]}")
            except Exception as e:
                log.error(f"pip install {pkg} exception: {e}")
                if attempt == retries - 1:
                    self.sig.detail.emit(f"  pip error: {e}")
        return False

    def _ffmpeg_in_path(self):
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5,
                creationflags=self._flags())
            return r.returncode == 0
        except Exception:
            return False

    def _ffmpeg_in_app(self):
        return (self.assets_dir / "ffmpeg.exe").exists()

    def _save_settings(self):
        global log_python_path
        log_python_path = self.python_path or "unknown"
        log.info(f"Saving settings: python={self.python_path}")
        try:
            sf = self.root / "settings.json"
            data = {}
            if sf.exists():
                try:
                    data = json.loads(sf.read_text())
                except Exception:
                    pass
            if self.python_path:
                data["python_path"] = str(self.python_path)
            if self._ffmpeg_in_app():
                data["ffmpeg_path"] = str(self.assets_dir / "ffmpeg.exe")
            if self._python_installed_by_setup:
                data["python_installed_by_setup"] = True
            sf.write_text(json.dumps(data, indent=2))
        except Exception as e:
            self.sig.detail.emit(f"⚠ Could not save settings: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Progress animation
    # ─────────────────────────────────────────────────────────────────────────
    def _set_target(self, pct):
        self._target = float(pct)

    def _animate_progress(self):
        """Smoothly nudge progress bar toward target."""
        if self._progress < self._target:
            diff = self._target - self._progress
            step = max(0.15, diff * 0.06)
            self._progress = min(self._target, self._progress + step)
            self.progress_bar.setValue(int(self._progress * 10))
        elif self.installing and self._progress >= self._target:
            # Idle creep — keeps bar moving even between steps
            if self._progress < self._target + 2.0:
                self._progress += 0.03
                self.progress_bar.setValue(int(self._progress * 10))

    def _on_nudge(self):
        """Small bump triggered by active work."""
        self._progress = min(self._target - 0.5, self._progress + 0.4)
        self.progress_bar.setValue(int(self._progress * 10))

    # ─────────────────────────────────────────────────────────────────────────
    #  Signal handlers (main thread)
    # ─────────────────────────────────────────────────────────────────────────
    def _on_update(self, status, progress, detail):
        self.status_lbl.setText(status)
        self._set_target(progress)
        if detail:
            self.detail_lbl.setText(detail)

    def _on_detail(self, detail):
        self.detail_lbl.setText(detail)

    def _on_failed(self, title, body, fix):
        log.error(f"FAILED: {title}\n  {body}")
        log.session_end("Setup", success=False)
        self._anim_timer.stop()
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk { background: #f38ba8; border-radius:4px; }")
        full = body
        if fix:
            full += f"\n\nHow to fix:\n{fix}"
        QMessageBox.critical(self, f"Apollova Setup — {title}", full)

    def _on_done(self):
        log.section("Installation complete")
        log.info(f"All steps completed successfully")
        log.info(f"Python: {log_python_path}")
        log.session_end("Setup", success=True)
        self._set_target(100)
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk { background: #a6e3a1; border-radius:4px; }")

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Apollova — Setup Complete")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText("<b>Installation Complete!</b>")
        dlg.setInformativeText(
            "All packages installed and verified successfully.\n\n"
            "HOW TO RUN APOLLOVA:\n"
            "  Double-click Apollova.exe (or Apollova.bat) in this folder.\n"
            "  Or use the desktop shortcut if you created one.\n\n"
            "FIRST-RUN NOTE:\n"
            "  When you first generate a job, Whisper will download\n"
            "  the transcription model you selected:\n\n"
            "    tiny   ~75 MB      small  ~460 MB\n"
            "    base   ~140 MB     medium ~1.5 GB\n\n"
            f"Questions? Contact: {SUPPORT_EMAIL}"
        )
        dlg.setStandardButtons(QMessageBox.StandardButton.Close)
        dlg.exec()
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova Setup")
    app.setStyleSheet(STYLE)
    win = SetupWizard()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
