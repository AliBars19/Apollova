"""
Apollova Uninstaller
Removes all packages installed by Apollova.
Options to also remove Python and FFmpeg.
Zero terminal output. Pure PyQt6.
"""

import os
import sys
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QFrame,
    QMessageBox, QGroupBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# Logger setup
_HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
_ASSETS = _HERE / "assets"
if _ASSETS.exists():
    sys.path.insert(0, str(_ASSETS))
try:
    from apollova_logger import get_logger as _get_logger
    log = _get_logger("uninstall")
except Exception:
    class _FallbackLog:
        def __getattr__(self, n): return lambda *a, **k: None
    log = _FallbackLog()

SUPPORT_EMAIL = "support@apollova.app"

# pip package name → actual installed directory name.
# Needed because pip names don't always match what lands in site-packages.
_PIP_TO_DIR = {
    "openai-whisper": "whisper",
    "stable-ts":      "stable_whisper",
    "Pillow":         "PIL",
    "python-dotenv":  "dotenv",
}

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
QPushButton#danger {
    background: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    font-size: 14px;
    padding: 10px 28px;
}
QPushButton#danger:hover { background: #eba0ac; }
QPushButton#danger:disabled { background: #45475a; color: #1e1e2e; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 14px;
    text-align: center;
    color: #cdd6f4;
    font-size: 11px;
}
QProgressBar::chunk { background: #f38ba8; border-radius: 4px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #1e1e2e; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical {
    background: #45475a; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #89b4fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class Signals(QObject):
    update = pyqtSignal(str, float, str)   # status, progress, detail
    detail = pyqtSignal(str)
    nudge  = pyqtSignal()
    done   = pyqtSignal()
    error  = pyqtSignal(str, str)


class UninstallWizard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apollova Uninstaller")
        self.resize(580, 700)
        self.setMinimumSize(520, 580)
        self.setMaximumWidth(720)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 580) // 2,
                  (screen.height() - 700) // 2)

        # Paths
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

        # Load settings
        self.settings   = {}
        sf = self.root / "settings.json"
        if sf.exists():
            try:
                self.settings = json.loads(sf.read_text())
            except Exception:
                pass

        self.python_path = self._find_python()
        self.uninstalling = False
        self.cancelled    = False

        # Progress animation
        self._progress = 0.0
        self._target   = 0.0
        self._anim = QTimer(self)
        self._anim.setInterval(30)
        self._anim.timeout.connect(self._animate)
        self._anim.start()

        self.sig = Signals()
        self.sig.update.connect(self._on_update)
        self.sig.detail.connect(lambda t: self.detail_lbl.setText(t))
        self.sig.nudge.connect(self._on_nudge)
        self.sig.done.connect(self._on_done)
        self.sig.error.connect(self._on_error)

        log.session_start("Uninstaller")
        log.info(f"Install root: {self.root}")
        log.info(f"Python found: {self.python_path or 'not found'}")
        self._build_ui()
        self._check_initial_state()

    # ─────────────────────────────────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

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
        t.setStyleSheet("color:#f38ba8;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(t)

        sub = QLabel("Uninstaller")
        sub.setStyleSheet("color:#6c7086; font-size:12px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        self._hsep(layout)

        # ── Python status ────────────────────────────────────────────────────
        py_grp = QGroupBox("Python")
        py_lay = QVBoxLayout(py_grp)
        self.py_lbl = QLabel("  Checking...")
        py_lay.addWidget(self.py_lbl)
        layout.addWidget(py_grp)

        # ── What to remove ───────────────────────────────────────────────────
        rem_grp = QGroupBox("What to Remove")
        rem_lay = QVBoxLayout(rem_grp)

        # Mandatory
        self.pkgs_chk = QCheckBox(
            "Uninstall all Apollova Python packages  (mandatory)")
        self.pkgs_chk.setChecked(True)
        self.pkgs_chk.setEnabled(False)
        rem_lay.addWidget(self.pkgs_chk)

        self._hsep(rem_lay)

        # Jobs
        self.jobs_chk = QCheckBox(
            "Delete all job folders  (Aurora, Mono, Onyx)")
        self.jobs_chk.setChecked(False)
        rem_lay.addWidget(self.jobs_chk)
        jobs_note = QLabel(
            "    Deletes all generated job folders and their audio/lyric files.\n"
            "    Your After Effects templates and database are NOT affected.")
        jobs_note.setStyleSheet("color:#6c7086; font-size:11px;")
        rem_lay.addWidget(jobs_note)

        self._hsep(rem_lay)

        # Database
        self.db_chk = QCheckBox(
            "Delete database  (removes all cached song data)")
        self.db_chk.setChecked(False)
        rem_lay.addWidget(self.db_chk)
        db_note = QLabel(
            "    Permanently deletes songs.db — all cached lyrics,\n"
            "    transcriptions, and usage counts will be lost.")
        db_note.setStyleSheet("color:#6c7086; font-size:11px;")
        rem_lay.addWidget(db_note)

        self._hsep(rem_lay)

        # Whisper models
        self.whisper_chk = QCheckBox(
            "Delete Whisper model cache  (whisper_models/ folder)")
        self.whisper_chk.setChecked(False)
        rem_lay.addWidget(self.whisper_chk)
        self.whisper_note = QLabel(
            "    Checking size...")
        self.whisper_note.setStyleSheet("color:#6c7086; font-size:11px;")
        rem_lay.addWidget(self.whisper_note)

        self._hsep(rem_lay)

        # FFmpeg
        self.ffmpeg_chk = QCheckBox(
            "Remove FFmpeg  (installed by Apollova Setup)")
        self.ffmpeg_chk.setChecked(False)
        rem_lay.addWidget(self.ffmpeg_chk)
        self.ffmpeg_note = QLabel(
            "    Checking FFmpeg status...")
        self.ffmpeg_note.setStyleSheet("color:#6c7086; font-size:11px;")
        rem_lay.addWidget(self.ffmpeg_note)

        self._hsep(rem_lay)

        # Python
        self.python_chk = QCheckBox(
            "Uninstall Python 3.11  (installed by Apollova Setup)")
        self.python_chk.setChecked(False)
        rem_lay.addWidget(self.python_chk)
        self.python_note = QLabel(
            "    WARNING: Only remove Python if Apollova installed it and\n"
            "    you do not use Python for anything else.\n"
            "    This will remove Python from your system entirely.")
        self.python_note.setStyleSheet("color:#f9e2af; font-size:11px;")
        rem_lay.addWidget(self.python_note)

        layout.addWidget(rem_grp)

        # ── What is kept ─────────────────────────────────────────────────────
        keep_grp = QGroupBox("What is Always Kept")
        keep_lay = QVBoxLayout(keep_grp)
        keep_lbl = QLabel(
            "  • After Effects template files (.aep)\n"
            "  • This installer folder and its contents\n"
            "  • settings.json")
        keep_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        keep_lay.addWidget(keep_lbl)
        layout.addWidget(keep_grp)

        # ── Progress ─────────────────────────────────────────────────────────
        prog_grp = QGroupBox("Progress")
        prog_lay = QVBoxLayout(prog_grp)
        self.status_lbl = QLabel("Ready to uninstall.")
        prog_lay.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
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
        self._hsep(outer)
        btn_w = QWidget()
        btn_lay = QHBoxLayout(btn_w)
        btn_lay.setContentsMargins(28, 10, 28, 16)
        btn_lay.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_lay.addWidget(self.cancel_btn)
        self.uninstall_btn = QPushButton("Uninstall")
        self.uninstall_btn.setObjectName("danger")
        self.uninstall_btn.setFixedWidth(130)
        self.uninstall_btn.clicked.connect(self._start_uninstall)
        btn_lay.addWidget(self.uninstall_btn)
        outer.addWidget(btn_w)

    def _hsep(self, parent):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#313244; margin:4px 0;")
        parent.addWidget(f)

    # ─────────────────────────────────────────────────────────────────────────
    #  Initial state checks
    # ─────────────────────────────────────────────────────────────────────────
    def _check_initial_state(self):
        # Python label
        if self.python_path:
            v = self._get_python_version(self.python_path)
            self.py_lbl.setText(
                f"  ✓ Python {v} found — pip packages will be removed")
            self.py_lbl.setStyleSheet("color:#a6e3a1;")
        else:
            self.py_lbl.setText(
                "  ✗ Python not found — pip packages cannot be removed automatically")
            self.py_lbl.setStyleSheet("color:#f38ba8;")
            self.python_chk.setEnabled(False)

        # Whisper models label
        wm_dir = self.root / "whisper_models"
        if wm_dir.exists():
            try:
                wm_size = sum(
                    f.stat().st_size for f in wm_dir.rglob("*") if f.is_file())
                wm_gb = wm_size / (1024 ** 3)
                size_str = (f"{wm_gb:.1f} GB" if wm_gb >= 1
                            else f"{wm_size / (1024**2):.0f} MB")
                self.whisper_note.setText(
                    f"    ⚠ {size_str} of model files — "
                    "models must be re-downloaded if you use Apollova again.")
                self.whisper_note.setStyleSheet("color:#f9e2af; font-size:11px;")
            except Exception:
                self.whisper_note.setText(
                    "    Whisper models folder found.")
        else:
            self.whisper_note.setText(
                "    No Whisper models found — nothing to remove.")
            self.whisper_chk.setEnabled(False)

        # FFmpeg label
        app_ffmpeg = self.assets_dir / "ffmpeg.exe"
        in_path    = self._ffmpeg_in_path()
        in_app     = app_ffmpeg.exists()

        if in_app:
            self.ffmpeg_note.setText(
                "    ✓ FFmpeg found in assets folder — was installed by Apollova Setup.")
            self.ffmpeg_chk.setChecked(True)
        elif in_path:
            self.ffmpeg_note.setText(
                "    FFmpeg found in system PATH — was not installed by Apollova Setup.\n"
                "    Check this only if you want to remove it.")
        else:
            self.ffmpeg_note.setText(
                "    FFmpeg not found — nothing to remove.")
            self.ffmpeg_chk.setEnabled(False)

        # Python removal warning — only offer if setup installed it
        setup_installed_python = self.settings.get("python_installed_by_setup", False)
        if not setup_installed_python:
            self.python_note.setText(
                self.python_note.text() + "\n"
                "    (Setup did not install Python on this machine — "
                "use with caution.)")

    # ─────────────────────────────────────────────────────────────────────────
    #  Uninstall flow
    # ─────────────────────────────────────────────────────────────────────────
    def _cancel(self):
        if self.uninstalling:
            self.cancelled = True
            log.warning("User cancelled uninstall")
            self.status_lbl.setText("Cancelling after current step...")
        else:
            self.close()

    def _start_uninstall(self):
        if self.uninstalling:
            return

        # Build summary of what will happen
        actions = ["  • Remove all Apollova Python packages"]
        if self.jobs_chk.isChecked():
            actions.append("  • Delete all job folders (Aurora, Mono, Onyx)")
        if self.db_chk.isChecked():
            actions.append("  • Delete songs database")
        if self.whisper_chk.isChecked():
            actions.append("  • Delete Whisper model cache (whisper_models/)")
        if self.ffmpeg_chk.isChecked():
            actions.append("  • Remove FFmpeg")
        if self.python_chk.isChecked():
            actions.append("  • Uninstall Python 3.11 from your system")

        warning = ""
        if self.python_chk.isChecked():
            warning = ("\n\n⚠ WARNING: You have chosen to uninstall Python.\n"
                       "This will remove Python 3.11 from your system entirely.\n"
                       "Do not do this if you use Python for other purposes.")

        reply = QMessageBox.question(
            self, "Confirm Uninstall",
            "The following will be removed:\n\n" +
            "\n".join(actions) + warning +
            "\n\nThis cannot be undone. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply != QMessageBox.StandardButton.Yes:
            return

        log.section("Uninstall started")
        log.info(f"Options — jobs:{self.jobs_chk.isChecked()} db:{self.db_chk.isChecked()} ffmpeg:{self.ffmpeg_chk.isChecked()} python:{self.python_chk.isChecked()}")
        self.uninstalling = True
        self.cancelled    = False
        self.uninstall_btn.setEnabled(False)
        threading.Thread(target=self._uninstall_thread, daemon=True).start()

    def _uninstall_thread(self):
        try:
            steps = [("packages", 40, "Removing Python packages...")]
            if self.jobs_chk.isChecked():
                steps.append(("jobs", 52, "Deleting job folders..."))
            if self.db_chk.isChecked():
                steps.append(("database", 60, "Deleting database..."))
            if self.whisper_chk.isChecked():
                steps.append(("whisper", 72, "Deleting Whisper model cache..."))
            if self.ffmpeg_chk.isChecked():
                steps.append(("ffmpeg", 82, "Removing FFmpeg..."))
            if self.python_chk.isChecked():
                steps.append(("python", 95, "Uninstalling Python..."))
            steps.append(("cleanup", 100, "Cleaning up..."))

            for step_id, target, label in steps:
                if self.cancelled:
                    self.sig.update.emit("Cancelled.", 0, "")
                    return
                self._target = float(target)
                self.sig.update.emit(label, self._progress, "")
                log.info(f"Step: {step_id}  —  {label}")
                self._run_step(step_id)
                time.sleep(0.1)

            self._target = 100.0
            self.sig.update.emit("Uninstall complete.", 100, "")
            self.sig.done.emit()

        except Exception as e:
            log.exception(f"Unexpected error in uninstall thread: {e}")
            self.sig.error.emit("Unexpected Error", str(e))
        finally:
            self.uninstalling = False
            self.uninstall_btn.setEnabled(True)
            self.cancel_btn.setText("Close")

    def _run_step(self, step_id):
        try:
            {
                "packages": self._step_remove_packages,
                "jobs":     self._step_delete_jobs,
                "database": self._step_delete_database,
                "whisper":  self._step_delete_whisper_models,
                "ffmpeg":   self._step_remove_ffmpeg,
                "python":   self._step_remove_python,
                "cleanup":  self._step_cleanup,
            }[step_id]()
        except Exception as e:
            log.exception(f"Exception in step '{step_id}': {e}")
            self.sig.detail.emit(f"⚠ Step error ({step_id}): {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Steps
    # ─────────────────────────────────────────────────────────────────────────
    def _step_remove_packages(self):
        if not self.python_path:
            self.sig.detail.emit(
                "Python not found — skipping pip uninstall.\n"
                "You may need to remove packages manually.")
            return

        flags    = self._flags()
        packages = self._collect_packages()
        if not packages:
            self.sig.detail.emit("No packages found to remove.")
            return

        # Single pip call — much faster than one subprocess per package
        self.sig.detail.emit(
            f"Removing {len(packages)} packages (this may take a minute)...")
        r = subprocess.run(
            [self.python_path, "-m", "pip", "uninstall"] + packages + ["-y"],
            capture_output=True, text=True, timeout=300, creationflags=flags)
        log.pkg_install(
            "all-packages",
            r.returncode == 0,
            f"batch-removed {len(packages)}" if r.returncode == 0
            else r.stderr[:200])
        if r.returncode != 0:
            log.warning(f"pip uninstall stderr: {r.stderr[:300]}")

        # Remove any leftover directories in user AppData site-packages.
        # pip names don't always match directory names — use the mapping.
        user_sp = self._get_user_site_packages()
        if user_sp:
            user_sp_path = Path(user_sp)
            for pkg in packages:
                dir_name  = _PIP_TO_DIR.get(pkg, pkg)
                dist_name = pkg.replace("-", "_")   # dist-info uses underscores

                pkg_dir = user_sp_path / dir_name
                if pkg_dir.exists():
                    self.sig.detail.emit(f"  Removing leftover: {dir_name}...")
                    shutil.rmtree(pkg_dir, ignore_errors=True)

                for item in user_sp_path.glob(f"{dist_name}-*.dist-info"):
                    shutil.rmtree(item, ignore_errors=True)

        self.sig.detail.emit(f"✓ Removed {len(packages)} packages.")

    def _step_delete_jobs(self):
        dirs = [
            self.root / "Apollova-Aurora" / "jobs",
            self.root / "Apollova-Mono"   / "jobs",
            self.root / "Apollova-Onyx"   / "jobs",
        ]
        for d in dirs:
            if d.exists():
                self.sig.detail.emit(f"  Deleting {d.parent.name}/jobs...")
                try:
                    shutil.rmtree(d)
                    d.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    self.sig.detail.emit(f"  ⚠ Could not delete {d}: {e}")
        self.sig.detail.emit("✓ Job folders cleared.")

    def _step_delete_database(self):
        db = self.root / "database" / "songs.db"
        if db.exists():
            try:
                db.unlink()
                log.info("Database deleted")
                self.sig.detail.emit("✓ Database deleted.")
            except Exception as e:
                self.sig.detail.emit(f"⚠ Could not delete database: {e}")
        else:
            self.sig.detail.emit("No database found.")

    def _step_delete_whisper_models(self):
        wm_dir = self.root / "whisper_models"
        if wm_dir.exists():
            try:
                shutil.rmtree(wm_dir)
                log.info("Whisper model cache deleted")
                self.sig.detail.emit("✓ Whisper model cache deleted.")
            except Exception as e:
                self.sig.detail.emit(f"⚠ Could not delete whisper_models: {e}")
        else:
            self.sig.detail.emit("No Whisper model cache found.")

    def _step_remove_ffmpeg(self):
        # Remove from assets folder
        for fname in ["ffmpeg.exe", "ffprobe.exe", "ffplay.exe"]:
            f = self.assets_dir / fname
            if f.exists():
                try:
                    f.unlink()
                    self.sig.detail.emit(f"  Removed {fname} from assets.")
                except Exception as e:
                    self.sig.detail.emit(f"  ⚠ Could not remove {fname}: {e}")

        # If FFmpeg is in PATH and user confirmed, attempt to locate and remove
        if self._ffmpeg_in_path():
            flags = self._flags()
            try:
                r = subprocess.run(
                    ["where", "ffmpeg"],
                    capture_output=True, text=True,
                    timeout=5, creationflags=flags)
                if r.returncode == 0:
                    for line in r.stdout.strip().splitlines():
                        p = Path(line.strip())
                        if p.exists():
                            self.sig.detail.emit(
                                f"  FFmpeg in PATH at {p.parent} — "
                                "cannot auto-remove system FFmpeg.\n"
                                "  Please remove it manually if desired.")
                            break
            except Exception:
                pass

        self.sig.detail.emit("✓ FFmpeg removed.")

    def _step_remove_python(self):
        """
        Attempt silent uninstall of Python 3.11 using the Windows uninstaller.
        """
        if not self.python_path:
            self.sig.detail.emit("Python path unknown — cannot auto-remove.")
            return

        flags = self._flags()

        # Find the Python uninstaller via registry
        try:
            import winreg
            uninstall_cmd = None
            for root_key in [winreg.HKEY_LOCAL_MACHINE,
                              winreg.HKEY_CURRENT_USER]:
                for sub in [
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                ]:
                    try:
                        key = winreg.OpenKey(root_key, sub)
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                sub_key = winreg.EnumKey(key, i)
                                sub_h   = winreg.OpenKey(key, sub_key)
                                name    = winreg.QueryValueEx(
                                    sub_h, "DisplayName")[0]
                                if "Python 3.11" in name:
                                    uninstall_cmd = winreg.QueryValueEx(
                                        sub_h, "UninstallString")[0]
                                    winreg.CloseKey(sub_h)
                                    break
                            except Exception:
                                continue
                        winreg.CloseKey(key)
                        if uninstall_cmd:
                            break
                    except Exception:
                        continue
                if uninstall_cmd:
                    break

            if uninstall_cmd:
                self.sig.detail.emit(
                    "Uninstalling Python 3.11 (this may take a minute)...")
                # Add /quiet if it's an MSI-based uninstall
                cmd = uninstall_cmd
                if "msiexec" in cmd.lower():
                    cmd += " /quiet /norestart"
                elif ".exe" in cmd.lower():
                    cmd += " /quiet"
                subprocess.run(
                    cmd, shell=True, timeout=300, creationflags=flags)
                log.info("Python 3.11 uninstalled via registry uninstaller")
                self.sig.detail.emit("✓ Python 3.11 uninstalled.")
            else:
                self.sig.detail.emit(
                    "⚠ Could not find Python 3.11 in Windows registry.\n"
                    "  Please uninstall Python 3.11 manually via:\n"
                    "  Settings → Apps → Python 3.11")
        except ImportError:
            self.sig.detail.emit(
                "⚠ winreg not available — please uninstall Python manually.")
        except Exception as e:
            self.sig.detail.emit(f"⚠ Python uninstall error: {e}")

    def _step_cleanup(self):
        # Apollova.bat
        bat = self.root / "Apollova.bat"
        if bat.exists():
            try:
                bat.unlink()
            except Exception:
                pass

        # __pycache__ folders (bytecode left over from running the app)
        for pc in self.assets_dir.rglob("__pycache__"):
            shutil.rmtree(pc, ignore_errors=True)

        # Invalidate the launcher's 24h integrity-check cache so a fresh
        # install isn't silently skipped by the old cached result
        last_check = self.assets_dir / "logs" / "last_check.json"
        if last_check.exists():
            try:
                last_check.unlink()
            except Exception:
                pass

        # Desktop shortcut
        try:
            import winreg
            key     = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = winreg.QueryValueEx(key, "Desktop")[0]
            winreg.CloseKey(key)
            lnk = Path(desktop) / "Apollova.lnk"
            if lnk.exists():
                lnk.unlink()
                self.sig.detail.emit("✓ Desktop shortcut removed.")
        except Exception:
            pass

        self.sig.detail.emit("✓ Cleanup complete.")

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _flags(self):
        return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def _find_python(self):
        flags = self._flags()
        saved = self.settings.get("python_path")

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

        if saved and Path(saved).exists() and valid(saved):
            return saved
        for c in [
            r"C:\Program Files\Python311\python.exe",
            r"C:\Python311\python.exe",
            os.path.expanduser(
                r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            "python",
        ]:
            if valid(c):
                return c
        return None

    def _get_python_version(self, path):
        try:
            flags = self._flags()
            r = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True,
                timeout=5, creationflags=flags)
            return (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
        except Exception:
            return "Unknown"

    def _get_user_site_packages(self):
        if not self.python_path:
            return None
        try:
            flags = self._flags()
            r = subprocess.run(
                [self.python_path, "-c",
                 "import site; print(site.getusersitepackages())"],
                capture_output=True, text=True,
                timeout=5, creationflags=flags)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        return None

    def _collect_packages(self):
        """Read all package names from requirements files."""
        packages = []
        for fname in ("requirements-base.txt", "requirements-gpu.txt"):
            fpath = self.req_dir / fname
            if not fpath.exists():
                continue
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("--"):
                    continue
                pkg = (line.split("==")[0].split(">=")[0]
                       .split("<=")[0].split("[")[0].strip())
                if pkg and pkg not in packages:
                    packages.append(pkg)
        # Always include torch even if not in requirements
        for extra in ["torch", "torchaudio", "torchvision",
                      "stable-ts", "stable_whisper"]:
            if extra not in packages:
                packages.append(extra)
        return packages

    def _ffmpeg_in_path(self):
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5,
                creationflags=self._flags())
            return r.returncode == 0
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Progress animation
    # ─────────────────────────────────────────────────────────────────────────
    def _animate(self):
        if self._progress < self._target:
            diff = self._target - self._progress
            step = max(0.15, diff * 0.06)
            self._progress = min(self._target, self._progress + step)
            self.progress_bar.setValue(int(self._progress * 10))

    def _on_nudge(self):
        self._progress = min(self._target - 0.5, self._progress + 0.5)
        self.progress_bar.setValue(int(self._progress * 10))

    # ─────────────────────────────────────────────────────────────────────────
    #  Signal handlers
    # ─────────────────────────────────────────────────────────────────────────
    def _on_update(self, status, progress, detail):
        self.status_lbl.setText(status)
        self._target = float(progress)
        if detail:
            self.detail_lbl.setText(detail)

    def _on_error(self, title, msg):
        log.error(f"Error: {title} — {msg}")
        QMessageBox.critical(self, f"Apollova — {title}",
                             f"{msg}\n\nContact {SUPPORT_EMAIL} if this continues.")

    def _on_done(self):
        log.session_end("Uninstaller", success=True)
        self._target = 100.0
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk { background:#a6e3a1; border-radius:4px; }")

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Apollova — Uninstall Complete")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText("<b>Uninstall Complete</b>")
        dlg.setInformativeText(
            "All selected items have been removed.\n\n"
            "You can now delete the Apollova folder to remove everything.\n\n"
            "Thank you for using Apollova."
        )
        dlg.setStandardButtons(QMessageBox.StandardButton.Close)
        dlg.exec()
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova Uninstaller")
    app.setStyleSheet(STYLE)
    win = UninstallWizard()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
