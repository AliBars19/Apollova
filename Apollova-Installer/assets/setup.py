"""
Apollova Setup Wizard — PyQt6 (no tkinter, no Tcl/Tk)
"""

import os
import sys
import subprocess
import threading
import urllib.request
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QFrame, QMessageBox,
    QScrollArea, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# ── Stylesheet ────────────────────────────────────────────────────────────────
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
    padding: 10px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QCheckBox { spacing: 6px; color: #cdd6f4; }
QCheckBox::indicator { width: 14px; height: 14px; }
QCheckBox:disabled { color: #585b70; }
QPushButton {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 7px 16px;
    color: #cdd6f4;
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
QPushButton#primary:disabled { background: #313244; color: #585b70; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 12px;
    text-align: center;
    color: #1e1e2e;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QScrollArea { border: none; }
QScrollBar:vertical {
    background: #1e1e2e; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #89b4fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ── Signals ───────────────────────────────────────────────────────────────────
class SetupSignals(QObject):
    status  = pyqtSignal(str, int, str)   # status text, progress %, detail
    detail  = pyqtSignal(str)
    done    = pyqtSignal()
    error   = pyqtSignal(str, str)        # title, message


# ── Main Window ───────────────────────────────────────────────────────────────
class SetupWizard(QMainWindow):
    PYTHON_URL            = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    PYTHON_INSTALLER_SIZE = "~25 MB"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apollova Setup")
        self.resize(560, 620)
        self.setMinimumSize(500, 500)
        self.setMaximumWidth(700)

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 560) // 2, (screen.height() - 620) // 2)

        if getattr(sys, 'frozen', False):
            self.install_dir = Path(sys.executable).parent
        else:
            self.install_dir = Path(__file__).parent

        self.assets_dir      = self.install_dir / "assets"
        self.requirements_dir = self.assets_dir / "requirements"

        icon_path = self.assets_dir / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.installing             = False
        self.cancelled              = False
        self.python_path            = None
        self.python_installer_path  = None

        self.signals = SetupSignals()
        self.signals.status.connect(self._on_status)
        self.signals.detail.connect(self._on_detail)
        self.signals.done.connect(self._show_complete_dialog)
        self.signals.error.connect(self._on_error)

        self._build_ui()
        self._check_python()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        page = QWidget()
        self.setCentralWidget(page)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_w = QWidget()
        layout = QVBoxLayout(content_w)
        layout.setContentsMargins(28, 22, 28, 10)
        layout.setSpacing(12)
        scroll.setWidget(content_w)
        outer.addWidget(scroll)

        # Title
        title = QLabel("Apollova")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color:#89b4fa;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("Setup & Dependency Installer")
        sub.setStyleSheet("color:#6c7086; font-size:12px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#313244;")
        layout.addWidget(sep)

        # Python section
        py_grp = QGroupBox("Python")
        py_lay = QVBoxLayout(py_grp)
        self.python_status_lbl = QLabel("Checking...")
        py_lay.addWidget(self.python_status_lbl)
        self.install_python_chk = QCheckBox(
            f"Download and install Python 3.11 for me  ({self.PYTHON_INSTALLER_SIZE})")
        self.install_python_chk.setEnabled(False)
        py_lay.addWidget(self.install_python_chk)
        layout.addWidget(py_grp)

        # Options section
        opt_grp = QGroupBox("Installation Options")
        opt_lay = QVBoxLayout(opt_grp)

        self.base_chk = QCheckBox("Install required packages  (mandatory)")
        self.base_chk.setChecked(True)
        self.base_chk.setEnabled(False)
        opt_lay.addWidget(self.base_chk)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#313244;")
        opt_lay.addWidget(sep2)

        self.gpu_chk = QCheckBox("Enable GPU Acceleration  (optional)")
        opt_lay.addWidget(self.gpu_chk)

        gpu_info = QLabel(
            "    Requires an NVIDIA GPU with CUDA support.\n"
            "    Adds ~1.5 GB and significantly speeds up transcription.")
        gpu_info.setStyleSheet("color:#6c7086; font-size:11px;")
        opt_lay.addWidget(gpu_info)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color:#313244;")
        opt_lay.addWidget(sep3)

        self.shortcut_chk = QCheckBox("Create desktop shortcut")
        self.shortcut_chk.setChecked(True)
        opt_lay.addWidget(self.shortcut_chk)

        layout.addWidget(opt_grp)

        # Progress section
        prog_grp = QGroupBox("Progress")
        prog_lay = QVBoxLayout(prog_grp)

        self.status_lbl = QLabel("Ready to install.")
        prog_lay.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_lay.addWidget(self.progress_bar)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        prog_lay.addWidget(self.detail_lbl)

        layout.addWidget(prog_grp)
        layout.addStretch()

        # Bottom buttons — outside scroll area so always visible
        sep_btn = QFrame()
        sep_btn.setFrameShape(QFrame.Shape.HLine)
        sep_btn.setStyleSheet("color:#313244;")
        outer.addWidget(sep_btn)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(28, 10, 28, 16)
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("primary")
        self.install_btn.setFixedWidth(120)
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_row)
        outer.addWidget(btn_widget)

    # ── Python detection ──────────────────────────────────────────────────────

    def _check_python(self):
        self.python_path = self._find_python()
        if self.python_path:
            v = self._get_python_version(self.python_path)
            self.python_status_lbl.setText(f"  ✓ Python {v} found")
            self.python_status_lbl.setStyleSheet("color:#a6e3a1;")
            self.install_python_chk.setEnabled(False)
            self.install_python_chk.setChecked(False)
        else:
            self.python_status_lbl.setText("  ✗ Python 3.10+ not found")
            self.python_status_lbl.setStyleSheet("color:#f38ba8;")
            self.install_python_chk.setEnabled(True)
            self.install_python_chk.setChecked(True)

    def _find_python(self):
        candidates = [
            "python", "python3",
            r"C:\Program Files\Python311\python.exe",
            r"C:\Python314\python.exe",
            r"C:\Python313\python.exe",
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python314\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python313\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python310\python.exe"),
        ]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        for path in candidates:
            try:
                r = subprocess.run(
                    [path, "-c",
                     "import sys; v=sys.version_info; print(v.major, v.minor)"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=flags)
                if r.returncode == 0:
                    parts = r.stdout.strip().split()
                    if len(parts) == 2:
                        major, minor = int(parts[0]), int(parts[1])
                        if major == 3 and minor >= 10:
                            return path
            except Exception:
                continue
        return None

    def _get_python_version(self, python_path):
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            r = subprocess.run([python_path, "--version"],
                               capture_output=True, text=True, timeout=5,
                               creationflags=flags)
            return (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
        except Exception:
            return "Unknown"

    # ── Install flow ──────────────────────────────────────────────────────────

    def _cancel(self):
        if self.installing:
            self.cancelled = True
            self.status_lbl.setText("Cancelling…")
        else:
            self.close()

    def _start_install(self):
        if self.installing:
            return
        if not self.python_path and not self.install_python_chk.isChecked():
            QMessageBox.critical(self, "Python Required",
                "Python 3.10+ is required to run Apollova.\n\n"
                "Check 'Download and install Python' above, or install it "
                "manually from python.org then re-run setup.")
            return
        self.installing = True
        self.cancelled  = False
        self.install_btn.setEnabled(False)
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        try:
            steps = []
            if not self.python_path and self.install_python_chk.isChecked():
                steps += [
                    ("download_python", "Downloading Python 3.11…"),
                    ("install_python",  "Installing Python 3.11…"),
                ]
            steps.append(("install_base", "Installing required packages…"))
            if self.gpu_chk.isChecked():
                steps.append(("install_gpu",
                               "Installing GPU packages (PyTorch ~1.5 GB)…"))
            steps += [
                ("create_launcher",    "Creating launcher…"),
                ("create_uninstaller", "Creating uninstaller…"),
            ]
            if self.shortcut_chk.isChecked():
                steps.append(("create_shortcut", "Creating desktop shortcut…"))

            total = len(steps)
            for i, (step_id, label) in enumerate(steps):
                if self.cancelled:
                    self.signals.status.emit("Installation cancelled.", 0, "")
                    return
                self.signals.status.emit(label, int(i / total * 100), "")
                if not self._run_step(step_id):
                    return

            self.signals.status.emit("Installation complete!", 100, "")
            self._save_python_path()
            self.signals.done.emit()

        except Exception as e:
            self.signals.status.emit(f"Unexpected error: {e}", 0, "")
            self.signals.error.emit("Error", str(e))
        finally:
            self.installing = False
            self.install_btn.setEnabled(True)

    def _run_step(self, step_id):
        return {
            "download_python":    self._download_python,
            "install_python":     self._install_python,
            "install_base":       lambda: self._install_packages("requirements-base.txt"),
            "install_gpu":        lambda: self._install_packages("requirements-gpu.txt"),
            "create_launcher":    self._create_launcher,
            "create_uninstaller": self._create_uninstaller,
            "create_shortcut":    self._create_shortcut,
        }.get(step_id, lambda: False)()

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _download_python(self):
        try:
            self.signals.detail.emit("Connecting to python.org…")
            path = os.path.join(tempfile.gettempdir(), "python_installer.exe")

            def hook(block, bsize, total):
                if total > 0:
                    self.signals.detail.emit(
                        f"Downloading Python: {min(100, block*bsize*100//total)}%")

            urllib.request.urlretrieve(self.PYTHON_URL, path, hook)
            self.python_installer_path = path
            return True
        except Exception as e:
            self.signals.error.emit("Download Error",
                f"Could not download Python:\n{e}\n\n"
                "Please install manually from python.org")
            return False

    def _install_python(self):
        try:
            self.signals.detail.emit("Running Python installer silently…")
            result = subprocess.run([
                self.python_installer_path,
                "/quiet", "InstallAllUsers=0",
                "PrependPath=1", "Include_pip=1", "Include_test=0"
            ], timeout=300)
            if result.returncode == 0:
                self.python_path = self._find_python()
                if self.python_path:
                    return True
            self.signals.error.emit("Python Install Failed",
                "The Python installer did not complete successfully.\n"
                "Please install Python 3.11 manually from python.org then re-run setup.")
            return False
        except Exception as e:
            self.signals.error.emit("Error", str(e))
            return False

    def _install_packages(self, filename):
        req_path = self.requirements_dir / filename
        if not req_path.exists():
            self.signals.error.emit("File Missing",
                f"Requirements file not found:\n{req_path}\n\nPlease reinstall Apollova.")
            return False

        python = self.python_path or "python"
        cmd    = [python, "-m", "pip", "install", "--upgrade", "-r", str(req_path)]
        if "gpu" in filename:
            cmd += ["--extra-index-url", "https://download.pytorch.org/whl/cu118"]

        try:
            flags   = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=flags)
            lines = []
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.strip()
                    lines.append(line)
                    if any(k in line for k in
                           ("Collecting", "Installing", "Successfully", "already")):
                        self.signals.detail.emit(line[:72])
            process.wait(timeout=1800)
            if process.returncode != 0:
                tail = "\n".join(lines[-12:])
                self.signals.error.emit("Install Failed",
                    f"pip failed for {filename}.\n\nLast output:\n{tail}")
                return False
            return True
        except Exception as e:
            self.signals.error.emit("Error", str(e))
            return False

    def _create_launcher(self):
        try:
            python = self.python_path or "python"
            bat    = self.install_dir / "Apollova.bat"
            bat.write_text(
                "@echo off\n"
                "cd /d \"%~dp0\"\n"
                f"\"{python}\" \"assets\\apollova_gui.py\"\n"
                "if errorlevel 1 (\n"
                "    echo.\n"
                "    echo Apollova encountered an error.\n"
                "    echo Check that all packages are installed and try again.\n"
                "    pause >nul\n"
                ")\n",
                encoding='utf-8')
            self.signals.detail.emit("Created: Apollova.bat")
            return True
        except Exception as e:
            self.signals.detail.emit(f"Launcher error: {e}")
            return False

    def _create_uninstaller(self):
        try:
            python   = self.python_path or "python"
            packages = []
            for fname in ("requirements-base.txt", "requirements-gpu.txt"):
                fpath = self.requirements_dir / fname
                if not fpath.exists():
                    continue
                for line in fpath.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if not line or line.startswith('#') or line.startswith('--'):
                        continue
                    pkg = line.split('==')[0].split('>=')[0].split('<=')[0].split('[')[0].strip()
                    if pkg and pkg not in packages:
                        packages.append(pkg)

            pkg_list = " ".join(packages)
            bat = self.install_dir / "Uninstall.bat"
            bat.write_text(
                "@echo off\n"
                "echo ================================================\n"
                "echo   Apollova Uninstaller\n"
                "echo ================================================\n"
                "echo.\n"
                "echo This removes all Apollova Python packages.\n"
                "echo Your templates, audio and job folders are NOT deleted.\n"
                "echo.\n"
                f"echo Packages: {pkg_list}\n"
                "echo.\n"
                "set /p confirm=\"Continue? (Y/N): \"\n"
                "if /i not \"%confirm%\"==\"Y\" (\n"
                "    echo Cancelled.\n"
                "    pause\n"
                "    exit /b\n"
                ")\n"
                "echo.\n"
                "echo Uninstalling...\n"
                f"\"{python}\" -m pip uninstall -y {pkg_list}\n"
                "echo.\n"
                "echo ================================================\n"
                "echo   Done. You can now delete the Apollova folder.\n"
                "echo ================================================\n"
                "echo.\n"
                "pause\n",
                encoding='utf-8')
            self.signals.detail.emit("Created: Uninstall.bat")
            return True
        except Exception as e:
            self.signals.detail.emit(f"Uninstaller error: {e}")
            return False

    def _create_shortcut(self):
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = winreg.QueryValueEx(key, "Desktop")[0]
            winreg.CloseKey(key)

            # Prefer Apollova.exe, fall back to Apollova.bat
            exe    = self.install_dir / "Apollova.exe"
            bat    = self.install_dir / "Apollova.bat"
            target = exe if exe.exists() else bat
            icon   = self.assets_dir / "icon.ico"
            if not icon.exists():
                icon = self.install_dir / "icon.ico"
            lnk  = os.path.join(desktop, "Apollova.lnk")
            ps   = (f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");' +
                    f'$s.TargetPath="{target}";' +
                    f'$s.WorkingDirectory="{self.install_dir}";'
                    )
            if icon.exists():
                ps += f'$s.IconLocation="{icon}";'
            ps += '$s.Save()'
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW
                           if sys.platform == 'win32' else 0)
            self.signals.detail.emit("Desktop shortcut created.")
            return True
        except Exception as e:
            self.signals.detail.emit(f"Shortcut skipped ({e}) — not fatal.")
            return True  # non-fatal

    def _save_python_path(self):
        """Save python_path to settings.json so Apollova.exe and Uninstall.exe can find it."""
        import json
        try:
            sf   = self.install_dir / "settings.json"
            data = {}
            if sf.exists():
                try:
                    data = json.loads(sf.read_text())
                except Exception:
                    pass
            if self.python_path:
                data['python_path'] = self.python_path
            sf.write_text(json.dumps(data, indent=2))
        except Exception as e:
            self.signals.detail.emit(f"Could not save settings: {e}")

        # ── Signal handlers (main thread) ────────────────────────────────────────

    def _on_status(self, status, progress, detail):
        self.status_lbl.setText(status)
        self.progress_bar.setValue(progress)
        if detail:
            self.detail_lbl.setText(detail)

    def _on_detail(self, detail):
        self.detail_lbl.setText(detail)

    def _on_error(self, title, message):
        QMessageBox.critical(self, title, message)

    # ── Completion dialog ─────────────────────────────────────────────────────

    def _show_complete_dialog(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Setup Complete")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText("<b>Installation Complete!</b>")
        dlg.setInformativeText(
            "All dependencies installed successfully.\n\n"
            "HOW TO RUN APOLLOVA:\n"
            "Double-click  Apollova.bat  in this folder,\n"
            "or use the desktop shortcut if you created one.\n\n"
            "FIRST-RUN NOTE:\n"
            "When you first generate a job, Whisper will download\n"
            "the transcription model you selected:\n\n"
            "  tiny   ~75 MB      small  ~460 MB\n"
            "  base   ~140 MB     medium ~1.5 GB"
        )
        dlg.setStandardButtons(QMessageBox.StandardButton.Close)
        dlg.exec()
        self.close()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova Setup")
    app.setStyleSheet(STYLE)
    win = SetupWizard()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
