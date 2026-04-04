"""Mobile server, Cloudflare tunnel, and system tray management."""

import json
import threading

from PyQt6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon,
)
from PyQt6.QtGui import QIcon

from assets.gui.constants import INSTALL_DIR, ASSETS_DIR, SETTINGS_FILE
from assets.gui.helpers import _set_label_style


def start_mobile_server(app) -> None:
    """Start the FastAPI server and Cloudflare Tunnel in background threads."""
    if not app.settings.get("mobile_enabled", True):
        return

    try:
        import uvicorn
        from apollova_server import (
            app as fastapi_app, set_gui_ref, emit_progress,
        )

        set_gui_ref(app, settings_path=str(SETTINGS_FILE))

        # Bridge GUI progress signals to WebSocket broadcast
        app._ws_emit_progress = emit_progress

        port = app.settings.get("server_port", 7823)
        app._server_thread = threading.Thread(
            target=uvicorn.run,
            args=(fastapi_app,),
            kwargs={
                "host": "127.0.0.1",
                "port": port,
                "log_level": "error",
            },
            daemon=True,
        )
        app._server_thread.start()
        app._append_log(f"Mobile server started on port {port}")

        start_tunnel(app, port)
    except ImportError as e:
        app._append_log(f"Mobile server unavailable: {e}")
    except Exception as e:
        app._append_log(f"Mobile server failed to start: {e}")


def start_tunnel(app, port: int = 7823) -> None:
    """Start cloudflared tunnel if available."""
    try:
        from apollova_tunnel import TunnelManager
        app._tunnel_manager = TunnelManager(
            port=port, assets_dir=ASSETS_DIR)

        if not app._tunnel_manager.is_available():
            app._append_log(
                "Mobile Connect: cloudflared not installed")
            update_tray_tunnel_status(app, False)
            return

        def _tunnel_thread():
            url = app._tunnel_manager.start()
            if url:
                app.settings["tunnel_url"] = url
                app._save_settings()
                app._append_log(f"Tunnel active: {url}")
                update_tray_tunnel_status(app, True)
                try:
                    app.tunnel_status_label.setText(
                        f"Connected \u2014 {url[:50]}...")
                    _set_label_style(app.tunnel_status_label, "success")
                except Exception:
                    pass
            else:
                app._append_log("Tunnel failed to start")
                update_tray_tunnel_status(app, False)

        threading.Thread(target=_tunnel_thread, daemon=True).start()
    except ImportError:
        app._append_log(
            "Mobile Connect: tunnel module not available")
    except Exception as e:
        app._append_log(f"Tunnel error: {e}")


def update_tray_tunnel_status(app, connected: bool) -> None:
    """Update the system tray icon tooltip with tunnel status."""
    if hasattr(app, 'tray_icon') and app.tray_icon:
        status = "Connected" if connected else "Offline"
        app.tray_icon.setToolTip(f"Apollova \u2014 Mobile {status}")


# ── System Tray ──────────────────────────────────────────────────────────────

def setup_system_tray(app) -> None:
    """Create the system tray icon with context menu."""
    icon_path = INSTALL_DIR / "assets" / "icon.ico"
    if not icon_path.exists():
        icon_path = INSTALL_DIR / "icon.ico"

    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    app.tray_icon = QSystemTrayIcon(icon, app)

    tray_menu = QMenu()
    open_action = tray_menu.addAction("Open Apollova")
    open_action.triggered.connect(lambda: tray_show_window(app))
    mobile_action = tray_menu.addAction("Mobile Connect")
    mobile_action.triggered.connect(lambda: show_mobile_qr(app))
    tray_menu.addSeparator()
    quit_action = tray_menu.addAction("Quit")
    quit_action.triggered.connect(lambda: tray_quit(app))

    app.tray_icon.setContextMenu(tray_menu)
    app.tray_icon.activated.connect(
        lambda reason: _tray_activated(app, reason))
    app.tray_icon.setToolTip("Apollova")
    app.tray_icon.show()


def _tray_activated(app, reason) -> None:
    if reason == QSystemTrayIcon.ActivationReason.Trigger:
        tray_show_window(app)


def tray_show_window(app) -> None:
    app.showNormal()
    app.activateWindow()


def tray_quit(app) -> None:
    """Actually quit the application (from tray menu)."""
    app._force_quit = True
    app._cleanup_and_quit()
    QApplication.quit()


def show_mobile_qr(app) -> None:
    """Show the QR code for mobile pairing in a dialog."""
    token = app.settings.get("session_token", "")
    url = app.settings.get("tunnel_url", "")
    if not token or not url:
        QMessageBox.warning(app, "Not Ready",
            "Mobile server is not running or tunnel is not connected.\n\n"
            "Make sure Apollova is running and has internet access.")
        return

    qr_data = json.dumps({"url": url, "token": token})
    try:
        import qrcode
        from io import BytesIO
        from PyQt6.QtGui import QPixmap
        qr = qrcode.QRCode(version=1, box_size=8, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="#0D0A18")
        buf = BytesIO()
        img.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())

        dlg = QMessageBox(app)
        dlg.setWindowTitle("Mobile Connect \u2014 Scan QR Code")
        dlg.setIconPixmap(pixmap)
        dlg.setText(
            "Scan this QR code with the Apollova iOS app")
        dlg.setInformativeText(f"Tunnel: {url[:50]}...")
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()
    except ImportError:
        QMessageBox.information(app, "QR Data",
            f"Install qrcode package for QR display.\n\n"
            f"Manual data:\n{qr_data}")
