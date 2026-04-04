"""Settings tab — AE path, Genius/Last.fm tokens, FFmpeg, mobile, paths."""

import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QGroupBox, QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QFont

from assets.gui.constants import (
    INSTALL_DIR, TEMPLATES_DIR, AURORA_JOBS_DIR, MONO_JOBS_DIR,
    ONYX_JOBS_DIR, DATABASE_DIR,
)
from assets.gui.helpers import _label, _set_label_style, _scrollable


def build(app) -> None:
    """Build the Settings tab. Sets all widgets on *app*."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)

    # After Effects
    ae_grp = QGroupBox("Adobe After Effects")
    ae_lay = QVBoxLayout(ae_grp)
    ae_row = QHBoxLayout()
    ae_row.addWidget(QLabel("Path:"))
    app.ae_path_edit = QLineEdit(
        app.settings.get('after_effects_path', '') or '')
    app.ae_path_edit.setPlaceholderText(
        "C:/Program Files/Adobe/.../AfterFX.exe")
    ae_row.addWidget(app.ae_path_edit)
    browse_btn = QPushButton("Browse...")
    browse_btn.clicked.connect(app._browse_ae_path)
    ae_row.addWidget(browse_btn)
    detect_btn = QPushButton("\U0001f50d  Auto-Detect")
    detect_btn.clicked.connect(app._auto_detect_ae_click)
    ae_row.addWidget(detect_btn)
    ae_lay.addLayout(ae_row)
    app.ae_status_label = QLabel("")
    ae_lay.addWidget(app.ae_status_label)
    app._update_ae_status()
    layout.addWidget(ae_grp)

    # Genius API
    genius_grp = QGroupBox("Genius API")
    genius_lay = QVBoxLayout(genius_grp)
    genius_lay.addWidget(QLabel("API Token:"))
    app.genius_edit = QLineEdit(
        app.settings.get('genius_api_token', '') or '')
    app.genius_edit.setEchoMode(QLineEdit.EchoMode.Password)
    genius_lay.addWidget(app.genius_edit)
    genius_lay.addWidget(_label(
        "Get your token at: https://genius.com/api-clients", "muted"))
    layout.addWidget(genius_grp)

    # Last.fm Integration
    lastfm_grp = QGroupBox("Last.fm Integration")
    lastfm_lay = QVBoxLayout(lastfm_grp)
    lastfm_lay.addWidget(QLabel("API Key:"))
    app.lastfm_key_edit = QLineEdit(
        app.settings.get('lastfm_api_key', '') or '')
    app.lastfm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    app.lastfm_key_edit.setPlaceholderText("Enter Last.fm API Key")
    lastfm_lay.addWidget(app.lastfm_key_edit)
    lfm_test_row = QHBoxLayout()
    lfm_test_btn = QPushButton("Test Connection")
    lfm_test_btn.setObjectName("accent")
    lfm_test_btn.clicked.connect(app._test_lastfm_connection)
    lfm_test_row.addWidget(lfm_test_btn)
    app.lastfm_status_label = _label("", "muted")
    lfm_test_row.addWidget(app.lastfm_status_label)
    lfm_test_row.addStretch()
    lastfm_lay.addLayout(lfm_test_row)
    lastfm_lay.addWidget(_label(
        "Get a free API key at: https://www.last.fm/api/account/create\n"
        "No subscription required. Enables the Discover tab.", "muted"))
    layout.addWidget(lastfm_grp)

    # Image Rotation
    img_grp = QGroupBox("Cover Image")
    img_lay = QVBoxLayout(img_grp)
    app.image_rotation_chk = QCheckBox(
        "Enable image rotation  (uses a different cover each time "
        "a song is processed)")
    app.image_rotation_chk.setChecked(
        app.settings.get('image_rotation', False))
    img_lay.addWidget(app.image_rotation_chk)
    img_lay.addWidget(_label(
        "    Fetches an alternative image from Genius each run so TikTok "
        "videos look different.  Requires internet.", "muted"))
    layout.addWidget(img_grp)

    # FFmpeg
    ffmpeg_grp = QGroupBox("FFmpeg")
    ffmpeg_lay = QVBoxLayout(ffmpeg_grp)
    app.ffmpeg_status_label = QLabel("Checking...")
    ffmpeg_lay.addWidget(app.ffmpeg_status_label)
    app._check_ffmpeg()
    layout.addWidget(ffmpeg_grp)

    # Mobile & Remote
    mobile_grp = QGroupBox("Mobile & Remote")
    mobile_lay = QVBoxLayout(mobile_grp)

    app.startup_chk = QCheckBox(
        "Launch Apollova on Windows startup (minimised to tray)")
    app.startup_chk.setChecked(
        app.settings.get("launch_on_startup", False))
    app.startup_chk.toggled.connect(app._toggle_launch_on_startup)
    mobile_lay.addWidget(app.startup_chk)

    tunnel_row = QHBoxLayout()
    tunnel_row.addWidget(QLabel("Tunnel:"))
    app.tunnel_status_label = QLabel("Checking...")
    tunnel_row.addWidget(app.tunnel_status_label)
    tunnel_row.addStretch()
    mobile_lay.addLayout(tunnel_row)

    qr_row = QHBoxLayout()
    show_qr_btn = QPushButton("Show QR Code")
    show_qr_btn.setObjectName("accent")
    show_qr_btn.clicked.connect(app._show_mobile_qr)
    qr_row.addWidget(show_qr_btn)
    regen_qr_btn = QPushButton("Regenerate QR")
    regen_qr_btn.setObjectName("danger")
    regen_qr_btn.clicked.connect(app._regenerate_qr)
    qr_row.addWidget(regen_qr_btn)
    qr_row.addStretch()
    mobile_lay.addLayout(qr_row)
    mobile_lay.addWidget(_label(
        "    Scan the QR code with the Apollova iOS app to connect "
        "your phone.", "muted"))
    layout.addWidget(mobile_grp)

    save_btn = QPushButton("Save Settings")
    save_btn.setObjectName("primary")
    save_btn.clicked.connect(app._save_all_settings)
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

    app.tabs.addTab(_scrollable(page), "  \u2699 Settings  ")


# ── Settings handlers ─────────────────────────────────────────────────────────

def update_ae_status(app) -> None:
    ae = getattr(app, 'ae_path_edit', None)
    path = ae.text() if ae else (
        app.settings.get('after_effects_path') or '')
    if path and Path(path).exists():
        app.ae_status_label.setText("\u2713 After Effects found")
        _set_label_style(app.ae_status_label, "success")
    elif path:
        app.ae_status_label.setText("\u2717 Path not found")
        _set_label_style(app.ae_status_label, "error")
    else:
        app.ae_status_label.setText("\u26a0 Not configured")
        _set_label_style(app.ae_status_label, "warning")


def check_ffmpeg(app) -> None:
    try:
        flags = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)
        r = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, text=True, timeout=5,
            creationflags=flags)
        if r.returncode == 0:
            app.ffmpeg_status_label.setText("\u2713 FFmpeg found in PATH")
            _set_label_style(app.ffmpeg_status_label, "success")
        else:
            app.ffmpeg_status_label.setText(
                "\u2717 FFmpeg not working properly")
            _set_label_style(app.ffmpeg_status_label, "error")
    except FileNotFoundError:
        app.ffmpeg_status_label.setText(
            "\u2717 FFmpeg not found \u2014 install and add to PATH")
        _set_label_style(app.ffmpeg_status_label, "error")
    except Exception as e:
        app.ffmpeg_status_label.setText(f"\u2717 Error: {e}")
        _set_label_style(app.ffmpeg_status_label, "error")


def browse_ae_path(app) -> None:
    path, _ = QFileDialog.getOpenFileName(
        app, "Select AfterFX.exe",
        "C:/Program Files/Adobe",
        "Executable (*.exe);;All files (*.*)")
    if path:
        app.ae_path_edit.setText(path)
        app._update_ae_status()


def auto_detect_ae_click(app) -> None:
    detected = app._auto_detect_after_effects()
    if detected:
        app.ae_path_edit.setText(detected)
        app._update_ae_status()
        QMessageBox.information(app, "Found",
                                f"After Effects found:\n{detected}")
    else:
        QMessageBox.warning(app, "Not Found",
            "Could not auto-detect After Effects.\n\n"
            "Please browse manually.")


def save_all_settings(app) -> None:
    from assets.apollova_gui import Config
    app.settings['after_effects_path'] = app.ae_path_edit.text()
    app.settings['genius_api_token'] = app.genius_edit.text()
    app.settings['whisper_model'] = app.whisper_combo.currentText()
    app.settings['image_rotation'] = app.image_rotation_chk.isChecked()
    app.settings['lastfm_api_key'] = app.lastfm_key_edit.text()
    Config.GENIUS_API_TOKEN = app.genius_edit.text()
    Config.WHISPER_MODEL = app.whisper_combo.currentText()
    app._save_settings()
    # Write .env to APPDATA (not install root) — matches config.py load priority
    from assets.scripts.config import Config as _Cfg
    env_dir = _Cfg.APPDATA_DIR
    env_dir.mkdir(parents=True, exist_ok=True)
    env = env_dir / ".env"
    tmp = env.with_suffix(".env.tmp")
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(f"GENIUS_API_TOKEN={app.genius_edit.text()}\n")
        f.write(f"WHISPER_MODEL={app.whisper_combo.currentText()}\n")
        f.write(f"LASTFM_API_KEY={app.lastfm_key_edit.text()}\n")
    tmp.replace(env)  # atomic write
    QMessageBox.information(app, "Saved", "Settings saved successfully!")
    app._update_inject_status()


def toggle_launch_on_startup(app, enabled: bool) -> None:
    """Register/unregister Apollova in the Windows startup registry."""
    app.settings["launch_on_startup"] = enabled
    app._save_settings()
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        if enabled:
            exe_path = str(Path(sys.executable))
            winreg.SetValueEx(key, "Apollova", 0, winreg.REG_SZ,
                              f'"{exe_path}" --minimised')
        else:
            try:
                winreg.DeleteValue(key, "Apollova")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        app._append_log(f"Startup registry update failed: {e}")


def regenerate_qr(app) -> None:
    """Regenerate the session token — invalidates all connected phones."""
    reply = QMessageBox.question(
        app, "Regenerate QR Code",
        "This will disconnect all currently paired phones.\n\n"
        "You will need to re-scan the QR code on your phone.\n\nContinue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply == QMessageBox.StandardButton.Yes:
        import secrets
        app.settings["session_token"] = secrets.token_hex(32)
        app._save_settings()
        app._show_mobile_qr()
