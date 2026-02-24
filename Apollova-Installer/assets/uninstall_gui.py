"""
Apollova Uninstaller — PyQt6 GUI
Same dark aesthetic as Setup.exe. Removes all pip packages,
optionally deletes user data folders.
"""

import sys
import os
import subprocess
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QFrame,
    QMessageBox, QGroupBox, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# ── Stylesheet (matches Setup) ────────────────────────────────────────────────
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
QPushButton#danger {
    background: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    font-size: 14px;
    padding: 10px 28px;
}
QPushButton#danger:hover { background: #eba0ac; }
QPushButton#danger:disabled { background: #313244; color: #585b70; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 12px;
    text-align: center;
    color: #1e1e2e;
}
QProgressBar::chunk { background: #f38ba8; border-radius: 4px; }
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


class UninstallSignals(QObject):
    status  = pyqtSignal(str, int, str)
    detail  = pyqtSignal(str)
    done    = pyqtSignal(bool)          # success
    error   = pyqtSignal(str, str)


class UninstallWizard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apollova Uninstaller")
        self.resize(560, 580)
        self.setMinimumSize(500, 480)
        self.setMaximumWidth(700)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 560) // 2, (screen.height() - 580) // 2)

        if getattr(sys, 'frozen', False):
            self.install_dir = Path(sys.executable).parent
        else:
            self.install_dir = Path(__file__).parent

        self.assets_dir       = self.install_dir / "assets"
        self.requirements_dir = self.assets_dir  / "requirements"

        icon_path = self.assets_dir / "icon.ico"
        if not icon_path.exists():
            icon_path = self.install_dir / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.uninstalling = False
        self.cancelled    = False
        self.python_path  = self._find_python()

        self.signals = UninstallSignals()
        self.signals.status.connect(self._on_status)
        self.signals.detail.connect(lambda t: self.detail_lbl.setText(t))
        self.signals.done.connect(self._on_done)
        self.signals.error.connect(lambda t, m: QMessageBox.critical(self, t, m))

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout  = QVBoxLayout(content)
        layout.setContentsMargins(28, 22, 28, 10)
        layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Title
        title = QLabel("Apollova")
        f = QFont("Segoe UI")
        f.setPointSize(18)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        title.setStyleSheet("color:#f38ba8;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("Uninstaller")
        sub.setStyleSheet("color:#6c7086; font-size:12px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#313244;")
        layout.addWidget(sep)

        # Python status
        py_grp = QGroupBox("Python")
        py_lay = QVBoxLayout(py_grp)
        if self.python_path:
            v   = self._get_python_version(self.python_path)
            lbl = QLabel(f"  ✓ Python {v} found — packages will be removed")
            lbl.setStyleSheet("color:#a6e3a1;")
        else:
            lbl = QLabel("  ✗ Python not found — pip packages cannot be removed")
            lbl.setStyleSheet("color:#f38ba8;")
        py_lay.addWidget(lbl)
        layout.addWidget(py_grp)

        # What will be removed
        remove_grp = QGroupBox("What will be removed")
        remove_lay = QVBoxLayout(remove_grp)

        self.pkgs_chk = QCheckBox("Uninstall all Apollova Python packages  (mandatory)")
        self.pkgs_chk.setChecked(True)
        self.pkgs_chk.setEnabled(False)
        remove_lay.addWidget(self.pkgs_chk)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#313244;")
        remove_lay.addWidget(sep2)

        self.jobs_chk = QCheckBox("Delete all job folders  (Aurora, Mono, Onyx)")
        self.jobs_chk.setChecked(False)
        remove_lay.addWidget(self.jobs_chk)

        jobs_info = QLabel(
            "    Deletes all generated job folders and their audio/lyric files.\n"
            "    Your After Effects templates and database are NOT affected.")
        jobs_info.setStyleSheet("color:#6c7086; font-size:11px;")
        remove_lay.addWidget(jobs_info)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color:#313244;")
        remove_lay.addWidget(sep3)

        self.db_chk = QCheckBox("Delete database  (removes all cached song data)")
        self.db_chk.setChecked(False)
        remove_lay.addWidget(self.db_chk)

        db_info = QLabel(
            "    Permanently deletes songs.db — all cached lyrics,\n"
            "    transcriptions, and use counts will be lost.")
        db_info.setStyleSheet("color:#6c7086; font-size:11px;")
        remove_lay.addWidget(db_info)

        layout.addWidget(remove_grp)

        # What is kept
        keep_grp = QGroupBox("What is kept")
        keep_lay = QVBoxLayout(keep_grp)
        keep_lbl = QLabel(
            "  • After Effects template files (.aep)\n"
            "  • This installer folder and its contents\n"
            "  • Your settings.json\n"
            "  • Whisper model cache (in whisper_models/)")
        keep_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        keep_lay.addWidget(keep_lbl)
        layout.addWidget(keep_grp)

        # Progress
        prog_grp = QGroupBox("Progress")
        prog_lay = QVBoxLayout(prog_grp)
        self.status_lbl = QLabel("Ready to uninstall.")
        prog_lay.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        prog_lay.addWidget(self.progress_bar)
        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color:#6c7086; font-size:11px;")
        prog_lay.addWidget(self.detail_lbl)
        layout.addWidget(prog_grp)
        layout.addStretch()

        # Buttons
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

        self.uninstall_btn = QPushButton("Uninstall")
        self.uninstall_btn.setObjectName("danger")
        self.uninstall_btn.setFixedWidth(130)
        self.uninstall_btn.clicked.connect(self._start_uninstall)
        btn_row.addWidget(self.uninstall_btn)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_row)
        outer.addWidget(btn_widget)

    # ── Python detection ──────────────────────────────────────────────────────

    def _find_python(self):
        import json
        # Check settings first
        sf = self.install_dir / "settings.json" if hasattr(self, 'install_dir') else None
        if sf and sf.exists():
            try:
                p = json.loads(sf.read_text()).get("python_path")
                if p and Path(p).exists() and self._is_valid_python(p):
                    return p
            except Exception:
                pass

        candidates = [
            "python",
            r"C:\Program Files\Python311\python.exe",
            r"C:\Program Files\Python312\python.exe",
            r"C:\Program Files\Python313\python.exe",
            r"C:\Python311\python.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
        ]
        for c in candidates:
            if self._is_valid_python(c):
                return c
        return None

    def _is_valid_python(self, path):
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(
                [path, "-c", "import sys; v=sys.version_info; print(v.major,v.minor)"],
                capture_output=True, text=True, timeout=5, creationflags=flags)
            if r.returncode == 0:
                parts = r.stdout.strip().split()
                return len(parts) == 2 and int(parts[0]) == 3 and int(parts[1]) >= 10
        except Exception:
            pass
        return False

    def _get_python_version(self, path):
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run([path, "--version"], capture_output=True,
                               text=True, timeout=5, creationflags=flags)
            return (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
        except Exception:
            return "Unknown"

    # ── Uninstall flow ────────────────────────────────────────────────────────

    def _cancel(self):
        if self.uninstalling:
            self.cancelled = True
            self.status_lbl.setText("Cancelling…")
        else:
            self.close()

    def _start_uninstall(self):
        if self.uninstalling:
            return

        reply = QMessageBox.question(
            self, "Confirm Uninstall",
            "This will remove all Apollova Python packages.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.uninstalling = True
        self.cancelled    = False
        self.uninstall_btn.setEnabled(False)
        threading.Thread(target=self._uninstall_thread, daemon=True).start()

    def _uninstall_thread(self):
        try:
            steps = [("remove_packages", "Removing Python packages…")]
            if self.jobs_chk.isChecked():
                steps.append(("delete_jobs", "Deleting job folders…"))
            if self.db_chk.isChecked():
                steps.append(("delete_database", "Deleting database…"))

            total = len(steps)
            for i, (step_id, label) in enumerate(steps):
                if self.cancelled:
                    self.signals.status.emit("Cancelled.", 0, "")
                    return
                self.signals.status.emit(label, int(i / total * 100), "")
                self._run_step(step_id)

            self.signals.status.emit("Uninstall complete.", 100, "")
            self.signals.done.emit(True)

        except Exception as e:
            self.signals.status.emit(f"Error: {e}", 0, "")
            self.signals.error.emit("Error", str(e))
        finally:
            self.uninstalling = False
            self.uninstall_btn.setEnabled(True)

    def _run_step(self, step_id):
        {
            "remove_packages": self._remove_packages,
            "delete_jobs":     self._delete_jobs,
            "delete_database": self._delete_database,
        }.get(step_id, lambda: None)()

    def _remove_packages(self):
        if not self.python_path:
            self.signals.detail.emit("Python not found — skipping pip uninstall")
            return

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

        if not packages:
            self.signals.detail.emit("No packages found in requirements files")
            return

        self.signals.detail.emit(f"Removing {len(packages)} packages…")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd   = [self.python_path, "-m", "pip", "uninstall", "-y"] + packages
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=flags)
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.strip()
                    if "Successfully" in line or "Uninstalling" in line:
                        self.signals.detail.emit(line[:72])
            process.wait(timeout=300)
        except Exception as e:
            self.signals.detail.emit(f"pip error: {e}")

    def _delete_jobs(self):
        import shutil
        job_dirs = [
            self.install_dir / "Apollova-Aurora" / "jobs",
            self.install_dir / "Apollova-Mono"   / "jobs",
            self.install_dir / "Apollova-Onyx"   / "jobs",
        ]
        for d in job_dirs:
            if d.exists():
                self.signals.detail.emit(f"Deleting {d.name}…")
                try:
                    shutil.rmtree(d)
                    d.mkdir(parents=True, exist_ok=True)  # recreate empty
                except Exception as e:
                    self.signals.detail.emit(f"Error deleting {d}: {e}")
        self.signals.detail.emit("Job folders cleared.")

    def _delete_database(self):
        import shutil
        db = self.install_dir / "database" / "songs.db"
        if db.exists():
            try:
                db.unlink()
                self.signals.detail.emit("Database deleted.")
            except Exception as e:
                self.signals.detail.emit(f"Error deleting database: {e}")
        else:
            self.signals.detail.emit("No database found.")

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_status(self, status, progress, detail):
        self.status_lbl.setText(status)
        self.progress_bar.setValue(progress)
        if detail:
            self.detail_lbl.setText(detail)

    def _on_done(self, success):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Uninstall Complete")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText("Uninstall Complete")
        dlg.setInformativeText(
            "All selected items have been removed.\n\n"
            "You can now delete the Apollova folder to finish removing everything.\n\n"
            "Thank you for using Apollova.")
        dlg.setStandardButtons(QMessageBox.StandardButton.Close)
        dlg.exec()
        self.close()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova Uninstaller")
    app.setStyleSheet(STYLE)
    win = UninstallWizard()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
