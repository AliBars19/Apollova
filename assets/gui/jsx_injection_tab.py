"""JSX Injection tab — unified project injection and render."""

import shutil
import subprocess
import sys
import tempfile
import time
import threading
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QMessageBox,
)

from assets.gui.constants import (
    INSTALL_DIR, ASSETS_DIR, BUNDLED_JSX_DIR,
    UNIFIED_TEMPLATE_PATH, UNIFIED_JSX_SCRIPT,
    JOBS_DIRS,
)
from assets.gui.helpers import _label, _set_label_style, _scrollable


def build(app) -> None:
    """Build the JSX Injection tab. Sets all widgets on *app*."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)

    # Status
    status_grp = QGroupBox("Unified Project Status")
    status_lay = QVBoxLayout(status_grp)

    def status_row(label_text: str) -> QLabel:
        row = QHBoxLayout()
        lbl_key = QLabel(label_text)
        lbl_key.setFixedWidth(130)
        lbl_val = QLabel("Checking...")
        row.addWidget(lbl_key)
        row.addWidget(lbl_val)
        row.addStretch()
        status_lay.addLayout(row)
        return lbl_val

    app.inject_jobs_label = status_row("Jobs:")
    app.inject_template_label = status_row("Unified Project:")
    app.inject_ae_label = status_row("After Effects:")

    ref_row = QHBoxLayout()
    ref_btn = QPushButton("\U0001f504  Refresh Status")
    ref_btn.setObjectName("muted")
    ref_btn.clicked.connect(app._update_inject_status)
    ref_row.addWidget(ref_btn)
    ref_row.addStretch()
    status_lay.addLayout(ref_row)

    install_lbl = _label(f"Install Dir: {INSTALL_DIR}", "muted")
    status_lay.addWidget(install_lbl)
    layout.addWidget(status_grp)

    btn_row = QHBoxLayout()
    app.inject_btn = QPushButton("Inject Only")
    app.inject_btn.setObjectName("primary")
    app.inject_btn.setToolTip("Open After Effects, inject jobs into unified project, save and exit")
    app.inject_btn.clicked.connect(app._run_injection)
    btn_row.addWidget(app.inject_btn)

    app.single_render_btn = QPushButton("Inject & Render")
    app.single_render_btn.setObjectName("primary")
    app.single_render_btn.setToolTip(
        "Inject all jobs into unified project then render via aerender.exe (one job at a time)")
    app.single_render_btn.clicked.connect(app._start_single_render)
    btn_row.addWidget(app.single_render_btn)

    app.single_render_cancel_btn = QPushButton("✕  Cancel Render")
    app.single_render_cancel_btn.setObjectName("muted")
    app.single_render_cancel_btn.setEnabled(False)
    app.single_render_cancel_btn.clicked.connect(app._cancel_single_render)
    btn_row.addWidget(app.single_render_cancel_btn)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    app.single_render_status_label = QLabel("Render: Idle")
    layout.addWidget(app.single_render_status_label)
    app.single_render_progress_bar = QProgressBar()
    app.single_render_progress_bar.setRange(0, 100)
    app.single_render_progress_bar.setFormat("Render: %p%")
    app.single_render_progress_bar.setValue(0)
    layout.addWidget(app.single_render_progress_bar)

    layout.addStretch()

    app.tabs.addTab(_scrollable(page), "  \U0001f680 JSX Injection  ")
    app._update_inject_status()


# ── Inject helpers ────────────────────────────────────────────────────────────

def update_inject_status(app) -> None:
    """Refresh status labels and enable/disable action buttons."""
    jobs_ok = template_ok = ae_ok = False

    # Count jobs across all 3 template dirs
    total_jobs = 0
    for t in ["aurora", "mono", "onyx"]:
        d = JOBS_DIRS.get(t)
        if d and d.exists():
            total_jobs += len(list(d.glob("job_*")))

    if total_jobs > 0:
        app.inject_jobs_label.setText(
            f"✓ {total_jobs} job(s) across Aurora / Mono / Onyx")
        _set_label_style(app.inject_jobs_label, "success")
        jobs_ok = True
    else:
        app.inject_jobs_label.setText("✗ No jobs found in any template dir")
        _set_label_style(app.inject_jobs_label, "error")

    if UNIFIED_TEMPLATE_PATH.exists():
        app.inject_template_label.setText(f"✓ {UNIFIED_TEMPLATE_PATH.name}")
        _set_label_style(app.inject_template_label, "success")
        template_ok = True
    else:
        app.inject_template_label.setText(
            f"✗ Not found: {UNIFIED_TEMPLATE_PATH.name}")
        _set_label_style(app.inject_template_label, "error")

    ae = app.settings.get('after_effects_path')
    if ae and Path(ae).exists():
        app.inject_ae_label.setText("✓ Found")
        _set_label_style(app.inject_ae_label, "success")
        ae_ok = True
    else:
        app.inject_ae_label.setText(
            "✗ Not configured — go to Settings")
        _set_label_style(app.inject_ae_label, "error")

    can_act = jobs_ok and template_ok and ae_ok
    app.inject_btn.setEnabled(can_act and not app.single_render_active)
    app.single_render_btn.setEnabled(can_act and not app.single_render_active)


def run_injection(app) -> None:
    """Launch After Effects with the unified JSX script (inject-only mode)."""
    ae = app.settings.get('after_effects_path')
    if app._log:
        app._log.section(
            f"JSX injection — unified project, jsx={UNIFIED_JSX_SCRIPT}")
    try:
        src = BUNDLED_JSX_DIR / UNIFIED_JSX_SCRIPT
        if not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / UNIFIED_JSX_SCRIPT
        if not src.exists():
            if app._log:
                app._log.error(f"JSX script not found: {UNIFIED_JSX_SCRIPT}")
            QMessageBox.critical(app, "Error",
                f"JSX script not found: {UNIFIED_JSX_SCRIPT}\n\nPlease reinstall.")
            return
        tmp = Path(tempfile.gettempdir()) / "Apollova"
        tmp.mkdir(exist_ok=True)
        dst = tmp / UNIFIED_JSX_SCRIPT
        shutil.copy(src, dst)
        prepare_jsx_with_path(dst, None, UNIFIED_TEMPLATE_PATH,
                              keep_open=True, jobs_dirs=JOBS_DIRS)
        if app._log:
            app._log.info(
                f"JSX prepared at {dst} | template={UNIFIED_TEMPLATE_PATH}")
    except Exception as e:
        tb = traceback.format_exc()
        if app._log:
            app._log.error(
                f"JSX preparation failed: {type(e).__name__}: {e}\n{tb}")
        QMessageBox.critical(app, "Error", f"Failed to prepare JSX:\n{e}")
        return

    ae_path = Path(ae)
    if ae_path.name.lower() != "afterfx.exe" or "adobe" not in str(ae_path).lower():
        if app._log:
            app._log.error(f"Invalid AE path rejected: {ae}")
        QMessageBox.critical(app, "Error",
            f"Invalid After Effects path:\n{ae}\n\n"
            "Expected AfterFX.exe inside an Adobe installation folder.")
        return
    try:
        flags = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)
        subprocess.Popen([ae, "-r", str(dst)], creationflags=flags)
        if app._log:
            app._log.info(f"After Effects launched: {ae}")
        QMessageBox.information(app, "Launched",
            "After Effects is launching…\n\n"
            f"Project: {UNIFIED_TEMPLATE_PATH.name}\n\n"
            "The script will open the project and inject all jobs.")
    except Exception as e:
        tb = traceback.format_exc()
        if app._log:
            app._log.error(
                f"After Effects launch failed: {type(e).__name__}: {e}\n{tb}")
        QMessageBox.critical(app, "Error",
                             f"Failed to launch After Effects:\n{e}")


# ── Single (unified) render ───────────────────────────────────────────────────

def start_single_render(app) -> None:
    """Count all jobs across all dirs and kick off the unified render thread."""
    total_jobs = 0
    for t in ["aurora", "mono", "onyx"]:
        d = JOBS_DIRS.get(t)
        if d and d.exists():
            total_jobs += len(list(d.glob("job_*")))

    if total_jobs == 0:
        QMessageBox.warning(app, "No Jobs",
            "No job directories found across Aurora / Mono / Onyx.\n"
            "Run batch generation first.")
        return

    reply = QMessageBox.question(
        app, "Confirm Render",
        f"Inject and render {total_jobs} job(s) via aerender.exe?\n\n"
        "This will take several minutes per job.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    app.single_render_active = True
    app.single_render_cancelled = False
    app.single_render_btn.setEnabled(False)
    app.single_render_cancel_btn.setEnabled(True)
    app.inject_btn.setEnabled(False)
    app.single_render_status_label.setText("Status: Starting…")
    app.single_render_progress_bar.setValue(0)
    threading.Thread(target=_single_render_worker, args=(app,), daemon=True).start()


def _single_render_worker(app) -> None:
    ok, err = run_single_template(app)
    app.signals.single_render_finished.emit(ok, err or "")


def cancel_single_render(app) -> None:
    app.single_render_cancelled = True
    app.single_render_status_label.setText("Status: Cancelling…")


def run_single_template(app) -> tuple:
    """Inject unified project then render all queued jobs one at a time."""
    ae = app.settings.get('after_effects_path')
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    aerender = _find_aerender(ae)
    if not aerender:
        return False, f"aerender.exe not found next to {ae}"

    try:
        src = BUNDLED_JSX_DIR / UNIFIED_JSX_SCRIPT
        if not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / UNIFIED_JSX_SCRIPT
        if not src.exists():
            return False, f"JSX not found: {UNIFIED_JSX_SCRIPT}"

        tmp = Path(tempfile.gettempdir()) / "Apollova"
        tmp.mkdir(exist_ok=True)
        dst = tmp / f"single_{UNIFIED_JSX_SCRIPT}"
        shutil.copy(src, dst)
        prepare_jsx_with_path(dst, None, UNIFIED_TEMPLATE_PATH,
                              auto_render=False, jobs_dirs=JOBS_DIRS)

        # Use aurora jobs dir for the error log (primary dir)
        err_log = JOBS_DIRS["aurora"] / "batch_error.txt"
        if err_log.exists():
            err_log.unlink()

        # Phase 1: inject all jobs into unified .aep
        app.signals.single_render_progress.emit("Status: Injecting…", 0.0)
        p = subprocess.Popen([ae, "-r", str(dst)], creationflags=flags)
        while p.poll() is None:
            if app.single_render_cancelled:
                p.terminate()
                p.wait(timeout=10)
                return False, "Cancelled by user"
            time.sleep(1)
        try:
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        if err_log.exists():
            return False, err_log.read_text().strip()

        # Phase 2: count all job dirs across all templates
        all_job_dirs = []
        for t in ["aurora", "mono", "onyx"]:
            d = JOBS_DIRS.get(t)
            if d and d.exists():
                all_job_dirs.extend(
                    sorted(x for x in d.iterdir()
                           if x.is_dir() and x.name.startswith("job_")))
        n_jobs = len(all_job_dirs)
        if n_jobs == 0:
            return False, "No job directories found after injection"

        failed_jobs: list[int] = []
        for job_idx in range(1, n_jobs + 1):
            if app.single_render_cancelled:
                return False, "Cancelled by user"
            pct = (job_idx - 1) / n_jobs * 100
            app.signals.single_render_progress.emit(
                f"Status: Rendering ({job_idx}/{n_jobs})…", pct)
            proc = subprocess.Popen(
                [str(aerender), "-project", str(UNIFIED_TEMPLATE_PATH),
                 "-rqindex", str(job_idx), "-continueOnMissingFootage",
                 "-mem_usage", "4", "60"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=flags,
            )
            for line in proc.stdout:
                if "PROGRESS:" in line:
                    try:
                        raw = float(line.split("PROGRESS:")[-1].strip())
                        overall = ((job_idx - 1) + raw / 100.0) / n_jobs * 100
                        app.signals.single_render_progress.emit(
                            f"Status: Rendering ({job_idx}/{n_jobs})…", overall)
                    except ValueError:
                        pass
                if app.single_render_cancelled:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return False, "Cancelled by user"
            proc.wait()
            if proc.returncode != 0:
                failed_jobs.append(job_idx)

        app.signals.single_render_progress.emit(
            f"Status: Done ({n_jobs - len(failed_jobs)}/{n_jobs} succeeded)", 100.0)
        if failed_jobs:
            return False, (
                f"{len(failed_jobs)}/{n_jobs} render jobs failed "
                f"(indices: {failed_jobs})")
        return True, None
    except Exception as e:
        return False, str(e)


def single_render_update_progress(app, status: str, pct: float) -> None:
    app.single_render_status_label.setText(status)
    app.single_render_progress_bar.setValue(int(pct))


def single_render_complete(app, ok: bool, err: str) -> None:
    app.single_render_active = False
    app.single_render_cancel_btn.setEnabled(False)
    app._update_inject_status()
    if not ok:
        app.single_render_status_label.setText(f"Status: Failed — {err}")
        app.single_render_progress_bar.setValue(0)
        QMessageBox.critical(app, "Render Failed", err)
    else:
        QMessageBox.information(app, "Render Complete",
                                "All jobs rendered successfully.")


def _escape_jsx_path(path_str: str) -> str:
    """Escape a path for safe embedding in a JSX string literal."""
    return (path_str
            .replace('\\', '/')
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace('\n', '')
            .replace('\r', ''))


def prepare_jsx_with_path(jsx_path, jobs_dir, template_path,
                          auto_render: bool = False,
                          keep_open: bool = False,
                          jobs_dirs: dict = None) -> None:
    """Substitute path placeholders in a JSX file in-place.

    When *jobs_dirs* is supplied (unified mode), all three per-template
    placeholders are substituted.  The legacy ``{{JOBS_PATH}}`` placeholder
    is also replaced for backwards compatibility with old per-template scripts.
    """
    with open(jsx_path, 'r', encoding='utf-8') as f:
        c = f.read()

    if jobs_dirs:
        c = c.replace('{{JOBS_PATH_AURORA}}',
                      _escape_jsx_path(str(jobs_dirs["aurora"])))
        c = c.replace('{{JOBS_PATH_MONO}}',
                      _escape_jsx_path(str(jobs_dirs["mono"])))
        c = c.replace('{{JOBS_PATH_ONYX}}',
                      _escape_jsx_path(str(jobs_dirs["onyx"])))

    # Keep legacy single-dir placeholder working for old per-template JSX files
    if jobs_dir is not None:
        c = c.replace('{{JOBS_PATH}}', _escape_jsx_path(str(jobs_dir)))

    c = c.replace('{{TEMPLATE_PATH}}',
                  _escape_jsx_path(str(template_path)))

    if keep_open:
        val = 'inject_only'
    elif auto_render:
        val = 'true'
    else:
        val = 'false'
    c = c.replace('{{AUTO_RENDER}}', val)

    with open(jsx_path, 'w', encoding='utf-8') as f:
        f.write(c)


def _find_aerender(ae_exe: str) -> Path | None:
    candidate = Path(ae_exe).parent / "aerender.exe"
    return candidate if candidate.exists() else None


