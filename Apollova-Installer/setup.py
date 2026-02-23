"""
Apollova Setup Wizard
Installs required dependencies for Apollova
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import os
import threading
import urllib.request
import tempfile
from pathlib import Path


class SetupWizard:
    PYTHON_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    PYTHON_INSTALLER_SIZE = "~25MB"

    def __init__(self, root):
        self.root = root
        self.root.title("Apollova Setup")
        self.root.geometry("560x640")
        self.root.minsize(520, 520)
        self.root.resizable(True, True)

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 560) // 2
        y = (self.root.winfo_screenheight() - 640) // 2
        self.root.geometry(f"560x640+{x}+{y}")

        if getattr(sys, 'frozen', False):
            self.install_dir = Path(sys.executable).parent
        else:
            self.install_dir = Path(__file__).parent

        self.assets_dir = self.install_dir / "assets"
        self.requirements_dir = self.assets_dir / "requirements"

        self.installing = False
        self.cancelled = False
        self.python_path = None
        self.python_installer_path = None

        self._setup_styles()
        self._create_ui()
        self._check_python()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Segoe UI', 18, 'bold'))
        style.configure('Subtitle.TLabel', font=('Segoe UI', 9), foreground='#666666')
        style.configure('Install.TButton', font=('Segoe UI', 10, 'bold'), padding=(20, 8))

    def _create_ui(self):
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)

        self.main = ttk.Frame(canvas, padding="25")
        canvas_window = canvas.create_window((0, 0), window=self.main, anchor="nw")

        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.main.bind("<Configure>", configure_scroll)

        def configure_canvas(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", configure_canvas)

        canvas.configure(yscrollcommand=scrollbar.set)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Title
        ttk.Label(self.main, text="Apollova", style='Title.TLabel').pack(pady=(0, 3))
        ttk.Label(self.main, text="Setup & Dependency Installer",
                  style='Subtitle.TLabel').pack(pady=(0, 18))
        ttk.Separator(self.main, orient='horizontal').pack(fill=tk.X, pady=(0, 18))

        # Python status
        py_frame = ttk.LabelFrame(self.main, text="Python", padding="12")
        py_frame.pack(fill=tk.X, pady=(0, 12))

        self.python_status = ttk.Label(py_frame, text="Checking...", font=('Segoe UI', 9))
        self.python_status.pack(anchor=tk.W)

        self.install_python_var = tk.BooleanVar(value=False)
        self.install_python_check = ttk.Checkbutton(
            py_frame,
            text=f"Download and install Python 3.11 for me  ({self.PYTHON_INSTALLER_SIZE})",
            variable=self.install_python_var,
            state='disabled'
        )
        self.install_python_check.pack(anchor=tk.W, pady=(6, 0))

        # Options
        opt_frame = ttk.LabelFrame(self.main, text="Installation Options", padding="12")
        opt_frame.pack(fill=tk.X, pady=(0, 12))

        self.base_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame,
                        text="Install required packages  (mandatory)",
                        variable=self.base_var,
                        state='disabled').pack(anchor=tk.W)

        ttk.Separator(opt_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        self.gpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame,
                        text="Enable GPU Acceleration  (optional)",
                        variable=self.gpu_var).pack(anchor=tk.W)
        ttk.Label(opt_frame,
                  text="    Requires an NVIDIA GPU with CUDA support.\n"
                       "    Adds ~1.5 GB and significantly speeds up transcription.",
                  font=('Segoe UI', 8), foreground='#888888').pack(anchor=tk.W, pady=(2, 0))

        ttk.Separator(opt_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        self.shortcut_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame,
                        text="Create desktop shortcut",
                        variable=self.shortcut_var).pack(anchor=tk.W)

        # Progress
        prog_frame = ttk.LabelFrame(self.main, text="Progress", padding="12")
        prog_frame.pack(fill=tk.X, pady=(0, 12))

        self.status_var = tk.StringVar(value="Ready to install.")
        ttk.Label(prog_frame, textvariable=self.status_var,
                  font=('Segoe UI', 9)).pack(anchor=tk.W)

        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(prog_frame, variable=self.progress_var,
                        maximum=100).pack(fill=tk.X, pady=(8, 4))

        self.detail_var = tk.StringVar(value="")
        ttk.Label(prog_frame, textvariable=self.detail_var,
                  font=('Segoe UI', 8), foreground='#888888').pack(anchor=tk.W)

        # Buttons — always visible at bottom
        ttk.Separator(self.main, orient='horizontal').pack(fill=tk.X, pady=(10, 16))
        btn_row = ttk.Frame(self.main)
        btn_row.pack(fill=tk.X)

        self.cancel_btn = ttk.Button(btn_row, text="Cancel",
                                     command=self._cancel, width=12)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.install_btn = ttk.Button(btn_row, text="Install",
                                      command=self._start_install,
                                      style='Install.TButton', width=14)
        self.install_btn.pack(side=tk.RIGHT)

    # ── Python detection ──────────────────────────────────────

    def _check_python(self):
        self.python_path = self._find_python()
        if self.python_path:
            v = self._get_python_version(self.python_path)
            self.python_status.config(text=f"  Python {v} found", foreground='#16a34a')
            self.install_python_check.config(state='disabled')
            self.install_python_var.set(False)
        else:
            self.python_status.config(text="  Python 3.10+ not found", foreground='#dc2626')
            self.install_python_check.config(state='normal')
            self.install_python_var.set(True)

    def _find_python(self):
        """Find a Python 3.10+ executable."""
        candidates = [
            "python", "python3",
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python310\python.exe"),
        ]
        for path in candidates:
            try:
                result = subprocess.run(
                    [path, "-c",
                     "import sys; v=sys.version_info; print(v.major, v.minor)"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split()
                    major, minor = int(parts[0]), int(parts[1])
                    if major == 3 and minor >= 10:
                        return path
            except Exception:
                continue
        return None

    def _get_python_version(self, python_path):
        try:
            r = subprocess.run(
                [python_path, "--version"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            return (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
        except Exception:
            return "Unknown"

    # ── Install flow ──────────────────────────────────────────

    def _cancel(self):
        if self.installing:
            self.cancelled = True
            self.status_var.set("Cancelling...")
        else:
            self.root.quit()

    def _start_install(self):
        if self.installing:
            return
        if not self.python_path and not self.install_python_var.get():
            messagebox.showerror(
                "Python Required",
                "Python 3.10+ is required to run Apollova.\n\n"
                "Check 'Download and install Python' above,\n"
                "or install it manually from python.org then re-run setup."
            )
            return
        self.installing = True
        self.cancelled = False
        self.install_btn.config(state='disabled')
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        try:
            steps = []
            if not self.python_path and self.install_python_var.get():
                steps += [
                    ("download_python", "Downloading Python 3.11..."),
                    ("install_python",  "Installing Python 3.11..."),
                ]
            steps.append(("install_base", "Installing required packages..."))
            if self.gpu_var.get():
                steps.append(("install_gpu", "Installing GPU packages (PyTorch ~1.5 GB)..."))
            steps += [
                ("create_launcher",    "Creating launcher..."),
                ("create_uninstaller", "Creating uninstaller..."),
            ]
            if self.shortcut_var.get():
                steps.append(("create_shortcut", "Creating desktop shortcut..."))

            total = len(steps)
            for i, (step_id, label) in enumerate(steps):
                if self.cancelled:
                    self._update_status("Installation cancelled.", 0, "")
                    return
                self._update_status(label, int(i / total * 100), "")
                if not self._run_step(step_id):
                    return  # step already showed error dialog

            self._update_status("Installation complete!", 100, "")
            self.root.after(0, self._show_complete_dialog)

        except Exception as e:
            self._update_status(f"Unexpected error: {e}", 0, "")
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.installing = False
            self.root.after(0, lambda: self.install_btn.config(state='normal'))

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

    # ── Steps ─────────────────────────────────────────────────

    def _download_python(self):
        try:
            self._update_detail("Connecting to python.org...")
            path = os.path.join(tempfile.gettempdir(), "python_installer.exe")

            def hook(block, bsize, total):
                if total > 0:
                    self._update_detail(
                        f"Downloading Python: {min(100, block*bsize*100//total)}%"
                    )

            urllib.request.urlretrieve(self.PYTHON_URL, path, hook)
            self.python_installer_path = path
            return True
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                "Download Error",
                f"Could not download Python:\n{e}\n\nPlease install manually from python.org"
            ))
            return False

    def _install_python(self):
        try:
            self._update_detail("Running Python installer silently...")
            result = subprocess.run([
                self.python_installer_path,
                "/quiet", "InstallAllUsers=0",
                "PrependPath=1", "Include_pip=1", "Include_test=0"
            ], timeout=300)
            if result.returncode == 0:
                self.python_path = self._find_python()
                if self.python_path:
                    return True
            self.root.after(0, lambda: messagebox.showerror(
                "Python Install Failed",
                "The Python installer did not complete successfully.\n"
                "Please install Python 3.11 manually from python.org then re-run setup."
            ))
            return False
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            return False

    def _install_packages(self, filename):
        req_path = self.requirements_dir / filename
        if not req_path.exists():
            self.root.after(0, lambda: messagebox.showerror(
                "File Missing",
                f"Requirements file not found:\n{req_path}\n\nPlease reinstall Apollova."
            ))
            return False

        python = self.python_path or "python"
        cmd = [python, "-m", "pip", "install", "--upgrade", "-r", str(req_path)]
        if "gpu" in filename:
            cmd += ["--extra-index-url", "https://download.pytorch.org/whl/cu118"]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            output_lines = []
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.strip()
                    output_lines.append(line)
                    if any(k in line for k in ("Collecting", "Installing", "Successfully", "already")):
                        self._update_detail(line[:72])

            process.wait(timeout=1800)

            if process.returncode != 0:
                tail = "\n".join(output_lines[-12:])
                self.root.after(0, lambda t=tail: messagebox.showerror(
                    "Install Failed",
                    f"pip failed for {filename}.\n\nLast output:\n{t}"
                ))
                return False
            return True

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            return False

    def _create_launcher(self):
        """
        Creates Apollova.bat — a simple batch file launcher.
        This CANNOT recurse because it just calls python.exe directly.
        No PyInstaller, no sys.executable tricks.
        """
        try:
            python = self.python_path or "python"
            bat = self.install_dir / "Apollova.bat"
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
                encoding='utf-8'
            )
            self._update_detail("Created: Apollova.bat")
            return True
        except Exception as e:
            self._update_detail(f"Launcher error: {e}")
            return False

    def _create_uninstaller(self):
        """Creates Uninstall.bat that removes all installed pip packages."""
        try:
            python = self.python_path or "python"

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
                f"echo Packages to remove: {pkg_list}\n"
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
                encoding='utf-8'
            )
            self._update_detail("Created: Uninstall.bat")
            return True
        except Exception as e:
            self._update_detail(f"Uninstaller error: {e}")
            return False

    def _create_shortcut(self):
        """Creates a desktop shortcut pointing to Apollova.bat."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            desktop = winreg.QueryValueEx(key, "Desktop")[0]
            winreg.CloseKey(key)

            bat  = self.install_dir / "Apollova.bat"
            icon = self.assets_dir / "icon.ico"
            lnk  = os.path.join(desktop, "Apollova.lnk")

            ps = (
                f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
                f'$s.TargetPath="{bat}";'
                f'$s.WorkingDirectory="{self.install_dir}";'
            )
            if icon.exists():
                ps += f'$s.IconLocation="{icon}";'
            ps += '$s.Save()'

            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self._update_detail("Desktop shortcut created.")
            return True
        except Exception as e:
            self._update_detail(f"Shortcut skipped ({e}) — not fatal.")
            return True  # Non-fatal

    # ── UI helpers ────────────────────────────────────────────

    def _update_status(self, status, progress, detail):
        self.root.after(0, lambda: self.status_var.set(status))
        self.root.after(0, lambda: self.progress_var.set(progress))
        self.root.after(0, lambda: self.detail_var.set(detail))

    def _update_detail(self, detail):
        self.root.after(0, lambda: self.detail_var.set(detail))

    # ── Completion dialog ─────────────────────────────────────

    def _show_complete_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Setup Complete")
        win.geometry("460x430")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        win.update_idletasks()
        x = (win.winfo_screenwidth()  - 460) // 2
        y = (win.winfo_screenheight() - 430) // 2
        win.geometry(f"460x430+{x}+{y}")

        f = ttk.Frame(win, padding="24")
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Installation Complete",
                  font=('Segoe UI', 15, 'bold'),
                  foreground='#16a34a').pack(pady=(0, 4))
        ttk.Label(f, text="All dependencies installed successfully.",
                  font=('Segoe UI', 9), foreground='#555').pack(pady=(0, 14))
        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=(0, 14))

        run_frame = ttk.LabelFrame(f, text="How to Run", padding="10")
        run_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(run_frame,
                  text="Double-click  Apollova.bat  in this folder,\n"
                       "or use the desktop shortcut if you created one.",
                  font=('Segoe UI', 9)).pack(anchor=tk.W)

        note_frame = ttk.LabelFrame(f, text="First-Run Note", padding="10")
        note_frame.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(note_frame,
                  text="When you first generate a job, Whisper will download\n"
                       "the transcription model you selected.\n\n"
                       "  tiny  ~75 MB     small  ~460 MB\n"
                       "  base  ~140 MB    medium ~1.5 GB",
                  font=('Segoe UI', 9), justify=tk.LEFT).pack(anchor=tk.W)

        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=(0, 14))

        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X)

        def launch():
            win.destroy()
            self.root.quit()
            bat = self.install_dir / "Apollova.bat"
            if bat.exists():
                os.startfile(str(bat))

        def close():
            win.destroy()
            self.root.quit()

        ttk.Button(btn_row, text="Launch Apollova", command=launch, width=16).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Close",           command=close,  width=12).pack(side=tk.RIGHT)


def main():
    root = tk.Tk()
    SetupWizard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
