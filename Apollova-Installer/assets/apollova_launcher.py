"""
Apollova.exe — Main application launcher
Tiny entry point: resolves paths and launches apollova_gui.py via Python.
No tkinter, no Tcl. Just a subprocess call so PyInstaller only needs to
bundle this small file, not the entire app + its heavy dependencies.
"""

import sys
import os
import subprocess
from pathlib import Path


def main():
    if getattr(sys, 'frozen', False):
        root = Path(sys.executable).parent
    else:
        root = Path(__file__).parent

    gui = root / "assets" / "apollova_gui.py"

    if not gui.exists():
        # Show a minimal error without tkinter
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Apollova — Error",
                f"Application files not found.\n\nExpected:\n{gui}\n\n"
                "Please reinstall Apollova.")
        except Exception:
            pass
        sys.exit(1)

    # Find Python: prefer the one that installed Apollova's packages
    python = _find_python(root)
    if not python:
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Apollova — Error",
                "Python 3.10+ not found.\n\nPlease run Setup.exe to install dependencies.")
        except Exception:
            pass
        sys.exit(1)

    # Launch the app — not recursive because we're calling python.exe directly
    os.chdir(str(root / "assets"))
    result = subprocess.run([python, str(gui)])
    sys.exit(result.returncode)


def _find_python(root):
    """Find Python 3.10+, checking the settings file first."""
    import json

    # 1. Check saved settings (from Setup wizard)
    settings_file = root / "settings.json"
    if settings_file.exists():
        try:
            s = json.loads(settings_file.read_text())
            p = s.get("python_path")
            if p and Path(p).exists() and _is_valid_python(p):
                return p
        except Exception:
            pass

    # 2. Common locations
    candidates = [
        "python",
        r"C:\Program Files\Python311\python.exe",
        r"C:\Program Files\Python312\python.exe",
        r"C:\Program Files\Python313\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python312\python.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python313\python.exe"),
    ]
    for c in candidates:
        if _is_valid_python(c):
            return c
    return None


def _is_valid_python(path):
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(
            [path, "-c", "import sys; v=sys.version_info; print(v.major,v.minor)"],
            capture_output=True, text=True, timeout=5, creationflags=flags)
        if r.returncode == 0:
            parts = r.stdout.strip().split()
            if len(parts) == 2:
                return int(parts[0]) == 3 and int(parts[1]) >= 10
    except Exception:
        pass
    return False


if __name__ == "__main__":
    main()
