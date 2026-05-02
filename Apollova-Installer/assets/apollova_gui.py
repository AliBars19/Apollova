#!/usr/bin/env python3
"""
Apollova - Lyric Video Job Generator
PyQt6 GUI Application - No tkinter, no Tcl/Tk dependency

This is the main class shell. Tab-building and handlers live in assets/gui/.
"""

import os
import sys
import json
import threading

# ── Fix stdout/stderr for --windowed PyInstaller builds ──────────────────────
# PyInstaller --windowed sets stdout/stderr to None on Windows, which causes
# any print() call (especially ones with Unicode emoji) to crash silently.
# Redirect to devnull so all print() calls in scripts are harmlessly absorbed.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
# Even when stdout exists, Windows cp1252 encoding can't handle emoji.
# Reconfigure to UTF-8 with replace error handling so nothing ever crashes.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

from pathlib import Path as _Path
# Ensure the install root (parent of assets/) is on sys.path so
# `from assets.gui.*` imports resolve correctly.
_install_root = str(_Path(__file__).resolve().parent.parent)
if _install_root not in sys.path:
    sys.path.insert(0, _install_root)

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QFrame
from PyQt6.QtGui import QIcon

from assets.gui.constants import (
    BASE_DIR, ASSETS_DIR, INSTALL_DIR, APP_VERSION,
    AURORA_JOBS_DIR, MONO_JOBS_DIR, ONYX_JOBS_DIR,
    DATABASE_DIR, WHISPER_DIR, TEMPLATES_DIR, SETTINGS_FILE,
    APP_STYLE,
)
from assets.gui.helpers import (
    WorkerSignals, _label, _show_startup_error,
)

# ── Path setup for script imports ─────────────────────────────────────────────
sys.path.insert(0, str(ASSETS_DIR))

try:
    from apollova_logger import get_logger as _get_logger
except Exception:
    _get_logger = None


# ── Import pipeline scripts ──────────────────────────────────────────────────
def _import_scripts():
    global Config, download_audio, trim_audio, detect_beats
    global download_image, extract_colors, transcribe_audio
    global transcribe_audio_mono, transcribe_audio_onyx
    global SongDatabase, fetch_genius_image, fetch_genius_image_rotated, SmartSongPicker

    # Check files exist
    missing = [s for s in ["config", "audio_processing", "image_processing",
                           "whisper_common",
                           "lyric_processing", "lyric_processing_mono",
                           "lyric_processing_onyx", "lyric_alignment",
                           "song_database", "genius_processing", "smart_picker"]
               if not (ASSETS_DIR / "scripts" / f"{s}.py").exists()]
    if missing:
        _show_startup_error(
            "Missing Files",
            "The following required files are missing:\n\n" +
            "\n".join(f"  \u2022 scripts/{m}.py" for m in missing),
            "Please reinstall Apollova \u2014 some files appear to have been deleted."
        )

    try:
        from scripts.config import Config as _C
        from scripts.audio_processing import download_audio as _da, trim_audio as _ta, detect_beats as _db
        from scripts.image_processing import download_image as _di, extract_colors as _ec
        from scripts.lyric_processing import transcribe_audio as _tr
        from scripts.lyric_processing_mono import transcribe_audio_mono as _trm
        from scripts.lyric_processing_onyx import transcribe_audio_onyx as _tro
        from scripts.song_database import SongDatabase as _SD
        from scripts.genius_processing import fetch_genius_image as _fg
        from scripts.genius_processing import fetch_genius_image_rotated as _fgr
        from scripts.smart_picker import SmartSongPicker as _SP
        Config = _C; download_audio = _da; trim_audio = _ta; detect_beats = _db
        download_image = _di; extract_colors = _ec; transcribe_audio = _tr
        transcribe_audio_mono = _trm; transcribe_audio_onyx = _tro
        SongDatabase = _SD; fetch_genius_image = _fg; fetch_genius_image_rotated = _fgr
        SmartSongPicker = _SP

    except OSError as e:
        err = str(e)
        if "1114" in err or "DLL" in err or "c10.dll" in err:
            _show_startup_error(
                "PyTorch DLL Error",
                "PyTorch failed to load due to a conflicting installation.\n\n"
                "This happens when two versions of PyTorch are installed at the same time "
                "(one in AppData and one in Program Files).",
                "Open PowerShell and run:\n\n"
                "  pip uninstall torch torchaudio -y\n\n"
                "Then re-run Setup.exe to reinstall cleanly.\n\n"
                "If this keeps happening, install the Visual C++ Redistributable:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            )
        _show_startup_error("Load Error", f"Failed to load application:\n{e}",
                            "Re-run Setup.exe to repair your installation.")

    except ImportError as e:
        pkg = str(e).replace("No module named ", "").strip("'")
        _show_startup_error(
            "Missing Package",
            f"A required Python package is not installed:\n\n  {pkg}",
            f"Re-run Setup.exe to install all required packages.\n\n"
            f"Or manually run:  pip install {pkg}"
        )
    except Exception as e:
        _show_startup_error(
            "Startup Error",
            f"Apollova failed to start:\n\n{type(e).__name__}: {e}",
            "Re-run Setup.exe to repair your installation."
        )


Config = download_audio = trim_audio = detect_beats = None
download_image = extract_colors = transcribe_audio = None
transcribe_audio_mono = transcribe_audio_onyx = None
SongDatabase = fetch_genius_image = fetch_genius_image_rotated = SmartSongPicker = None
_import_scripts()

# ── Tab + handler modules ────────────────────────────────────────────────────
from assets.gui import job_creation_tab, jsx_injection_tab, settings_tab
from assets.gui import mobile_server, job_processing
from pathlib import Path


# ── Main Window ───────────────────────────────────────────────────────────────
class AppolovaApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Apollova v{APP_VERSION} - Lyric Video Generator")
        self.resize(960, 800)
        self.setMinimumSize(800, 600)

        icon_path = INSTALL_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_directories()
        self.song_db = SongDatabase(db_path=str(DATABASE_DIR / "songs.db"))
        self.smart_picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
        self.settings = self._load_settings()

        # Sync settings -> Config and validate
        Config.GENIUS_API_TOKEN = self.settings.get('genius_api_token', '')
        Config.WHISPER_MODEL = self.settings.get('whisper_model', 'small')
        self._config_warnings = Config.validate()

        self._job_queue = []
        self.is_processing = False
        self.cancel_requested = False
        self._resume_mode = False
        self.use_smart_picker = False
        self._smart_songs = []
        self.batch_render_active = False
        self.batch_render_cancelled = False
        self.batch_results = {}
        self._discover_cancel_event = threading.Event()
        self._discovery_in_progress = False
        self._discovery_results = []

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(lambda v: self.progress_bar.setValue(int(v)))
        self.signals.progress.connect(self._broadcast_progress)
        self.signals.finished.connect(self._on_generation_finished)
        self.signals.error.connect(self._on_generation_error)
        self.signals.stats_refresh.connect(self._refresh_stats_label)
        self.signals.batch_progress.connect(self._batch_update_progress)
        self.signals.batch_template_status.connect(self._batch_update_template_status_slot)
        self.signals.batch_finished.connect(self._batch_render_complete)
        self.signals.batch_render_progress.connect(self._batch_update_render_progress)
        self.signals.discovery_progress.connect(self._on_discovery_progress)
        self.signals.discovery_results.connect(self._on_discovery_results)
        self.signals.discovery_error.connect(self._on_discovery_error)

        # Initialise file logger
        try:
            self._log = _get_logger("app") if _get_logger else None
            if self._log:
                self._log.session_start("Apollova GUI")
        except Exception:
            self._log = None

        self._build_ui()

        # Show config warnings in the log
        for w in self._config_warnings:
            self._append_log(f"Config: {w}")

        if not self.settings.get('after_effects_path'):
            detected = self._auto_detect_after_effects()
            if detected:
                self.settings['after_effects_path'] = detected
                self._save_settings()
                self.ae_path_edit.setText(detected)
                self._update_ae_status()

        # Mobile server + tunnel
        self._tunnel_manager = None
        self._server_thread = None
        self._start_mobile_server()
        self._setup_system_tray()

    # ── Dirs / Settings ───────────────────────────────────────────────────────

    def _init_directories(self):
        for d in [AURORA_JOBS_DIR, MONO_JOBS_DIR, ONYX_JOBS_DIR,
                  DATABASE_DIR, WHISPER_DIR, TEMPLATES_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_settings(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'after_effects_path': None,
            'genius_api_token': Config.GENIUS_API_TOKEN,
            'whisper_model': Config.WHISPER_MODEL,
        }

    def _save_settings(self):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=2)

    def _auto_detect_after_effects(self):
        versions = [
            "Adobe After Effects 2026", "Adobe After Effects 2025", "Adobe After Effects 2024",
            "Adobe After Effects 2023", "Adobe After Effects CC 2024",
            "Adobe After Effects CC 2023", "Adobe After Effects CC 2022",
            "Adobe After Effects CC 2021", "Adobe After Effects CC 2020",
        ]
        for pf in [Path("C:/Program Files/Adobe"),
                   Path("C:/Program Files (x86)/Adobe")]:
            if pf.exists():
                for v in versions:
                    p = pf / v / "Support Files" / "AfterFX.exe"
                    if p.exists():
                        return str(p)
        return None

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 15, 20, 15)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_label("\U0001f3ac Apollova", "title"))
        hdr.addWidget(_label("  Lyric Video Generator", "subtitle"))
        hdr.addStretch()
        stats = self.song_db.get_stats()
        self.stats_label = _label(
            f"\U0001f4ca {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics",
            "subtitle")
        hdr.addWidget(self.stats_label)
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#313244;")
        root.addWidget(sep)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        job_creation_tab.build(self)
        jsx_injection_tab.build(self)
        settings_tab.build(self)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ── Delegated handlers: Job Creation tab ──────────────────────────────────

    def _on_tab_changed(self, index):
        if index == 1:
            self._update_inject_status()
            self._update_batch_status()

    def _on_template_change(self):
        job_creation_tab.on_template_change(self)

    def _on_song_mode_changed(self, index):
        job_creation_tab.on_song_mode_changed(self, index)

    def _on_jobs_count_changed(self, _index):
        job_creation_tab.on_jobs_count_changed(self, _index)

    def _update_queue_counter(self):
        job_creation_tab.update_queue_counter(self)

    def _update_generate_btn_state(self):
        job_creation_tab.update_generate_btn_state(self)

    def _add_job_to_queue(self):
        job_creation_tab.add_job_to_queue(self)

    def _remove_from_queue(self):
        job_creation_tab.remove_from_queue(self)

    def _clear_queue(self):
        job_creation_tab.clear_queue(self)

    def _rebuild_queue_list(self):
        job_creation_tab.rebuild_queue_list(self)

    def _job_template(self):
        return job_creation_tab.job_template(self)

    def _refresh_smart_picker_stats(self):
        job_creation_tab.refresh_smart_picker_stats(self)

    def _reset_use_counts(self):
        job_creation_tab.reset_use_counts(self)

    def _reshuffle_songs(self):
        job_creation_tab.reshuffle_songs(self)

    def _check_lastfm_configured(self):
        job_creation_tab.check_lastfm_configured(self)

    def _start_discovery(self):
        job_creation_tab.start_discovery(self)

    def _cancel_discovery(self):
        job_creation_tab.cancel_discovery(self)

    def _on_discovery_progress(self, step, current, total, title):
        job_creation_tab.on_discovery_progress(self, step, current, total, title)

    def _on_discovery_results(self, results):
        job_creation_tab.on_discovery_results(self, results)

    def _on_discovery_error(self, error_msg):
        job_creation_tab.on_discovery_error(self, error_msg)

    def _discover_select_all(self):
        job_creation_tab.discover_select_all(self)

    def _discover_deselect_all(self):
        job_creation_tab.discover_deselect_all(self)

    def _discover_deselect_low(self):
        job_creation_tab.discover_deselect_low(self)

    def _update_discover_add_btn(self, *args):
        job_creation_tab.update_discover_add_btn(self, *args)

    def _discover_add_selected(self):
        job_creation_tab.discover_add_selected(self)

    @staticmethod
    def _highlight_field(field, has_error):
        job_creation_tab.highlight_field(field, has_error)

    def _on_url_changed(self, text):
        job_creation_tab.on_url_changed(self, text)

    def _validate_song_record(self, url, start, end):
        return job_creation_tab.validate_song_record(url, start, end)

    def _check_database(self):
        job_creation_tab.check_database(self)

    def _check_existing_jobs(self):
        job_creation_tab.check_existing_jobs(self)

    def _delete_existing_jobs(self):
        job_creation_tab.delete_existing_jobs(self)

    def _open_jobs_folder(self):
        job_creation_tab.open_jobs_folder(self)

    def _test_lastfm_connection(self):
        job_creation_tab.test_lastfm_connection(self)

    # ── Delegated handlers: JSX Injection tab ─────────────────────────────────

    def _inject_template(self):
        return jsx_injection_tab.inject_template(self)

    def _update_inject_status(self):
        jsx_injection_tab.update_inject_status(self)

    def _run_injection(self):
        jsx_injection_tab.run_injection(self)

    def _prepare_jsx_with_path(self, jsx_path, jobs_dir, template_path,
                               auto_render=False):
        jsx_injection_tab.prepare_jsx_with_path(
            jsx_path, jobs_dir, template_path, auto_render)

    def _update_batch_status(self):
        return jsx_injection_tab.update_batch_status(self)

    def _start_batch_render(self):
        jsx_injection_tab.start_batch_render(self)

    def _cancel_batch_render(self):
        jsx_injection_tab.cancel_batch_render(self)

    def _batch_update_progress(self, status, progress, current):
        jsx_injection_tab.batch_update_progress(self, status, progress, current)

    def _batch_update_template_status_slot(self, template, text):
        jsx_injection_tab.batch_update_template_status_slot(self, template, text)

    def _batch_render_complete(self, results):
        jsx_injection_tab.batch_render_complete(self, results)

    def _batch_update_render_progress(self, pct):
        jsx_injection_tab.batch_update_render_progress(self, pct)

    # ── Delegated handlers: Settings tab ──────────────────────────────────────

    def _update_ae_status(self):
        settings_tab.update_ae_status(self)

    def _check_ffmpeg(self):
        settings_tab.check_ffmpeg(self)

    def _browse_ae_path(self):
        settings_tab.browse_ae_path(self)

    def _auto_detect_ae_click(self):
        settings_tab.auto_detect_ae_click(self)

    def _save_all_settings(self):
        settings_tab.save_all_settings(self)

    def _toggle_launch_on_startup(self, enabled):
        settings_tab.toggle_launch_on_startup(self, enabled)

    def _regenerate_qr(self):
        settings_tab.regenerate_qr(self)

    # ── Delegated handlers: Mobile server ─────────────────────────────────────

    def _start_mobile_server(self):
        mobile_server.start_mobile_server(self)

    def _setup_system_tray(self):
        mobile_server.setup_system_tray(self)

    def _show_mobile_qr(self):
        mobile_server.show_mobile_qr(self)

    # ── Delegated handlers: Job processing ────────────────────────────────────

    def _validate_inputs(self):
        return job_processing.validate_inputs(self)

    def _lock_inputs(self, lock):
        job_processing.lock_inputs(self, lock)

    def _start_generation(self):
        job_processing.start_generation(self)

    def _cancel_generation(self):
        job_processing.cancel_generation(self)

    def _run_step(self, job_number, step_name, fn, *args, **kwargs):
        return job_processing.run_step(self, job_number, step_name, fn, *args, **kwargs)

    def _process_single_song(self, job_number, song_title, youtube_url,
                              start_time, end_time, template, output_dir,
                              return_data=False):
        return job_processing.process_single_song(
            self, job_number, song_title, youtube_url,
            start_time, end_time, template, output_dir, return_data)

    def _on_generation_finished(self):
        job_processing.on_generation_finished(self)

    def _on_generation_error(self, msg):
        job_processing.on_generation_error(self, msg)

    def _broadcast_progress(self, percent):
        job_processing.broadcast_progress(self, percent)

    def _append_log(self, msg):
        job_processing.append_log(self, msg)

    def _refresh_stats_label(self):
        job_processing.refresh_stats_label(self)

    def _run_with_ticker(self, fn, *args, **kwargs):
        return job_processing.run_with_ticker(self, fn, *args, **kwargs)

    def _cleanup_and_quit(self):
        job_processing.cleanup_and_quit(self)

    def closeEvent(self, event):
        job_processing.close_event(self, event)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova")
    app.setStyleSheet(APP_STYLE)
    win = AppolovaApp()
    if "--minimised" in sys.argv:
        win.hide()
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
