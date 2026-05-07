"""JSX Injection tab — individual injection and batch render."""

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
    QRadioButton, QGroupBox, QProgressBar, QButtonGroup, QMessageBox,
)

from assets.gui.constants import (
    INSTALL_DIR, ASSETS_DIR, BUNDLED_JSX_DIR, TEMPLATE_PATHS,
    JOBS_DIRS, JSX_SCRIPTS,
)
from assets.gui.helpers import _label, _set_label_style, _scrollable


def build(app) -> None:
    """Build the JSX Injection tab. Sets all widgets on *app*."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)

    # Template selector
    tpl_grp = QGroupBox("Individual Template Injection")
    tpl_lay = QVBoxLayout(tpl_grp)
    app.inject_tpl_group = QButtonGroup(app)
    for name, val, desc in [
        ("Aurora", "aurora", "Full visual template"),
        ("Mono", "mono", "Minimal text template"),
        ("Onyx", "onyx", "Hybrid vinyl template"),
    ]:
        rb = QRadioButton(f"{name}  —  {desc}")
        rb.setProperty("tval", val)
        if val == "aurora":
            rb.setChecked(True)
        app.inject_tpl_group.addButton(rb)
        tpl_lay.addWidget(rb)
    app.inject_tpl_group.buttonClicked.connect(app._update_inject_status)
    layout.addWidget(tpl_grp)

    # Status
    status_grp = QGroupBox("Status")
    status_lay = QVBoxLayout(status_grp)

    def status_row(label_text):
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
    app.inject_template_label = status_row("Template File:")
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
    app.inject_btn.setToolTip("Open After Effects, inject jobs, save project, and exit")
    app.inject_btn.clicked.connect(app._run_injection)
    btn_row.addWidget(app.inject_btn)

    app.single_render_btn = QPushButton("Inject & Render")
    app.single_render_btn.setObjectName("primary")
    app.single_render_btn.setToolTip(
        "Inject jobs then render all via aerender.exe (one job at a time)")
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

    # Batch render
    batch_grp = QGroupBox("Batch Render All Templates")
    batch_lay = QVBoxLayout(batch_grp)
    batch_lay.addWidget(QLabel("Templates Ready:"))
    app.batch_status_labels = {}
    for name, val, _ in [
        ("Aurora", "aurora", ""),
        ("Mono", "mono", ""),
        ("Onyx", "onyx", ""),
    ]:
        lbl = QLabel(f"  {name}: Checking...")
        app.batch_status_labels[val] = lbl
        batch_lay.addWidget(lbl)

    app.batch_status_label = QLabel("Status: Idle")
    app.batch_progress_bar = QProgressBar()
    app.batch_progress_bar.setRange(0, 100)
    app.batch_render_progress_bar = QProgressBar()
    app.batch_render_progress_bar.setRange(0, 100)
    app.batch_render_progress_bar.setFormat("Render: %p%")
    app.batch_render_progress_bar.setValue(0)
    app.batch_current_label = _label("", "muted")
    batch_lay.addWidget(app.batch_status_label)
    batch_lay.addWidget(app.batch_progress_bar)
    batch_lay.addWidget(app.batch_render_progress_bar)
    batch_lay.addWidget(app.batch_current_label)

    bb_row = QHBoxLayout()
    app.render_all_btn = QPushButton("Render All")
    app.render_all_btn.setObjectName("primary")
    app.render_all_btn.setToolTip("Render all templates with After Effects")
    app.render_all_btn.clicked.connect(app._start_batch_render)
    bb_row.addWidget(app.render_all_btn)
    app.batch_cancel_btn = QPushButton("\u2715  Cancel")
    app.batch_cancel_btn.setObjectName("muted")
    app.batch_cancel_btn.setEnabled(False)
    app.batch_cancel_btn.setToolTip(
        "Cancel batch render after current template")
    app.batch_cancel_btn.clicked.connect(app._cancel_batch_render)
    bb_row.addWidget(app.batch_cancel_btn)
    bb_row.addStretch()
    batch_lay.addLayout(bb_row)

    batch_info = _label(
        "Renders all templates sequentially (Aurora \u2192 Mono \u2192 Onyx).\n"
        "Each template auto-injects, renders, then closes. "
        "Requires 2+ templates.",
        "muted")
    batch_lay.addWidget(batch_info)
    layout.addWidget(batch_grp)
    layout.addStretch()

    app.tabs.addTab(_scrollable(page), "  \U0001f680 JSX Injection  ")
    app._update_inject_status()
    app._update_batch_status()


# ── Inject helpers ────────────────────────────────────────────────────────────

def inject_template(app) -> str:
    btn = app.inject_tpl_group.checkedButton()
    return btn.property("tval") if btn else "aurora"


def update_inject_status(app) -> None:
    t = app._inject_template()
    d = JOBS_DIRS.get(t)
    jobs_ok = template_ok = ae_ok = False

    if d and d.exists():
        jf = list(d.glob("job_*"))
        if jf:
            app.inject_jobs_label.setText(
                f"\u2713 {len(jf)} job(s) found in {d.name}")
            _set_label_style(app.inject_jobs_label, "success")
            jobs_ok = True
        else:
            app.inject_jobs_label.setText(f"\u2717 No jobs in {d}")
            _set_label_style(app.inject_jobs_label, "error")
    else:
        app.inject_jobs_label.setText("\u2717 Folder not found")
        _set_label_style(app.inject_jobs_label, "error")

    tp = TEMPLATE_PATHS.get(t)
    if tp and tp.exists():
        app.inject_template_label.setText(f"\u2713 {tp.name}")
        _set_label_style(app.inject_template_label, "success")
        template_ok = True
    else:
        app.inject_template_label.setText(
            f"\u2717 Not found: {tp.name if tp else 'Unknown'}")
        _set_label_style(app.inject_template_label, "error")

    ae = app.settings.get('after_effects_path')
    if ae and Path(ae).exists():
        app.inject_ae_label.setText("\u2713 Found")
        _set_label_style(app.inject_ae_label, "success")
        ae_ok = True
    else:
        app.inject_ae_label.setText(
            "\u2717 Not configured \u2014 go to Settings")
        _set_label_style(app.inject_ae_label, "error")

    can_act = jobs_ok and template_ok and ae_ok
    app.inject_btn.setEnabled(can_act and not app.single_render_active)
    app.single_render_btn.setEnabled(can_act and not app.single_render_active)


def run_injection(app) -> None:
    t = app._inject_template()
    ae = app.settings.get('after_effects_path')
    tp = TEMPLATE_PATHS.get(t)
    d = JOBS_DIRS.get(t)
    jsx = JSX_SCRIPTS.get(t)
    if app._log:
        app._log.section(f"JSX injection \u2014 template={t.upper()}, jsx={jsx}")
    try:
        src = BUNDLED_JSX_DIR / jsx
        if not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / jsx
        if not src.exists():
            if app._log:
                app._log.error(f"JSX script not found: {jsx}")
            QMessageBox.critical(app, "Error",
                f"JSX script not found: {jsx}\n\nPlease reinstall.")
            return
        tmp = Path(tempfile.gettempdir()) / "Apollova"
        tmp.mkdir(exist_ok=True)
        dst = tmp / jsx
        shutil.copy(src, dst)
        prepare_jsx_with_path(dst, d, tp)
        if app._log:
            app._log.info(
                f"JSX prepared at {dst} | jobs={d} | template={tp}")
    except Exception as e:
        tb = traceback.format_exc()
        if app._log:
            app._log.error(
                f"JSX preparation failed: {type(e).__name__}: {e}\n{tb}")
        QMessageBox.critical(app, "Error", f"Failed to prepare JSX:\n{e}")
        return
    # Validate AE path points to AfterFX.exe under an Adobe directory
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
            f"After Effects is launching\u2026\n\nTemplate: {tp.name}\n"
            f"Jobs: {d}\n\n"
            "The script will open the project and inject the jobs.")
    except Exception as e:
        tb = traceback.format_exc()
        if app._log:
            app._log.error(
                f"After Effects launch failed: {type(e).__name__}: {e}\n{tb}")
        QMessageBox.critical(app, "Error",
                             f"Failed to launch After Effects:\n{e}")


# ── Single template render ────────────────────────────────────────────────────

def start_single_render(app) -> None:
    t = app._inject_template()
    d = JOBS_DIRS.get(t)
    jf = list(d.glob("job_*")) if d and d.exists() else []
    if not jf:
        QMessageBox.warning(app, "No Jobs",
            f"No job directories found for {t.capitalize()}.\nRun batch generation first.")
        return
    reply = QMessageBox.question(
        app, "Confirm Render",
        f"Inject and render {len(jf)} {t.capitalize()} job(s) via aerender.exe?\n\n"
        "This will take several minutes per job.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return
    app.single_render_active = True
    app.single_render_cancelled = False
    app.single_render_btn.setEnabled(False)
    app.single_render_cancel_btn.setEnabled(True)
    app.inject_btn.setEnabled(False)
    app.render_all_btn.setEnabled(False)
    app.single_render_status_label.setText("Status: Starting…")
    app.single_render_progress_bar.setValue(0)
    threading.Thread(target=_single_render_worker, args=(app, t), daemon=True).start()


def _single_render_worker(app, t: str) -> None:
    ok, err = run_single_template(app, t)
    app.signals.single_render_finished.emit(ok, err or "")


def cancel_single_render(app) -> None:
    app.single_render_cancelled = True
    app.single_render_status_label.setText("Status: Cancelling…")


def run_single_template(app, t: str) -> tuple:
    ae = app.settings.get('after_effects_path')
    tp = TEMPLATE_PATHS.get(t)
    d = JOBS_DIRS.get(t)
    jsx = JSX_SCRIPTS.get(t)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    aerender = _find_aerender(ae)
    if not aerender:
        return False, f"aerender.exe not found next to {ae}"

    try:
        src = BUNDLED_JSX_DIR / jsx
        if not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / jsx
        if not src.exists():
            return False, f"JSX not found: {jsx}"

        tmp = Path(tempfile.gettempdir()) / "Apollova"
        tmp.mkdir(exist_ok=True)
        dst = tmp / f"single_{jsx}"
        shutil.copy(src, dst)
        prepare_jsx_with_path(dst, d, tp, auto_render=False)

        err_log = d / "batch_error.txt"
        if err_log.exists():
            err_log.unlink()

        # Phase 1: inject
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

        # Phase 2: render one job at a time
        job_dirs = sorted(x for x in d.iterdir() if x.is_dir() and x.name.startswith("job_"))
        n_jobs = len(job_dirs)
        if n_jobs == 0:
            return False, "No job directories found after injection"

        failed_jobs: list[int] = []
        for job_idx in range(1, n_jobs + 1):
            if app.single_render_cancelled:
                return False, "Cancelled by user"
            pct = (job_idx - 1) / n_jobs * 100
            app.signals.single_render_progress.emit(
                f"Status: Rendering {t.capitalize()} ({job_idx}/{n_jobs})…", pct)
            proc = subprocess.Popen(
                [str(aerender), "-project", str(tp),
                 "-rqindex", str(job_idx), "-continueOnMissingFootage"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=flags,
            )
            for line in proc.stdout:
                if "PROGRESS:" in line:
                    try:
                        raw = float(line.split("PROGRESS:")[-1].strip())
                        overall = ((job_idx - 1) + raw / 100.0) / n_jobs * 100
                        app.signals.single_render_progress.emit(
                            f"Status: Rendering {t.capitalize()} ({job_idx}/{n_jobs})…", overall)
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
            return False, f"{len(failed_jobs)}/{n_jobs} render jobs failed (indices: {failed_jobs})"
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
    app._update_batch_status()
    if not ok:
        app.single_render_status_label.setText(f"Status: Failed — {err}")
        app.single_render_progress_bar.setValue(0)
        QMessageBox.critical(app, "Render Failed", err)
    else:
        QMessageBox.information(app, "Render Complete", "All jobs rendered successfully.")


def _escape_jsx_path(path_str: str) -> str:
    """Escape a path for safe embedding in a JSX string literal."""
    return (path_str
            .replace('\\', '/')
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace('\n', '')
            .replace('\r', ''))


def prepare_jsx_with_path(jsx_path, jobs_dir, template_path,
                          auto_render: bool = False) -> None:
    with open(jsx_path, 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace('{{JOBS_PATH}}', _escape_jsx_path(str(jobs_dir)))
    c = c.replace('{{TEMPLATE_PATH}}',
                  _escape_jsx_path(str(template_path)))
    c = c.replace('{{AUTO_RENDER}}', 'true' if auto_render else 'false')
    with open(jsx_path, 'w', encoding='utf-8') as f:
        f.write(c)


# ── Batch Render ──────────────────────────────────────────────────────────────

def update_batch_status(app) -> list:
    ready = []
    ae = app.settings.get('after_effects_path')
    ae_ok = ae and Path(ae).exists()
    for t in ['aurora', 'mono', 'onyx']:
        d = JOBS_DIRS.get(t)
        tp = TEMPLATE_PATHS.get(t)
        jsx = JSX_SCRIPTS.get(t)
        jobs_ok = d and d.exists() and list(d.glob("job_*"))
        tpl_ok = tp and tp.exists()
        src = BUNDLED_JSX_DIR / jsx if jsx else None
        if src and not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / jsx
        jsx_ok = src and src.exists()
        lbl = app.batch_status_labels[t]
        if jobs_ok:
            cnt = len(list(d.glob("job_*")))
            if tpl_ok and jsx_ok:
                lbl.setText(f"  {t.capitalize()}: {cnt} jobs ready")
                _set_label_style(lbl, "success")
                ready.append(t)
            elif not tpl_ok:
                lbl.setText(
                    f"  {t.capitalize()}: {cnt} jobs (no template)")
                _set_label_style(lbl, "warning")
            else:
                lbl.setText(
                    f"  {t.capitalize()}: {cnt} jobs (JSX missing)")
                _set_label_style(lbl, "warning")
        else:
            lbl.setText(f"  {t.capitalize()}: No jobs")
            _set_label_style(lbl, "normal")
    app.render_all_btn.setEnabled(
        len(ready) >= 2 and ae_ok and not app.batch_render_active)
    return ready


def start_batch_render(app) -> None:
    ready = app._update_batch_status()
    if len(ready) < 2:
        QMessageBox.critical(app, "Error",
            "Need at least 2 templates with jobs.")
        return
    lines = ["Ready to render:"]
    for t in ready:
        lines.append(
            f"  - {t.capitalize()}: "
            f"{len(list(JOBS_DIRS[t].glob('job_*')))} jobs")
    lines += ["", "This will take a while. Continue?"]
    reply = QMessageBox.question(
        app, "Confirm Batch Render", "\n".join(lines),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return
    app.batch_render_active = True
    app.batch_render_cancelled = False
    app.batch_results = {}
    app.render_all_btn.setEnabled(False)
    app.batch_cancel_btn.setEnabled(True)
    app.inject_btn.setEnabled(False)
    threading.Thread(target=batch_render_thread,
                     args=(app, ready), daemon=True).start()


def cancel_batch_render(app) -> None:
    reply = QMessageBox.question(
        app, "Cancel",
        "Cancel batch? Current template will finish first.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply == QMessageBox.StandardButton.Yes:
        app.batch_render_cancelled = True
        app.batch_status_label.setText("Status: Cancelling\u2026")


def batch_render_thread(app, templates: list) -> None:
    total = len(templates)
    for idx, t in enumerate(templates):
        if app.batch_render_cancelled:
            app.signals.batch_progress.emit(
                "Status: Cancelled", idx / total * 100, "Cancelled")
            break
        app.signals.batch_progress.emit(
            f"Status: Rendering {t.capitalize()} ({idx+1}/{total})",
            idx / total * 100,
            f"Launching After Effects for {t.capitalize()}\u2026")
        ok, err = run_batch_template(app, t)
        app.batch_results[t] = {'success': ok, 'error': err}
        if ok:
            app.signals.batch_template_status.emit(
                t, f"  {t.capitalize()}: Complete \u2713")
        else:
            app.signals.batch_template_status.emit(
                t, f"  {t.capitalize()}: Failed \u2014 {err}")
    app.signals.batch_finished.emit(dict(app.batch_results))


def _find_aerender(ae_exe: str) -> Path | None:
    candidate = Path(ae_exe).parent / "aerender.exe"
    return candidate if candidate.exists() else None


def run_batch_template(app, t: str) -> tuple:
    ae = app.settings.get('after_effects_path')
    tp = TEMPLATE_PATHS.get(t)
    d = JOBS_DIRS.get(t)
    jsx = JSX_SCRIPTS.get(t)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    aerender = _find_aerender(ae)
    if not aerender:
        return False, f"aerender.exe not found next to {ae}"

    try:
        src = BUNDLED_JSX_DIR / jsx
        if not src.exists():
            src = ASSETS_DIR / "scripts" / "JSX" / jsx
        if not src.exists():
            return False, f"JSX not found: {jsx}"

        tmp = Path(tempfile.gettempdir()) / "Apollova"
        tmp.mkdir(exist_ok=True)
        dst = tmp / f"batch_{jsx}"
        shutil.copy(src, dst)
        # Inject only — no AUTO_RENDER; JSX saves the project then AE exits
        prepare_jsx_with_path(dst, d, tp, auto_render=False)

        err_log = d / "batch_error.txt"
        if err_log.exists():
            err_log.unlink()

        # ── Phase 1: Inject ───────────────────────────────────────────────────
        app.signals.batch_progress.emit(
            f"Status: Injecting {t.capitalize()}…",
            0, f"Opening After Effects for {t.capitalize()}…")
        p = subprocess.Popen([ae, "-r", str(dst)], creationflags=flags)
        while p.poll() is None:
            if app.batch_render_cancelled:
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

        # ── Phase 2: Render via aerender.exe (one job at a time to avoid OOM) ──
        # Running all items in one aerender process exhausts RAM after the first
        # render when Multi-Frame Rendering is enabled. Separate processes give
        # each job a fresh memory budget.
        job_dirs = sorted(
            x for x in d.iterdir()
            if x.is_dir() and x.name.startswith("job_")
        )
        n_jobs = len(job_dirs)
        if n_jobs == 0:
            return False, "No job directories found after injection"

        app.signals.batch_render_progress.emit(0.0)
        failed_jobs: list[int] = []
        for job_idx in range(1, n_jobs + 1):
            if app.batch_render_cancelled:
                return False, "Cancelled by user"

            app.signals.batch_progress.emit(
                f"Status: Rendering {t.capitalize()} ({job_idx}/{n_jobs})…",
                (job_idx - 1) / n_jobs * 100,
                f"aerender.exe rendering {t.capitalize()} {job_idx}/{n_jobs}…",
            )

            proc = subprocess.Popen(
                [
                    str(aerender), "-project", str(tp),
                    "-rqindex", str(job_idx),
                    "-continueOnMissingFootage",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=flags,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if "PROGRESS:" in line:
                    try:
                        raw = float(line.split("PROGRESS:")[-1].strip())
                        overall = ((job_idx - 1) + raw / 100.0) / n_jobs * 100
                        app.signals.batch_render_progress.emit(overall)
                    except ValueError:
                        pass
                if app.batch_render_cancelled:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return False, "Cancelled by user"
            proc.wait()
            if proc.returncode != 0:
                failed_jobs.append(job_idx)

        app.signals.batch_render_progress.emit(100.0)
        if failed_jobs:
            return False, f"{len(failed_jobs)}/{n_jobs} render jobs failed (indices: {failed_jobs})"
        return True, None
    except Exception as e:
        return False, str(e)


def batch_update_progress(app, status: str, progress: float,
                          current: str) -> None:
    app.batch_status_label.setText(status)
    app.batch_progress_bar.setValue(int(progress))
    app.batch_current_label.setText(current)
    # Reset render sub-bar on new template
    app.batch_render_progress_bar.setValue(0)


def batch_update_render_progress(app, pct: float) -> None:
    app.batch_render_progress_bar.setValue(int(pct))


def batch_update_template_status_slot(app, template: str,
                                      text: str) -> None:
    lbl = app.batch_status_labels.get(template)
    if lbl:
        lbl.setText(text)
        style = "success" if "Complete" in text else "error"
        _set_label_style(lbl, style)


def batch_render_complete(app, results: dict) -> None:
    app.batch_render_active = False
    app.render_all_btn.setEnabled(True)
    app.batch_cancel_btn.setEnabled(False)
    app.inject_btn.setEnabled(True)
    app.batch_progress_bar.setValue(100)
    sc = sum(1 for r in results.values() if r['success'])
    fc = sum(1 for r in results.values() if not r['success'])
    if app.batch_render_cancelled:
        app.batch_status_label.setText("Status: Cancelled")
        app.batch_current_label.setText(
            f"Completed {sc} before cancellation")
    else:
        app.batch_status_label.setText("Status: Complete")
        app.batch_current_label.setText(f"Success: {sc}, Failed: {fc}")
    lines = ["Batch Render Complete\n"]
    for t, r in results.items():
        status_str = "Success" if r['success'] else ("Failed \u2014 " + str(r['error']))
        lines.append(f"{t.capitalize()}: {status_str}")
    if app.batch_render_cancelled:
        lines.append("\nCancelled by user.")
    QMessageBox.information(
        app, "Batch Render Complete", "\n".join(lines))
    app._update_batch_status()
