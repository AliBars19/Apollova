"""Apollova GUI — all constants, paths, styles, and validation patterns."""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Path resolution ───────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    ASSETS_DIR = BASE_DIR / "assets"
else:
    ASSETS_DIR = Path(__file__).resolve().parent.parent
    BASE_DIR = ASSETS_DIR.parent

BUNDLED_JSX_DIR = ASSETS_DIR / "scripts" / "JSX"
APP_VERSION = "1.0.0"

# ── Directory constants ───────────────────────────────────────────────────────
INSTALL_DIR = BASE_DIR
TEMPLATES_DIR = BASE_DIR / "templates"
AURORA_JOBS_DIR = BASE_DIR / "Apollova-Aurora" / "jobs"
MONO_JOBS_DIR = BASE_DIR / "Apollova-Mono" / "jobs"
ONYX_JOBS_DIR = BASE_DIR / "Apollova-Onyx" / "jobs"
DATABASE_DIR = BASE_DIR / "database"
WHISPER_DIR = BASE_DIR / "whisper_models"
SETTINGS_FILE = BASE_DIR / "settings.json"

TEMPLATE_PATHS = {
    "aurora": TEMPLATES_DIR / "Apollova-Aurora.aep",
    "mono": TEMPLATES_DIR / "Apollova-Mono.aep",
    "onyx": TEMPLATES_DIR / "Apollova-Onyx.aep",
}
JOBS_DIRS = {
    "aurora": AURORA_JOBS_DIR,
    "mono": MONO_JOBS_DIR,
    "onyx": ONYX_JOBS_DIR,
}
JSX_SCRIPTS = {
    "aurora": "Apollova-Aurora-Injection.jsx",
    "mono": "Apollova-Mono-Injection.jsx",
    "onyx": "Apollova-Onyx-Injection.jsx",
}

# ── Validation patterns ───────────────────────────────────────────────────────
_VALID_YT = re.compile(
    r'(?:youtube\.com/watch\?.*v=|youtu\.be/)([A-Za-z0-9_-]{11})')
_VALID_TIME = re.compile(r'^\d{1,2}:\d{2}$')


@dataclass
class DiscoveryResult:
    track: object              # LastFMTrack from lastfm_discovery.py
    youtube_url: Optional[str]
    youtube_confidence: str    # "high", "medium", "low", "none"
    start_mmss: str
    end_mmss: str
    chorus_confidence: float   # 0.0-1.0
    status: str                # "ready", "no_youtube", "no_chorus"


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
