#!/usr/bin/env python3
"""
Apollova - Lyric Video Job Generator
PyQt6 GUI Application - No tkinter, no Tcl/Tk dependency
"""

import os
import re
import sys
import json
import shutil
import time
import threading
import tempfile
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QRadioButton,
    QTabWidget, QGroupBox, QTextEdit, QProgressBar, QListWidget,
    QScrollArea, QFileDialog, QMessageBox, QButtonGroup, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon

# ── Path resolution ───────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR   = Path(sys.executable).parent
    ASSETS_DIR = BASE_DIR / "assets"
else:
    ASSETS_DIR = Path(__file__).parent
    BASE_DIR   = ASSETS_DIR.parent

BUNDLED_JSX_DIR = ASSETS_DIR / "scripts" / "JSX"
sys.path.insert(0, str(ASSETS_DIR))

try:
    from apollova_logger import get_logger as _get_logger
except Exception:
    _get_logger = None

# ── Safe startup: friendly GUI errors instead of raw tracebacks ───────────────
def _show_startup_error(title, message, fix=None):
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = QMessageBox()
    dlg.setWindowTitle(f"Apollova \u2014 {title}")
    dlg.setIcon(QMessageBox.Icon.Critical)
    dlg.setText(f"<b>{title}</b>")
    full_msg = message
    if fix:
        full_msg += f"\n\n<b>How to fix:</b>\n{fix}"
    dlg.setInformativeText(full_msg)
    dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
    dlg.setStyleSheet(
        "QWidget{background:#1e1e2e;color:#cdd6f4;font-family:'Segoe UI';font-size:13px;}"
        "QPushButton{background:#313244;border:1px solid #45475a;border-radius:5px;"
        "padding:6px 16px;color:#cdd6f4;}"
        "QPushButton:hover{background:#89b4fa;color:#1e1e2e;}"
    )
    dlg.exec()
    sys.exit(1)

def _import_scripts():
    global Config, download_audio, trim_audio, detect_beats
    global download_image, extract_colors, transcribe_audio
    global transcribe_audio_mono, transcribe_audio_onyx
    global SongDatabase, fetch_genius_image, SmartSongPicker

    # Check files exist
    missing = [s for s in ["config","audio_processing","image_processing",
                            "whisper_common",
                            "lyric_processing","lyric_processing_mono",
                            "lyric_processing_onyx","lyric_alignment",
                            "song_database","genius_processing","smart_picker"]
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
        from scripts.smart_picker import SmartSongPicker as _SP
        Config=_C; download_audio=_da; trim_audio=_ta; detect_beats=_db
        download_image=_di; extract_colors=_ec; transcribe_audio=_tr
        transcribe_audio_mono=_trm; transcribe_audio_onyx=_tro
        SongDatabase=_SD; fetch_genius_image=_fg; SmartSongPicker=_SP

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
        pkg = str(e).replace("No module named ","").strip("'")
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

Config=download_audio=trim_audio=detect_beats=None
download_image=extract_colors=transcribe_audio=None
transcribe_audio_mono=transcribe_audio_onyx=None
SongDatabase=fetch_genius_image=SmartSongPicker=None
_import_scripts()

# ── Directory constants ───────────────────────────────────────────────────────
INSTALL_DIR     = BASE_DIR
TEMPLATES_DIR   = BASE_DIR / "templates"
AURORA_JOBS_DIR = BASE_DIR / "Apollova-Aurora" / "jobs"
MONO_JOBS_DIR   = BASE_DIR / "Apollova-Mono"   / "jobs"
ONYX_JOBS_DIR   = BASE_DIR / "Apollova-Onyx"   / "jobs"
DATABASE_DIR    = BASE_DIR / "database"
WHISPER_DIR     = BASE_DIR / "whisper_models"
SETTINGS_FILE   = BASE_DIR / "settings.json"

TEMPLATE_PATHS = {
    "aurora": TEMPLATES_DIR / "Apollova-Aurora.aep",
    "mono":   TEMPLATES_DIR / "Apollova-Mono.aep",
    "onyx":   TEMPLATES_DIR / "Apollova-Onyx.aep",
}
JOBS_DIRS = {
    "aurora": AURORA_JOBS_DIR,
    "mono":   MONO_JOBS_DIR,
    "onyx":   ONYX_JOBS_DIR,
}
JSX_SCRIPTS = {
    "aurora": "Apollova-Aurora-Injection.jsx",
    "mono":   "Apollova-Mono-Injection.jsx",
    "onyx":   "Apollova-Onyx-Injection.jsx",
}

# ── Stylesheet ────────────────────────────────────────────────────────────────
APP_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #313244;
    border-radius: 6px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    padding: 8px 18px;
    border-radius: 4px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
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
QLineEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 8px;
    color: #cdd6f4;
}
QLineEdit:focus { border: 1px solid #89b4fa; }
QPushButton {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 7px 18px;
    color: #cdd6f4;
    min-height: 28px;
}
QPushButton:hover { background: #3a3d5c; border-color: #89b4fa; color: #cdd6f4; }
QPushButton:pressed { background: #89b4fa; color: #1e1e2e; border-color: #89b4fa; }
QPushButton:disabled { background: #1e1e2e; color: #45475a; border-color: #2a2a3c; }
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    font-size: 14px;
    padding: 9px 26px;
    border: none;
    border-radius: 6px;
    min-height: 34px;
}
QPushButton#primary:hover { background: #b4befe; border: none; }
QPushButton#primary:pressed { background: #cdd6f4; border: none; }
QPushButton#primary:disabled { background: #2a2f45; color: #45475a; border: 1px solid #313244; }
QPushButton#accent {
    background: #1a2540;
    color: #89b4fa;
    border: 1px solid #4a6fa5;
    border-radius: 6px;
    padding: 7px 18px;
    min-height: 28px;
}
QPushButton#accent:hover { background: #89b4fa; color: #1e1e2e; border-color: #89b4fa; }
QPushButton#accent:pressed { background: #b4befe; color: #1e1e2e; }
QPushButton#accent:disabled { background: #1e1e2e; color: #45475a; border-color: #2a2a3c; }
QPushButton#danger {
    background: #2e1520;
    color: #f38ba8;
    border: 1px solid #6b2d3e;
    border-radius: 6px;
    padding: 7px 18px;
    min-height: 28px;
}
QPushButton#danger:hover { background: #f38ba8; color: #1e1e2e; border-color: #f38ba8; }
QPushButton#danger:pressed { background: #eba0ac; color: #1e1e2e; }
QPushButton#muted {
    background: #1e1e2e;
    color: #6c7086;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 7px 18px;
    min-height: 28px;
}
QPushButton#muted:hover { background: #313244; color: #a6adc8; border-color: #45475a; }
QPushButton#muted:pressed { background: #45475a; color: #cdd6f4; }
QComboBox {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 5px 8px;
    color: #cdd6f4;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #313244;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QRadioButton { spacing: 8px; color: #cdd6f4; padding: 3px 0; }
QRadioButton::indicator {
    width: 16px; height: 16px;
    border-radius: 8px;
    border: 2px solid #45475a;
    background: #1e1e2e;
}
QRadioButton::indicator:hover { border-color: #89b4fa; }
QRadioButton::indicator:checked { background: #89b4fa; border-color: #89b4fa; }
QTextEdit {
    background: #11111b;
    border: 1px solid #313244;
    border-radius: 4px;
    color: #a6e3a1;
    font-family: 'Consolas';
    font-size: 11px;
}
QListWidget {
    background: #181825;
    border: 1px solid #313244;
    border-radius: 4px;
    color: #cdd6f4;
    font-family: 'Consolas';
    font-size: 11px;
}
QListWidget::item:selected { background: #89b4fa; color: #1e1e2e; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 10px;
    text-align: center;
    color: #1e1e2e;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QScrollArea { border: none; }
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #89b4fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ── Validation patterns ───────────────────────────────────────────────────────
_VALID_YT   = re.compile(r'(?:youtube\.com/watch\?.*v=|youtu\.be/)([A-Za-z0-9_-]{11})')
_VALID_TIME = re.compile(r'^\d{1,2}:\d{2}$')

# ── Worker signals (thread → UI) ──────────────────────────────────────────────
class WorkerSignals(QObject):
    log                   = pyqtSignal(str)
    progress              = pyqtSignal(float)
    finished              = pyqtSignal()
    error                 = pyqtSignal(str)
    stats_refresh         = pyqtSignal()
    batch_progress        = pyqtSignal(str, float, str)
    batch_template_status = pyqtSignal(str, str)
    batch_finished        = pyqtSignal(dict)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _label(text, style=""):
    lbl = QLabel(text)
    if style == "title":
        f = QFont("Segoe UI")
        f.setPointSize(16)
        f.setWeight(QFont.Weight.Bold)
        lbl.setFont(f)
        lbl.setStyleSheet("color:#89b4fa;")
    elif style == "subtitle":
        lbl.setStyleSheet("color:#6c7086; font-size:12px;")
    elif style == "muted":
        lbl.setStyleSheet("color:#6c7086; font-size:11px;")
    elif style == "success":
        lbl.setStyleSheet("color:#a6e3a1;")
    elif style == "warning":
        lbl.setStyleSheet("color:#f9e2af;")
    elif style == "error":
        lbl.setStyleSheet("color:#f38ba8;")
    return lbl

def _set_label_style(lbl, style):
    styles = {
        "success": "color:#a6e3a1;",
        "warning": "color:#f9e2af;",
        "error":   "color:#f38ba8;",
        "muted":   "color:#6c7086; font-size:11px;",
        "normal":  "color:#cdd6f4;",
    }
    lbl.setStyleSheet(styles.get(style, "color:#cdd6f4;"))

def _scrollable(widget):
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    return scroll


# ── Main Window ───────────────────────────────────────────────────────────────
class AppolovaApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apollova - Lyric Video Generator")
        self.resize(960, 800)
        self.setMinimumSize(800, 600)

        icon_path = INSTALL_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_directories()
        self.song_db  = SongDatabase(db_path=str(DATABASE_DIR / "songs.db"))
        self.settings = self._load_settings()

        # Sync settings → Config and validate
        Config.GENIUS_API_TOKEN = self.settings.get('genius_api_token', '')
        Config.WHISPER_MODEL = self.settings.get('whisper_model', 'small')
        self._config_warnings = Config.validate()

        self._job_queue             = []   # list of {title, url, start, end}
        self.is_processing          = False
        self.cancel_requested       = False
        self._resume_mode           = False
        self.use_smart_picker       = False
        self.batch_render_active    = False
        self.batch_render_cancelled = False
        self.batch_results          = {}

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(lambda v: self.progress_bar.setValue(int(v)))
        self.signals.finished.connect(self._on_generation_finished)
        self.signals.error.connect(self._on_generation_error)
        self.signals.stats_refresh.connect(self._refresh_stats_label)
        self.signals.batch_progress.connect(self._batch_update_progress)
        self.signals.batch_template_status.connect(self._batch_update_template_status_slot)
        self.signals.batch_finished.connect(self._batch_render_complete)

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

    # ── Dirs / Settings ───────────────────────────────────────────────────────

    def _init_directories(self):
        for d in [AURORA_JOBS_DIR, MONO_JOBS_DIR, ONYX_JOBS_DIR,
                  DATABASE_DIR, WHISPER_DIR, TEMPLATES_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_settings(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'after_effects_path': None,
            'genius_api_token':   Config.GENIUS_API_TOKEN,
            'whisper_model':      Config.WHISPER_MODEL,
        }

    def _save_settings(self):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=2)

    def _auto_detect_after_effects(self):
        versions = [
            "Adobe After Effects 2025", "Adobe After Effects 2024",
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
        hdr.addWidget(_label("🎬 Apollova", "title"))
        hdr.addWidget(_label("  Lyric Video Generator", "subtitle"))
        hdr.addStretch()
        stats = self.song_db.get_stats()
        self.stats_label = _label(
            f"📊 {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics",
            "subtitle")
        hdr.addWidget(self.stats_label)
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#313244;")
        root.addWidget(sep)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_job_tab()
        self._build_inject_tab()
        self._build_settings_tab()

        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ── Job Creation Tab ──────────────────────────────────────────────────────

    def _build_job_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # Template
        tpl_grp = QGroupBox("Template")
        tpl_lay = QVBoxLayout(tpl_grp)
        self.job_tpl_group = QButtonGroup(self)
        for name, val, desc in [
            ("Aurora", "aurora", "Full visual with gradients, spectrum, beat-sync"),
            ("Mono",   "mono",   "Minimal text-only, black/white alternating"),
            ("Onyx",   "onyx",   "Hybrid — word-by-word lyrics + spinning vinyl disc"),
        ]:
            rb = QRadioButton(f"{name}  —  {desc}")
            rb.setProperty("tval", val)
            if val == "aurora":
                rb.setChecked(True)
            self.job_tpl_group.addButton(rb)
            tpl_lay.addWidget(rb)

        path_row = QHBoxLayout()
        path_row.addWidget(_label("Output:", "muted"))
        self.output_path_label = _label(str(AURORA_JOBS_DIR), "muted")
        path_row.addWidget(self.output_path_label)
        path_row.addStretch()
        tpl_lay.addLayout(path_row)
        layout.addWidget(tpl_grp)
        self.job_tpl_group.buttonClicked.connect(self._on_template_change)

        # Song selection
        song_grp = QGroupBox("Song Selection")
        song_lay = QVBoxLayout(song_grp)
        self.song_tabs = QTabWidget()
        song_lay.addWidget(self.song_tabs)
        layout.addWidget(song_grp)

        # Manual entry sub-tab
        manual_w = QWidget()
        ml = QVBoxLayout(manual_w)
        ml.setSpacing(6)

        # ── Input fields ──────────────────────────────────────────────────────
        ml.addWidget(QLabel("Song Title (Artist - Song):"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. Drake - God's Plan")
        self.title_edit.textChanged.connect(self._check_database)
        ml.addWidget(self.title_edit)
        self.db_match_label = _label("", "muted")
        ml.addWidget(self.db_match_label)
        ml.addWidget(QLabel("YouTube URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.textChanged.connect(self._on_url_changed)
        ml.addWidget(self.url_edit)
        self.url_error_label = _label("", "error")
        self.url_error_label.setVisible(False)
        ml.addWidget(self.url_error_label)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("Start (MM:SS):"))
        self.start_edit = QLineEdit("00:00")
        self.start_edit.setFixedWidth(70)
        tr.addWidget(self.start_edit)
        tr.addSpacing(20)
        tr.addWidget(QLabel("End (MM:SS):"))
        self.end_edit = QLineEdit("01:01")
        self.end_edit.setFixedWidth(70)
        tr.addWidget(self.end_edit)
        tr.addStretch()
        ml.addLayout(tr)

        # ── Add to queue button ───────────────────────────────────────────────
        add_row = QHBoxLayout()
        self.add_job_btn = QPushButton("＋  Add to Queue")
        self.add_job_btn.setObjectName("accent")
        self.add_job_btn.clicked.connect(self._add_job_to_queue)
        add_row.addWidget(self.add_job_btn)
        add_row.addStretch()
        ml.addLayout(add_row)

        # ── Separator ─────────────────────────────────────────────────────────
        q_sep = QFrame()
        q_sep.setFrameShape(QFrame.Shape.HLine)
        q_sep.setStyleSheet("color:#313244; margin:4px 0;")
        ml.addWidget(q_sep)

        # ── Queue header with counter ─────────────────────────────────────────
        q_hdr = QHBoxLayout()
        q_hdr.addWidget(QLabel("Job Queue:"))
        q_hdr.addStretch()
        self.queue_counter_label = _label("0 / 12", "muted")
        q_hdr.addWidget(self.queue_counter_label)
        ml.addLayout(q_hdr)

        # ── Queue list ────────────────────────────────────────────────────────
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(90)
        self.queue_list.setMaximumHeight(120)
        self.queue_list.itemSelectionChanged.connect(
            lambda: self.remove_job_btn.setEnabled(
                bool(self.queue_list.selectedItems()) and not self.is_processing))
        ml.addWidget(self.queue_list)

        # ── Queue action buttons ──────────────────────────────────────────────
        q_btn_row = QHBoxLayout()
        self.remove_job_btn = QPushButton("✕  Remove Selected")
        self.remove_job_btn.setObjectName("muted")
        self.remove_job_btn.setEnabled(False)
        self.remove_job_btn.clicked.connect(self._remove_from_queue)
        q_btn_row.addWidget(self.remove_job_btn)
        self.clear_queue_btn = QPushButton("🗑  Clear Queue")
        self.clear_queue_btn.setObjectName("danger")
        self.clear_queue_btn.setEnabled(False)
        self.clear_queue_btn.clicked.connect(self._clear_queue)
        q_btn_row.addWidget(self.clear_queue_btn)
        q_btn_row.addStretch()
        ml.addLayout(q_btn_row)

        ml.addStretch()
        self.song_tabs.addTab(manual_w, "  ✏️ Manual Entry  ")

        # Smart Picker sub-tab
        smart_w = QWidget()
        sl = QVBoxLayout(smart_w)
        sl.setSpacing(6)
        desc_lbl = _label(
            "Smart Picker automatically selects songs from your database.\n"
            "It ensures fair rotation — no song used twice until all used once.", "muted")
        desc_lbl.setWordWrap(True)
        sl.addWidget(desc_lbl)
        self.smart_stats_label = QLabel("Loading stats...")
        sl.addWidget(self.smart_stats_label)
        ref_btn = QPushButton("🔄 Refresh Stats")
        ref_btn.clicked.connect(self._refresh_smart_picker_stats)
        sl.addWidget(ref_btn)
        sl.addWidget(QLabel("Next songs to be selected:"))
        self.smart_listbox = QListWidget()
        self.smart_listbox.setMinimumHeight(150)
        sl.addWidget(self.smart_listbox)
        self.smart_warning_label = _label("", "warning")
        sl.addWidget(self.smart_warning_label)
        sl.addStretch()
        self.song_tabs.addTab(smart_w, "  🤖 Smart Picker  ")
        self.song_tabs.currentChanged.connect(self._on_song_mode_changed)
        self._refresh_smart_picker_stats()

        # Job settings
        js_grp = QGroupBox("Job Settings")
        js_lay = QHBoxLayout(js_grp)
        js_lay.addWidget(QLabel("Number of Jobs:"))
        self.jobs_combo = QComboBox()
        self.jobs_combo.addItems(["1", "3", "6", "12"])
        self.jobs_combo.setCurrentText("12")
        self.jobs_combo.setFixedWidth(70)
        self.jobs_combo.currentIndexChanged.connect(self._on_jobs_count_changed)
        js_lay.addWidget(self.jobs_combo)
        js_lay.addSpacing(20)
        js_lay.addWidget(QLabel("Whisper Model:"))
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.whisper_combo.setCurrentText(self.settings.get('whisper_model', 'small'))
        self.whisper_combo.setFixedWidth(110)
        js_lay.addWidget(self.whisper_combo)
        js_lay.addStretch()
        self.job_warning_label = _label("", "warning")
        js_lay.addWidget(self.job_warning_label)
        self.delete_jobs_btn = QPushButton("Delete Existing Jobs")
        self.delete_jobs_btn.setObjectName("danger")
        self.delete_jobs_btn.setVisible(False)
        self.delete_jobs_btn.clicked.connect(self._delete_existing_jobs)
        js_lay.addWidget(self.delete_jobs_btn)
        layout.addWidget(js_grp)
        self._check_existing_jobs()

        # Progress
        prog_grp = QGroupBox("Progress")
        prog_lay = QVBoxLayout(prog_grp)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        prog_lay.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        prog_lay.addWidget(self.status_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(130)
        prog_lay.addWidget(self.log_text)
        layout.addWidget(prog_grp)

        # Buttons
        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("🚀 Generate Jobs")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.clicked.connect(self._start_generation)
        self.generate_btn.setEnabled(False)   # enabled when queue is full (manual) or always (smart)
        btn_row.addWidget(self.generate_btn)
        self.cancel_btn = QPushButton("✕  Cancel")
        self.cancel_btn.setObjectName("muted")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        btn_row.addWidget(self.cancel_btn)
        open_btn = QPushButton("📂  Open Jobs Folder")
        open_btn.clicked.connect(self._open_jobs_folder)
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.tabs.addTab(_scrollable(page), "  📁 Job Creation  ")

    # ── JSX Injection Tab ─────────────────────────────────────────────────────

    def _build_inject_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # Template selector
        tpl_grp = QGroupBox("Individual Template Injection")
        tpl_lay = QVBoxLayout(tpl_grp)
        self.inject_tpl_group = QButtonGroup(self)
        for name, val, desc in [
            ("Aurora", "aurora", "Full visual template"),
            ("Mono",   "mono",   "Minimal text template"),
            ("Onyx",   "onyx",   "Hybrid vinyl template"),
        ]:
            rb = QRadioButton(f"{name}  —  {desc}")
            rb.setProperty("tval", val)
            if val == "aurora":
                rb.setChecked(True)
            self.inject_tpl_group.addButton(rb)
            tpl_lay.addWidget(rb)
        self.inject_tpl_group.buttonClicked.connect(self._update_inject_status)
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

        self.inject_jobs_label     = status_row("Jobs:")
        self.inject_template_label = status_row("Template File:")
        self.inject_ae_label       = status_row("After Effects:")

        ref_row = QHBoxLayout()
        ref_btn = QPushButton("🔄  Refresh Status")
        ref_btn.setObjectName("muted")
        ref_btn.clicked.connect(self._update_inject_status)
        ref_row.addWidget(ref_btn)
        ref_row.addStretch()
        status_lay.addLayout(ref_row)

        install_lbl = _label(f"Install Dir: {INSTALL_DIR}", "muted")
        status_lay.addWidget(install_lbl)
        layout.addWidget(status_grp)

        self.inject_btn = QPushButton("Launch After Effects & Inject")
        self.inject_btn.setObjectName("primary")
        self.inject_btn.clicked.connect(self._run_injection)
        layout.addWidget(self.inject_btn)

        info = _label(
            "This will launch AE, open the template, and inject job data.\n"
            "After injection, review the comps and manually add to render queue.", "muted")
        layout.addWidget(info)

        # Batch render
        batch_grp = QGroupBox("Batch Render All Templates")
        batch_lay = QVBoxLayout(batch_grp)
        batch_lay.addWidget(QLabel("Templates Ready:"))
        self.batch_status_labels = {}
        for name, val, _ in [("Aurora","aurora",""), ("Mono","mono",""), ("Onyx","onyx","")]:
            lbl = QLabel(f"  {name}: Checking...")
            self.batch_status_labels[val] = lbl
            batch_lay.addWidget(lbl)

        self.batch_status_label  = QLabel("Status: Idle")
        self.batch_progress_bar  = QProgressBar()
        self.batch_progress_bar.setRange(0, 100)
        self.batch_current_label = _label("", "muted")
        batch_lay.addWidget(self.batch_status_label)
        batch_lay.addWidget(self.batch_progress_bar)
        batch_lay.addWidget(self.batch_current_label)

        bb_row = QHBoxLayout()
        self.render_all_btn = QPushButton("Render All")
        self.render_all_btn.setObjectName("primary")
        self.render_all_btn.clicked.connect(self._start_batch_render)
        bb_row.addWidget(self.render_all_btn)
        self.batch_cancel_btn = QPushButton("✕  Cancel")
        self.batch_cancel_btn.setObjectName("muted")
        self.batch_cancel_btn.setEnabled(False)
        self.batch_cancel_btn.clicked.connect(self._cancel_batch_render)
        bb_row.addWidget(self.batch_cancel_btn)
        bb_row.addStretch()
        batch_lay.addLayout(bb_row)

        batch_info = _label(
            "Renders all templates sequentially (Aurora → Mono → Onyx).\n"
            "Each template auto-injects, renders, then closes. Requires 2+ templates.", "muted")
        batch_lay.addWidget(batch_info)
        layout.addWidget(batch_grp)
        layout.addStretch()

        self.tabs.addTab(_scrollable(page), "  🚀 JSX Injection  ")
        self._update_inject_status()
        self._update_batch_status()

    # ── Settings Tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # After Effects
        ae_grp = QGroupBox("Adobe After Effects")
        ae_lay = QVBoxLayout(ae_grp)
        ae_row = QHBoxLayout()
        ae_row.addWidget(QLabel("Path:"))
        self.ae_path_edit = QLineEdit(self.settings.get('after_effects_path', '') or '')
        self.ae_path_edit.setPlaceholderText(
            "C:/Program Files/Adobe/.../AfterFX.exe")
        ae_row.addWidget(self.ae_path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_ae_path)
        ae_row.addWidget(browse_btn)
        detect_btn = QPushButton("🔍  Auto-Detect")
        detect_btn.clicked.connect(self._auto_detect_ae_click)
        ae_row.addWidget(detect_btn)
        ae_lay.addLayout(ae_row)
        self.ae_status_label = QLabel("")
        ae_lay.addWidget(self.ae_status_label)
        self._update_ae_status()
        layout.addWidget(ae_grp)

        # Genius API
        genius_grp = QGroupBox("Genius API")
        genius_lay = QVBoxLayout(genius_grp)
        genius_lay.addWidget(QLabel("API Token:"))
        self.genius_edit = QLineEdit(self.settings.get('genius_api_token', '') or '')
        self.genius_edit.setEchoMode(QLineEdit.EchoMode.Password)
        genius_lay.addWidget(self.genius_edit)
        genius_lay.addWidget(_label("Get your token at: https://genius.com/api-clients", "muted"))
        layout.addWidget(genius_grp)

        # FFmpeg
        ffmpeg_grp = QGroupBox("FFmpeg")
        ffmpeg_lay = QVBoxLayout(ffmpeg_grp)
        self.ffmpeg_status_label = QLabel("Checking...")
        ffmpeg_lay.addWidget(self.ffmpeg_status_label)
        self._check_ffmpeg()
        layout.addWidget(ffmpeg_grp)

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_all_settings)
        layout.addWidget(save_btn)

        # Paths info
        paths_grp = QGroupBox("Installation Paths (Read-Only)")
        paths_lay = QVBoxLayout(paths_grp)
        paths_lbl = _label(
            f"Install Dir:  {INSTALL_DIR}\n"
            f"Templates:    {TEMPLATES_DIR}\n"
            f"Aurora Jobs:  {AURORA_JOBS_DIR}\n"
            f"Mono Jobs:    {MONO_JOBS_DIR}\n"
            f"Onyx Jobs:    {ONYX_JOBS_DIR}\n"
            f"Database:     {DATABASE_DIR}", "muted")
        f2 = QFont("Consolas")
        f2.setPointSize(9)
        paths_lbl.setFont(f2)
        paths_lay.addWidget(paths_lbl)
        layout.addWidget(paths_grp)
        layout.addStretch()

        self.tabs.addTab(_scrollable(page), "  ⚙ Settings  ")

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_tab_changed(self, index):
        if index == 1:
            self._update_inject_status()
            self._update_batch_status()

    def _on_template_change(self):
        t = self._job_template()
        self.output_path_label.setText(str(JOBS_DIRS.get(t, AURORA_JOBS_DIR)))
        self._check_existing_jobs()

    def _on_song_mode_changed(self, index):
        self.use_smart_picker = (index == 1)
        if self.use_smart_picker:
            self._refresh_smart_picker_stats()
        self._update_generate_btn_state()

    def _on_jobs_count_changed(self, _index):
        self._update_queue_counter()
        self._update_generate_btn_state()
        if self.use_smart_picker:
            self._refresh_smart_picker_stats()

    def _update_queue_counter(self):
        n     = int(self.jobs_combo.currentText())
        count = len(self._job_queue)
        self.queue_counter_label.setText(f"{count} / {n}")

    def _update_generate_btn_state(self):
        if self.is_processing:
            self.generate_btn.setEnabled(False)
            return
        if self.use_smart_picker:
            self.generate_btn.setEnabled(True)
        else:
            n = int(self.jobs_combo.currentText())
            self.generate_btn.setEnabled(len(self._job_queue) >= n)

    def _add_job_to_queue(self):
        title = self.title_edit.text().strip()
        url   = self.url_edit.text().strip()
        start = self.start_edit.text().strip()
        end   = self.end_edit.text().strip()
        n     = int(self.jobs_combo.currentText())

        if len(self._job_queue) >= n:
            QMessageBox.warning(self, "Queue Full",
                f"Queue already has {n} jobs.\n"
                "Increase the job count or clear the queue first.")
            return

        if not title:
            QMessageBox.critical(self, "Missing Info", "Song title is required.")
            return

        # If the URL field is empty but the song is cached, use the cached URL
        cached = self.song_db.get_song(title)
        effective_url = url or (cached['youtube_url'] if cached else "")

        errors = self._validate_song_record(effective_url, start, end)
        if errors:
            QMessageBox.critical(self, "Invalid Job Data",
                "Fix the following before adding this job to the queue:\n\n• " +
                "\n• ".join(errors))
            return

        self._job_queue.append(
            {'title': title, 'url': effective_url, 'start': start, 'end': end})
        self._rebuild_queue_list()
        self._update_queue_counter()
        self._update_generate_btn_state()

        # Clear fields and highlights for next entry
        self.title_edit.clear()
        self.url_edit.clear()
        self.start_edit.setText("00:00")
        self.end_edit.setText("01:01")
        self.db_match_label.setText("")
        for f in (self.url_edit, self.start_edit, self.end_edit):
            self._highlight_field(f, False)

    def _remove_from_queue(self):
        row = self.queue_list.currentRow()
        if row < 0:
            return
        self._job_queue.pop(row)
        self._rebuild_queue_list()
        self._update_queue_counter()
        self._update_generate_btn_state()

    def _clear_queue(self):
        if not self._job_queue:
            return
        reply = QMessageBox.question(
            self, "Clear Queue",
            f"Are you sure you want to delete all {len(self._job_queue)} job(s) from the queue?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._job_queue.clear()
        self._rebuild_queue_list()
        self._update_queue_counter()
        self._update_generate_btn_state()

    def _rebuild_queue_list(self):
        self.queue_list.clear()
        for i, job in enumerate(self._job_queue, 1):
            self.queue_list.addItem(
                f"{i:2}. {job['title'][:35]:<35}  {job['start']} → {job['end']}")
        self.clear_queue_btn.setEnabled(bool(self._job_queue))
        self.remove_job_btn.setEnabled(False)

    def _job_template(self):
        btn = self.job_tpl_group.checkedButton()
        return btn.property("tval") if btn else "aurora"

    def _inject_template(self):
        btn = self.inject_tpl_group.checkedButton()
        return btn.property("tval") if btn else "aurora"

    # ── Smart Picker ──────────────────────────────────────────────────────────

    def _refresh_smart_picker_stats(self):
        try:
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            stats  = picker.get_database_stats()
            if stats['total_songs'] == 0:
                _set_label_style(self.smart_stats_label, "warning")
                self.smart_stats_label.setText(
                    "📊 Database is empty. Add songs via Manual Entry first.")
                self.smart_warning_label.setText(
                    "⚠️ No songs available. Use Manual Entry to add songs.")
                self.smart_listbox.clear()
                return

            self.smart_stats_label.setText(
                f"📊 Total: {stats['total_songs']} | Unused: {stats['unused_songs']} | "
                f"Uses: {stats['min_uses']}–{stats['max_uses']} (avg {stats['avg_uses']})")

            num_jobs = int(self.jobs_combo.currentText())
            songs    = picker.get_available_songs(num_songs=num_jobs)
            self.smart_listbox.clear()
            for i, s in enumerate(songs, 1):
                tag = "🆕 new" if s['use_count'] == 1 else f"📊 {s['use_count']}x"
                self.smart_listbox.addItem(
                    f"{i:2}. {s['song_title'][:45]:<45} ({tag})")
            if len(songs) < num_jobs:
                self.smart_warning_label.setText(
                    f"⚠️ Only {len(songs)} songs available, {num_jobs} requested.")
            else:
                self.smart_warning_label.setText("")
        except Exception as e:
            _set_label_style(self.smart_stats_label, "error")
            self.smart_stats_label.setText(f"❌ Error: {e}")

    # ── Field validation helpers ──────────────────────────────────────────────

    @staticmethod
    def _highlight_field(field, has_error: bool):
        """Apply or clear a red border on an input field."""
        if has_error:
            field.setStyleSheet(
                "border: 1px solid #f38ba8; border-radius: 4px;")
        else:
            field.setStyleSheet("")  # revert to global app stylesheet

    def _on_url_changed(self, text):
        url = text.strip()
        if url and not _VALID_YT.search(url):
            self._highlight_field(self.url_edit, True)
            self.url_error_label.setText("⚠  This is not a valid YouTube URL")
            self.url_error_label.setVisible(True)
        else:
            self._highlight_field(self.url_edit, False)
            self.url_error_label.setVisible(False)

    def _validate_song_record(self, url, start, end):
        """
        Validate a song's core database fields.
        Returns a list of human-readable error strings (empty = all valid).
        """
        errors = []

        # ── URL ──
        if not url or not url.strip():
            errors.append("YouTube URL is missing")
        elif url.strip().lower() == "unknown":
            errors.append(
                "YouTube URL is set to 'unknown' — this song was never "
                "given a real YouTube link")
        elif not _VALID_YT.search(url):
            errors.append(
                f"YouTube URL is not a valid YouTube watch link: '{url[:70]}'")

        # ── Times ──
        def _parse(val, label):
            if not val or not val.strip():
                errors.append(f"{label} is missing")
                return None
            if not _VALID_TIME.match(val.strip()):
                errors.append(
                    f"{label} '{val}' is not in MM:SS format (e.g. 00:30)")
                return None
            try:
                m, s = val.strip().split(':')
                return int(m) * 60 + int(s)
            except ValueError:
                errors.append(
                    f"{label} '{val}' contains non-numeric characters")
                return None

        s_sec = _parse(start, "Start time")
        e_sec = _parse(end,   "End time")
        if s_sec is not None and e_sec is not None and s_sec >= e_sec:
            errors.append(
                f"Start time ({start}) must be before end time ({end})")

        return errors

    # ── Database check ────────────────────────────────────────────────────────

    def _check_database(self):
        title = self.title_edit.text().strip()
        if len(title) < 3:
            self.db_match_label.setText("")
            for f in (self.url_edit, self.start_edit, self.end_edit):
                self._highlight_field(f, False)
            return
        cached = self.song_db.get_song(title)
        if cached:
            url   = cached['youtube_url'] or ""
            start = cached['start_time']  or ""
            end   = cached['end_time']    or ""
            self.url_edit.setText(url)
            self.start_edit.setText(start)
            self.end_edit.setText(end)

            errors = self._validate_song_record(url, start, end)

            # Highlight each field individually so the user knows exactly what to fix
            self._highlight_field(self.url_edit,
                                  any("URL" in e for e in errors))
            self._highlight_field(self.start_edit,
                                  any("Start" in e for e in errors))
            self._highlight_field(self.end_edit,
                                  any("End" in e or "end time" in e.lower()
                                      for e in errors))

            if errors:
                _set_label_style(self.db_match_label, "error")
                self.db_match_label.setText(
                    "⚠ Found in database but has invalid data — "
                    "fix the highlighted field(s):  " +
                    "  |  ".join(errors))
            else:
                _set_label_style(self.db_match_label, "success")
                self.db_match_label.setText(
                    "✓ Found in database! URL and timestamps loaded.")
        else:
            for f in (self.url_edit, self.start_edit, self.end_edit):
                self._highlight_field(f, False)
            matches = self.song_db.search_songs(title)
            if matches:
                _set_label_style(self.db_match_label, "warning")
                self.db_match_label.setText(
                    f"Similar: {', '.join([m[0][:25] for m in matches[:3]])}")
            else:
                _set_label_style(self.db_match_label, "muted")
                self.db_match_label.setText("New song — will be saved to database.")

    # ── Jobs helpers ──────────────────────────────────────────────────────────

    def _check_existing_jobs(self):
        t = self._job_template()
        d = JOBS_DIRS.get(t)
        if not d or not d.exists():
            self.job_warning_label.setText("")
            self.delete_jobs_btn.setVisible(False)
            return
        existing = list(d.glob("job_*"))
        if existing:
            self.job_warning_label.setText(
                f"⚠️ {len(existing)} existing job(s) detected")
            self.delete_jobs_btn.setVisible(True)
        else:
            self.job_warning_label.setText("")
            self.delete_jobs_btn.setVisible(False)

    def _delete_existing_jobs(self):
        if self.is_processing:
            QMessageBox.warning(self, "Processing",
                                "Cannot delete jobs while processing.")
            return
        t = self._job_template()
        d = JOBS_DIRS.get(t)
        existing = list(d.glob("job_*"))
        if not existing:
            return
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete {len(existing)} job folder(s) from {t.upper()}?\n\nCannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        for j in existing:
            shutil.rmtree(j)
        QMessageBox.information(self, "Deleted",
                                f"Deleted {len(existing)} job folder(s).")
        self._check_existing_jobs()

    def _open_jobs_folder(self):
        t = self._job_template()
        d = JOBS_DIRS.get(t)
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    # ── Inject helpers ────────────────────────────────────────────────────────

    def _update_inject_status(self):
        t    = self._inject_template()
        d    = JOBS_DIRS.get(t)
        jobs_ok = template_ok = ae_ok = False

        if d and d.exists():
            jf = list(d.glob("job_*"))
            if jf:
                self.inject_jobs_label.setText(
                    f"✓ {len(jf)} job(s) found in {d.name}")
                _set_label_style(self.inject_jobs_label, "success")
                jobs_ok = True
            else:
                self.inject_jobs_label.setText(f"✗ No jobs in {d}")
                _set_label_style(self.inject_jobs_label, "error")
        else:
            self.inject_jobs_label.setText("✗ Folder not found")
            _set_label_style(self.inject_jobs_label, "error")

        tp = TEMPLATE_PATHS.get(t)
        if tp and tp.exists():
            self.inject_template_label.setText(f"✓ {tp.name}")
            _set_label_style(self.inject_template_label, "success")
            template_ok = True
        else:
            self.inject_template_label.setText(
                f"✗ Not found: {tp.name if tp else 'Unknown'}")
            _set_label_style(self.inject_template_label, "error")

        ae = self.settings.get('after_effects_path')
        if ae and Path(ae).exists():
            self.inject_ae_label.setText("✓ Found")
            _set_label_style(self.inject_ae_label, "success")
            ae_ok = True
        else:
            self.inject_ae_label.setText("✗ Not configured — go to Settings")
            _set_label_style(self.inject_ae_label, "error")

        self.inject_btn.setEnabled(jobs_ok and template_ok and ae_ok)

    def _update_ae_status(self):
        ae = getattr(self, 'ae_path_edit', None)
        path = ae.text() if ae else (self.settings.get('after_effects_path') or '')
        if path and Path(path).exists():
            self.ae_status_label.setText("✓ After Effects found")
            _set_label_style(self.ae_status_label, "success")
        elif path:
            self.ae_status_label.setText("✗ Path not found")
            _set_label_style(self.ae_status_label, "error")
        else:
            self.ae_status_label.setText("⚠ Not configured")
            _set_label_style(self.ae_status_label, "warning")

    def _check_ffmpeg(self):
        try:
            r = subprocess.run(['ffmpeg', '-version'],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                self.ffmpeg_status_label.setText("✓ FFmpeg found in PATH")
                _set_label_style(self.ffmpeg_status_label, "success")
            else:
                self.ffmpeg_status_label.setText("✗ FFmpeg not working properly")
                _set_label_style(self.ffmpeg_status_label, "error")
        except FileNotFoundError:
            self.ffmpeg_status_label.setText(
                "✗ FFmpeg not found — install and add to PATH")
            _set_label_style(self.ffmpeg_status_label, "error")
        except Exception as e:
            self.ffmpeg_status_label.setText(f"✗ Error: {e}")
            _set_label_style(self.ffmpeg_status_label, "error")

    def _browse_ae_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select AfterFX.exe",
            "C:/Program Files/Adobe",
            "Executable (*.exe);;All files (*.*)")
        if path:
            self.ae_path_edit.setText(path)
            self._update_ae_status()

    def _auto_detect_ae_click(self):
        detected = self._auto_detect_after_effects()
        if detected:
            self.ae_path_edit.setText(detected)
            self._update_ae_status()
            QMessageBox.information(self, "Found",
                                    f"After Effects found:\n{detected}")
        else:
            QMessageBox.warning(self, "Not Found",
                                "Could not auto-detect After Effects.\n\nPlease browse manually.")

    def _save_all_settings(self):
        self.settings['after_effects_path'] = self.ae_path_edit.text()
        self.settings['genius_api_token']   = self.genius_edit.text()
        self.settings['whisper_model']      = self.whisper_combo.currentText()
        Config.GENIUS_API_TOKEN = self.genius_edit.text()
        Config.WHISPER_MODEL    = self.whisper_combo.currentText()
        self._save_settings()
        env = INSTALL_DIR / ".env"
        with open(env, 'w') as f:
            f.write(f"GENIUS_API_TOKEN={self.genius_edit.text()}\n")
            f.write(f"WHISPER_MODEL={self.whisper_combo.currentText()}\n")
        QMessageBox.information(self, "Saved", "Settings saved successfully!")
        self._update_inject_status()

    # ── JSX Injection ─────────────────────────────────────────────────────────

    def _run_injection(self):
        t   = self._inject_template()
        ae  = self.settings.get('after_effects_path')
        tp  = TEMPLATE_PATHS.get(t)
        d   = JOBS_DIRS.get(t)
        jsx = JSX_SCRIPTS.get(t)
        if self._log:
            self._log.section(f"JSX injection — template={t.upper()}, jsx={jsx}")
        try:
            src = BUNDLED_JSX_DIR / jsx
            if not src.exists():
                src = ASSETS_DIR / "scripts" / "JSX" / jsx
            if not src.exists():
                if self._log:
                    self._log.error(f"JSX script not found: {jsx}")
                QMessageBox.critical(self, "Error",
                    f"JSX script not found: {jsx}\n\nPlease reinstall.")
                return
            tmp = Path(tempfile.gettempdir()) / "Apollova"
            tmp.mkdir(exist_ok=True)
            dst = tmp / jsx
            shutil.copy(src, dst)
            self._prepare_jsx_with_path(dst, d, tp)
            if self._log:
                self._log.info(f"JSX prepared at {dst} | jobs={d} | template={tp}")
        except Exception as e:
            tb = traceback.format_exc()
            if self._log:
                self._log.error(f"JSX preparation failed: {type(e).__name__}: {e}\n{tb}")
            QMessageBox.critical(self, "Error", f"Failed to prepare JSX:\n{e}")
            return
        try:
            subprocess.Popen([ae, "-r", str(dst)])
            if self._log:
                self._log.info(f"After Effects launched: {ae}")
            QMessageBox.information(self, "Launched",
                f"After Effects is launching…\n\nTemplate: {tp.name}\nJobs: {d}\n\n"
                "The script will open the project and inject the jobs.")
        except Exception as e:
            tb = traceback.format_exc()
            if self._log:
                self._log.error(f"After Effects launch failed: {type(e).__name__}: {e}\n{tb}")
            QMessageBox.critical(self, "Error",
                                 f"Failed to launch After Effects:\n{e}")

    def _prepare_jsx_with_path(self, jsx_path, jobs_dir,
                               template_path, auto_render=False):
        with open(jsx_path, 'r', encoding='utf-8') as f:
            c = f.read()
        c = c.replace('{{JOBS_PATH}}',     str(jobs_dir).replace('\\', '/'))
        c = c.replace('{{TEMPLATE_PATH}}', str(template_path).replace('\\', '/'))
        c = c.replace('{{AUTO_RENDER}}',   'true' if auto_render else 'false')
        with open(jsx_path, 'w', encoding='utf-8') as f:
            f.write(c)

    # ── Batch Render ──────────────────────────────────────────────────────────

    def _update_batch_status(self):
        ready = []
        ae    = self.settings.get('after_effects_path')
        ae_ok = ae and Path(ae).exists()
        for t in ['aurora', 'mono', 'onyx']:
            d   = JOBS_DIRS.get(t)
            tp  = TEMPLATE_PATHS.get(t)
            jsx = JSX_SCRIPTS.get(t)
            jobs_ok = d and d.exists() and list(d.glob("job_*"))
            tpl_ok  = tp and tp.exists()
            src     = BUNDLED_JSX_DIR / jsx if jsx else None
            if src and not src.exists():
                src = ASSETS_DIR / "scripts" / "JSX" / jsx
            jsx_ok = src and src.exists()
            lbl = self.batch_status_labels[t]
            if jobs_ok:
                cnt = len(list(d.glob("job_*")))
                if tpl_ok and jsx_ok:
                    lbl.setText(f"  {t.capitalize()}: {cnt} jobs ready")
                    _set_label_style(lbl, "success")
                    ready.append(t)
                elif not tpl_ok:
                    lbl.setText(f"  {t.capitalize()}: {cnt} jobs (no template)")
                    _set_label_style(lbl, "warning")
                else:
                    lbl.setText(f"  {t.capitalize()}: {cnt} jobs (JSX missing)")
                    _set_label_style(lbl, "warning")
            else:
                lbl.setText(f"  {t.capitalize()}: No jobs")
                _set_label_style(lbl, "normal")
        self.render_all_btn.setEnabled(
            len(ready) >= 2 and ae_ok and not self.batch_render_active)
        return ready

    def _start_batch_render(self):
        ready = self._update_batch_status()
        if len(ready) < 2:
            QMessageBox.critical(self, "Error",
                "Need at least 2 templates with jobs.")
            return
        lines = ["Ready to render:"]
        for t in ready:
            lines.append(f"  - {t.capitalize()}: {len(list(JOBS_DIRS[t].glob('job_*')))} jobs")
        lines += ["", "This will take a while. Continue?"]
        reply = QMessageBox.question(self, "Confirm Batch Render", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.batch_render_active    = True
        self.batch_render_cancelled = False
        self.batch_results          = {}
        self.render_all_btn.setEnabled(False)
        self.batch_cancel_btn.setEnabled(True)
        self.inject_btn.setEnabled(False)
        threading.Thread(target=self._batch_render_thread,
                         args=(ready,), daemon=True).start()

    def _cancel_batch_render(self):
        reply = QMessageBox.question(self, "Cancel",
            "Cancel batch? Current template will finish first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.batch_render_cancelled = True
            self.batch_status_label.setText("Status: Cancelling…")

    def _batch_render_thread(self, templates):
        total = len(templates)
        for idx, t in enumerate(templates):
            if self.batch_render_cancelled:
                self.signals.batch_progress.emit(
                    "Status: Cancelled", idx / total * 100, "Cancelled")
                break
            self.signals.batch_progress.emit(
                f"Status: Rendering {t.capitalize()} ({idx+1}/{total})",
                idx / total * 100,
                f"Launching After Effects for {t.capitalize()}…")
            ok, err = self._run_batch_template(t)
            self.batch_results[t] = {'success': ok, 'error': err}
            if ok:
                self.signals.batch_template_status.emit(
                    t, f"  {t.capitalize()}: Complete ✓")
            else:
                self.signals.batch_template_status.emit(
                    t, f"  {t.capitalize()}: Failed — {err}")
        self.signals.batch_finished.emit(dict(self.batch_results))

    def _run_batch_template(self, t):
        ae  = self.settings.get('after_effects_path')
        tp  = TEMPLATE_PATHS.get(t)
        d   = JOBS_DIRS.get(t)
        jsx = JSX_SCRIPTS.get(t)
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
            self._prepare_jsx_with_path(dst, d, tp, auto_render=True)
            err_log = d / "batch_error.txt"
            if err_log.exists():
                err_log.unlink()
            p = subprocess.Popen([ae, "-r", str(dst)])
            p.wait()
            if err_log.exists():
                return False, err_log.read_text().strip()
            return True, None
        except Exception as e:
            return False, str(e)

    def _batch_update_progress(self, status, progress, current):
        self.batch_status_label.setText(status)
        self.batch_progress_bar.setValue(int(progress))
        self.batch_current_label.setText(current)

    def _batch_update_template_status_slot(self, template, text):
        lbl = self.batch_status_labels.get(template)
        if lbl:
            lbl.setText(text)
            style = "success" if "Complete" in text else "error"
            _set_label_style(lbl, style)

    def _batch_render_complete(self, results):
        self.batch_render_active = False
        self.render_all_btn.setEnabled(True)
        self.batch_cancel_btn.setEnabled(False)
        self.inject_btn.setEnabled(True)
        self.batch_progress_bar.setValue(100)
        sc = sum(1 for r in results.values() if r['success'])
        fc = sum(1 for r in results.values() if not r['success'])
        if self.batch_render_cancelled:
            self.batch_status_label.setText("Status: Cancelled")
            self.batch_current_label.setText(f"Completed {sc} before cancellation")
        else:
            self.batch_status_label.setText("Status: Complete")
            self.batch_current_label.setText(f"Success: {sc}, Failed: {fc}")
        lines = ["Batch Render Complete\n"]
        for t, r in results.items():
            lines.append(
                f"{t.capitalize()}: {'Success' if r['success'] else 'Failed — ' + str(r['error'])}")
        if self.batch_render_cancelled:
            lines.append("\nCancelled by user.")
        QMessageBox.information(self, "Batch Render Complete", "\n".join(lines))
        self._update_batch_status()

    # ── Generation ────────────────────────────────────────────────────────────

    def _validate_inputs(self):
        errors = []
        if self.use_smart_picker:
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            stats  = picker.get_database_stats()
            if stats['total_songs'] == 0:
                errors.append("Database empty. Add songs via Manual Entry first.")
            else:
                songs = picker.get_available_songs(
                    num_songs=int(self.jobs_combo.currentText()))
                if not songs:
                    errors.append("No songs available in database.")
                else:
                    # Validate every song upfront before a single job starts
                    bad = []
                    for s in songs:
                        song_errors = self._validate_song_record(
                            s['youtube_url'], s['start_time'], s['end_time'])
                        if song_errors:
                            bad.append((s['song_title'], song_errors))
                    if bad:
                        lines = [
                            f"{len(bad)} of the {len(songs)} selected song(s) "
                            f"have invalid data and cannot be processed:\n"]
                        for song_title, errs in bad:
                            lines.append(f"• {song_title}:")
                            for e in errs:
                                lines.append(f"    – {e}")
                        lines.append(
                            "\nFix these entries in your database "
                            "(Settings → Database Editor) before generating.")
                        errors.append("\n".join(lines))
        else:
            n = int(self.jobs_combo.currentText())
            if len(self._job_queue) < n:
                errors.append(
                    f"Queue has {len(self._job_queue)} / {n} jobs. "
                    "Add all jobs before generating.")
        if errors:
            QMessageBox.critical(self, "Validation Error", "\n\n".join(errors))
            return False
        return True

    def _lock_inputs(self, lock):
        for w in [self.title_edit, self.url_edit, self.start_edit,
                  self.end_edit, self.jobs_combo, self.whisper_combo,
                  self.add_job_btn]:
            w.setEnabled(not lock)
        for btn in self.job_tpl_group.buttons():
            btn.setEnabled(not lock)
        self.remove_job_btn.setEnabled(False)
        self.clear_queue_btn.setEnabled(not lock and bool(self._job_queue))

    def _start_generation(self):
        if not self._validate_inputs():
            return
        t    = self._job_template()
        d    = JOBS_DIRS.get(t)
        existing = list(d.glob("job_*")) if d.exists() else []

        if self.use_smart_picker:
            num  = int(self.jobs_combo.currentText())
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            songs  = picker.get_available_songs(num_songs=num)
            sl = "\n".join(
                [f"  {i+1}. {s['song_title'][:40]}" for i, s in enumerate(songs[:12])])
            if len(songs) > 12:
                sl += f"\n  … and {len(songs)-12} more"
            reply = QMessageBox.question(self, "Smart Picker Confirmation",
                f"Generate {len(songs)} jobs for {t.upper()}?\n\nSongs:\n{sl}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        if existing:
            complete   = [j for j in existing if (j / "job_data.json").exists()]
            incomplete = [j for j in existing if not (j / "job_data.json").exists()]
            detail = f"Found {len(existing)} existing job(s)"
            if complete:
                detail += f"\n  • {len(complete)} complete"
            if incomplete:
                detail += f"\n  • {len(incomplete)} incomplete / failed"

            dlg = QMessageBox(self)
            dlg.setWindowTitle("Existing Jobs")
            dlg.setText("Existing jobs detected")
            dlg.setInformativeText(
                detail + "\n\n"
                "Delete All  —  wipe everything and start fresh\n"
                "Resume  —  skip completed jobs, retry the rest\n"
                "Cancel  —  do nothing"
            )
            delete_btn = dlg.addButton("Delete All",
                                       QMessageBox.ButtonRole.DestructiveRole)
            resume_btn = dlg.addButton("Resume",
                                       QMessageBox.ButtonRole.AcceptRole)
            dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            dlg.setDefaultButton(resume_btn)
            dlg.exec()

            clicked = dlg.clickedButton()
            if clicked == delete_btn:
                for j in existing:
                    shutil.rmtree(j)
                self._resume_mode = False
                self._check_existing_jobs()
            elif clicked == resume_btn:
                for j in incomplete:
                    shutil.rmtree(j)
                self._resume_mode = True
            else:
                return

        self.is_processing    = True
        self.cancel_requested = False
        self._lock_inputs(True)
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        threading.Thread(target=self._process_jobs, daemon=True).start()

    def _cancel_generation(self):
        self.cancel_requested = True
        self.signals.log.emit("Cancellation requested…")

    def _run_step(self, job_number, step_name, fn, *args, **kwargs):
        """Run a processing step. On failure, logs the full traceback to file
        and re-raises with the step name prepended so the popup is useful."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            if self._log:
                self._log.error(
                    f"[Job {job_number:03}] STEP FAILED — {step_name}\n"
                    f"  {type(e).__name__}: {e}\n{tb}")
            raise RuntimeError(f"[{step_name}] {type(e).__name__}: {e}") from None

    def _process_jobs(self):
        try:
            num   = int(self.jobs_combo.currentText())
            t     = self._job_template()
            outd  = JOBS_DIRS.get(t)
            Config.WHISPER_MODEL = self.whisper_combo.currentText()
            Config.GENIUS_API_TOKEN = self.settings.get('genius_api_token', '')

            if self._log:
                mode = "SmartPicker" if self.use_smart_picker else "Manual"
                self._log.section(
                    f"Job batch started — {num} job(s) | {t.upper()} | {mode} | "
                    f"Whisper: {Config.WHISPER_MODEL}")

            if self.use_smart_picker:
                self.signals.log.emit(f"🤖 Smart Picker: {num} songs | {t.upper()}")
                picker   = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
                outd.mkdir(parents=True, exist_ok=True)

                start_idx = 1
                if self._resume_mode:
                    done = [j for j in outd.glob("job_*")
                            if (j / "job_data.json").exists()]
                    start_idx = len(done) + 1
                    remaining = num - len(done)
                    if remaining <= 0:
                        self.signals.log.emit("All jobs already complete — nothing to do.")
                        self.signals.finished.emit()
                        return
                    self.signals.log.emit(
                        f"  Resuming from job {start_idx} "
                        f"({len(done)} already complete, {remaining} remaining)")
                    songs = picker.get_available_songs(num_songs=remaining)
                else:
                    songs = picker.get_available_songs(num_songs=num)

                for i, s in enumerate(songs):
                    idx = start_idx + i
                    if self.cancel_requested:
                        raise Exception("Cancelled by user")
                    self.signals.log.emit(
                        f"\n{'='*40}\n📀 Job {idx}/{num}: {s['song_title'][:40]}")
                    self._process_single_song(
                        idx, s['song_title'], s['youtube_url'],
                        s['start_time'], s['end_time'], t, outd)
                    picker.mark_song_used(s['song_title'])
                    self.signals.progress.emit(idx / num * 100)
                self.signals.log.emit(
                    f"\n{'='*40}\n🎉 SUCCESS! {num} job(s) created!\n📂 {outd}\n"
                    "Next: Go to JSX Injection tab")
            else:
                total = len(self._job_queue)
                self.signals.log.emit(f"Starting {total} queued job(s) | {t.upper()}")
                outd.mkdir(parents=True, exist_ok=True)
                for idx, job in enumerate(self._job_queue, 1):
                    if self.cancel_requested:
                        raise Exception("Cancelled by user")
                    if self._resume_mode and (outd / f"job_{idx:03}" / "job_data.json").exists():
                        self.signals.log.emit(
                            f"\n{'='*40}\n⏭ Job {idx}/{total}: {job['title'][:40]} — skipping (complete)")
                        self.signals.progress.emit(idx / total * 100)
                        continue
                    self.signals.log.emit(
                        f"\n{'='*40}\n📀 Job {idx}/{total}: {job['title'][:40]}")
                    self._process_single_song(
                        idx, job['title'], job['url'],
                        job['start'], job['end'], t, outd)
                    self.signals.progress.emit(idx / total * 100)
                self.signals.log.emit(
                    f"\n{'='*40}\n🎉 SUCCESS! {total} job(s) created!\n📂 {outd}\n"
                    "Next: Go to JSX Injection tab")

            self.signals.stats_refresh.emit()
            self.signals.finished.emit()
        except Exception as e:
            tb = traceback.format_exc()
            self.signals.log.emit(f"❌ Error: {e}")
            self.signals.log.emit(f"─── Traceback ───\n{tb}")
            if self._log:
                self._log.error(f"Job batch failed: {type(e).__name__}: {e}\n{tb}")
            self.signals.error.emit(str(e))

    def _on_generation_finished(self):
        self.is_processing  = False
        self._resume_mode   = False
        self._job_queue.clear()
        self._rebuild_queue_list()
        self._update_queue_counter()
        self._lock_inputs(False)
        self._update_generate_btn_state()
        self.cancel_btn.setEnabled(False)
        self._check_existing_jobs()
        QMessageBox.information(self, "Complete!",
            f"Jobs created for {self._job_template().upper()}!\n\n"
            "Go to JSX Injection tab to inject into After Effects.")

    def _on_generation_error(self, msg):
        self.is_processing = False
        self._resume_mode  = False
        self._lock_inputs(False)
        self._update_generate_btn_state()
        self.cancel_btn.setEnabled(False)
        self._check_existing_jobs()
        QMessageBox.critical(self, "Error", msg)

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        self.status_label.setText(msg[:80])
        if self._log:
            if "❌" in msg or "error" in msg.lower() or "fail" in msg.lower():
                self._log.error(msg)
            elif "⚠" in msg or "warning" in msg.lower():
                self._log.warning(msg)
            else:
                self._log.info(msg)

    def _refresh_stats_label(self):
        s = self.song_db.get_stats()
        self.stats_label.setText(
            f"📊 {s['total_songs']} songs | {s['cached_lyrics']} with lyrics")

    # ── Single song processing (logic unchanged from original) ────────────────

    def _process_single_song(self, job_number, song_title, youtube_url,
                              start_time, end_time, template, output_dir,
                              return_data=False):
        job_folder  = output_dir / f"job_{job_number:03}"
        job_folder.mkdir(parents=True, exist_ok=True)
        needs_image = template in ['aurora', 'onyx']
        cached      = self.song_db.get_song(song_title)

        if cached:
            self.signals.log.emit("  ✓ Using cached data")
            youtube_url = cached['youtube_url']
            start_time  = cached['start_time']
            end_time    = cached['end_time']

        def chk():
            if self.cancel_requested:
                raise Exception("Cancelled")

        # Audio download
        chk()
        audio_path = job_folder / "audio_source.mp3"
        if not audio_path.exists():
            self.signals.log.emit("  Downloading audio…")
            self._run_step(job_number, "Audio download", download_audio, youtube_url, str(job_folder))
            self.signals.log.emit("  ✓ Audio downloaded")
        else:
            self.signals.log.emit("  ✓ Audio exists")

        # Trim
        chk()
        trimmed = job_folder / "audio_trimmed.wav"
        if not trimmed.exists():
            self.signals.log.emit(f"  Trimming ({start_time} → {end_time})…")
            self._run_step(job_number, "Audio trim", trim_audio, str(job_folder), start_time, end_time)
            self.signals.log.emit("  ✓ Trimmed")
        else:
            self.signals.log.emit("  ✓ Trimmed audio exists")

        # Beats (Aurora only)
        beats = []
        if template == 'aurora':
            chk()
            beats_path = job_folder / "beats.json"
            if cached and cached.get('beats'):
                beats = cached['beats']
                with open(beats_path, 'w') as f:
                    json.dump(beats, f, indent=4)
                self.signals.log.emit("  ✓ Cached beats")
            elif not beats_path.exists():
                self.signals.log.emit("  Detecting beats…")
                beats = self._run_step(job_number, "Beat detection", detect_beats, str(job_folder))
                with open(beats_path, 'w') as f:
                    json.dump(beats, f, indent=4)
                self.signals.log.emit(f"  ✓ {len(beats)} beats")
            else:
                with open(beats_path) as f:
                    beats = json.load(f)
                self.signals.log.emit("  ✓ Beats exist")

        # Transcribe (per-template)
        chk()
        lyrics_path = job_folder / "lyrics.txt"
        if template == 'aurora':
            if cached and cached.get('transcribed_lyrics'):
                with open(lyrics_path, 'w', encoding='utf-8') as f:
                    json.dump(cached['transcribed_lyrics'], f, indent=4, ensure_ascii=False)
                self.signals.log.emit(
                    f"  ✓ Cached lyrics ({len(cached['transcribed_lyrics'])} segs)")
            elif not lyrics_path.exists():
                self.signals.log.emit(f"  Transcribing ({Config.WHISPER_MODEL})…")
                t0 = time.time()
                self._run_step(job_number, "Whisper transcription (Aurora)", transcribe_audio, str(job_folder), song_title)
                elapsed = time.time() - t0
                self.signals.log.emit(
                    f"  ✓ Transcribed ({elapsed:.0f}s)")
            else:
                self.signals.log.emit("  ✓ Lyrics exist")
            lyrics_data = lyrics_path.read_text() if lyrics_path.exists() else ""

        elif template == 'mono':
            mono_path = job_folder / "mono_data.json"
            cached_mono = self.song_db.get_mono_lyrics(song_title)
            if cached_mono:
                with open(mono_path, 'w', encoding='utf-8') as f:
                    json.dump(cached_mono, f, indent=4, ensure_ascii=False)
                self.signals.log.emit("  ✓ Cached mono lyrics")
            elif not mono_path.exists():
                self.signals.log.emit(f"  Transcribing mono ({Config.WHISPER_MODEL})…")
                t0 = time.time()
                self._run_step(job_number, "Whisper transcription (Mono)", transcribe_audio_mono, str(job_folder), song_title)
                elapsed = time.time() - t0
                self.signals.log.emit(
                    f"  ✓ Transcribed mono ({elapsed:.0f}s)")
            else:
                self.signals.log.emit("  ✓ Mono data exists")
            lyrics_data = mono_path.read_text() if mono_path.exists() else "{}"

        elif template == 'onyx':
            onyx_path = job_folder / "onyx_data.json"
            cached_onyx = self.song_db.get_onyx_lyrics(song_title)
            if cached_onyx:
                with open(onyx_path, 'w', encoding='utf-8') as f:
                    json.dump(cached_onyx, f, indent=4, ensure_ascii=False)
                self.signals.log.emit("  ✓ Cached onyx lyrics")
            elif not onyx_path.exists():
                self.signals.log.emit(f"  Transcribing onyx ({Config.WHISPER_MODEL})…")
                t0 = time.time()
                self._run_step(job_number, "Whisper transcription (Onyx)", transcribe_audio_onyx, str(job_folder), song_title)
                elapsed = time.time() - t0
                self.signals.log.emit(
                    f"  ✓ Transcribed onyx ({elapsed:.0f}s)")
            else:
                self.signals.log.emit("  ✓ Onyx data exists")
            lyrics_data = onyx_path.read_text() if onyx_path.exists() else "{}"

        else:
            lyrics_data = ""

        # Image / colors
        image_path = job_folder / "cover.png"
        colors     = ['#ffffff', '#000000']
        if needs_image:
            chk()
            if cached and cached.get('genius_image_url'):
                if not image_path.exists():
                    self.signals.log.emit("  Downloading cached image…")
                    self._run_step(job_number, "Image download", download_image, str(job_folder), cached['genius_image_url'])
                self.signals.log.emit("  ✓ Cached image")
            elif not image_path.exists():
                self.signals.log.emit("  Fetching cover…")
                ok = self._run_step(job_number, "Genius image fetch", fetch_genius_image, song_title, str(job_folder))
                self.signals.log.emit("  ✓ Cover" if ok else "  ⚠ No cover")
            else:
                self.signals.log.emit("  ✓ Cover exists")
            chk()
            if image_path.exists():
                if cached and cached.get('colors'):
                    colors = cached['colors']
                    self.signals.log.emit("  ✓ Cached colors")
                else:
                    self.signals.log.emit("  Extracting colors…")
                    colors = self._run_step(job_number, "Color extraction", extract_colors, str(job_folder))
                    self.signals.log.emit(f"  ✓ Colors: {', '.join(colors)}")

        data_file = {
            'aurora': job_folder / "lyrics.txt",
            'mono':   job_folder / "mono_data.json",
            'onyx':   job_folder / "onyx_data.json",
        }.get(template, job_folder / "lyrics.txt")

        job_data = {
            "job_id": job_number, "song_title": song_title,
            "youtube_url": youtube_url, "start_time": start_time,
            "end_time": end_time, "template": template,
            "audio_trimmed": str(job_folder / "audio_trimmed.wav"),
            "cover_image": str(image_path) if image_path.exists() else None,
            "colors": colors, "lyrics_file": str(data_file),
            "beats": beats, "created_at": datetime.now().isoformat(),
        }
        with open(job_folder / "job_data.json", 'w') as f:
            json.dump(job_data, f, indent=4)

        if not cached and not self.use_smart_picker:
            self.signals.log.emit("  Saving to database…")
            self.song_db.add_song(
                song_title=song_title, youtube_url=youtube_url,
                start_time=start_time, end_time=end_time,
                genius_image_url=None, colors=colors, beats=beats)
        elif cached and not self.use_smart_picker:
            self.song_db.mark_song_used(song_title)
        if not self.use_smart_picker:
            if template == 'aurora':
                self.song_db.update_lyrics(song_title, lyrics_data)
            elif template == 'mono':
                self.song_db.update_mono_lyrics(song_title, lyrics_data)
            elif template == 'onyx':
                self.song_db.update_onyx_lyrics(song_title, lyrics_data)

        self.signals.log.emit(f"  ✓ Job {job_number} complete")
        return (job_data, job_folder) if return_data else None



# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Apollova")
    app.setStyleSheet(APP_STYLE)
    win = AppolovaApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
