"""
Apollova License Activation Dialog

Shown on startup when no valid license is found.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from apollova_license import activate_license

_STYLE = """
QDialog, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QLineEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 8px 12px;
    color: #cdd6f4;
    font-size: 15px;
    letter-spacing: 2px;
}
QLineEdit:focus { border-color: #89b4fa; }
QPushButton {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 8px 20px;
    color: #cdd6f4;
}
QPushButton:hover { background: #45475a; border-color: #89b4fa; }
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    padding: 9px 28px;
    border: none;
}
QPushButton#primary:hover { background: #b4befe; }
QPushButton#primary:disabled { background: #45475a; color: #6c7086; }
"""

_MESSAGES = {
    "no_license": "Enter your Apollova license key to activate this software.",
    "hardware_mismatch": (
        "This license file belongs to a different computer.\n"
        "Please enter your license key to activate on this machine."
    ),
    "invalid_token": (
        "Your license data appears to have been modified.\n"
        "Please re-enter your license key to reactivate."
    ),
    "revoked": (
        "Your license has been revoked.\n"
        "Please contact support@apollova.co.uk for assistance."
    ),
}


class ActivationDialog(QDialog):

    def __init__(self, reason: str = "no_license", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apollova — License Activation")
        self.setFixedSize(480, 370)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(_STYLE)
        self._activated = False
        self._build_ui(reason)

    # ─────────────────────────────────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self, reason: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(10)

        # Title
        title = QLabel("Apollova")
        f = QFont("Segoe UI")
        f.setPointSize(20)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        title.setStyleSheet("color: #89b4fa;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("License Activation")
        subtitle.setStyleSheet("color: #6c7086; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244; margin: 2px 0;")
        layout.addWidget(sep)

        # Reason message
        msg = _MESSAGES.get(reason, _MESSAGES["no_license"])
        reason_lbl = QLabel(msg)
        reason_lbl.setWordWrap(True)
        reason_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        reason_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(reason_lbl)

        # Key input
        key_lbl = QLabel("License Key")
        key_lbl.setStyleSheet("color: #6c7086; font-size: 11px; margin-top: 4px;")
        layout.addWidget(key_lbl)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self._key_input.setMaxLength(19)
        self._key_input.textChanged.connect(self._auto_format)
        layout.addWidget(self._key_input)

        # Status label
        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setMinimumHeight(38)
        self._status_lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self.reject)
        btn_row.addWidget(exit_btn)

        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setObjectName("primary")
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._on_activate)
        btn_row.addWidget(self._activate_btn)

        layout.addLayout(btn_row)

        # Purchase link
        link = QLabel(
            '<a href="https://apollova.co.uk" style="color:#89b4fa;">'
            'Purchase a license at apollova.co.uk</a>'
        )
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setStyleSheet("font-size: 11px; margin-top: 4px;")
        layout.addWidget(link)

        # Disable input for revoked licenses (must contact support)
        if reason == "revoked":
            self._key_input.setEnabled(False)
            self._activate_btn.setEnabled(False)

    # ─────────────────────────────────────────────────────────────────────────
    #  Logic
    # ─────────────────────────────────────────────────────────────────────────
    def _auto_format(self, text: str):
        """Auto-insert dashes: XXXX-XXXX-XXXX-XXXX"""
        self._key_input.blockSignals(True)
        clean = "".join(c for c in text.upper() if c.isalnum())[:16]
        parts = [clean[i:i + 4] for i in range(0, len(clean), 4)]
        formatted = "-".join(parts)
        self._key_input.setText(formatted)
        self._key_input.setCursorPosition(len(formatted))
        self._key_input.blockSignals(False)

    def _on_activate(self):
        key = self._key_input.text().strip()
        if not key:
            self._status_lbl.setText("Please enter your license key.")
            return
        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Activating...")
        self._status_lbl.setStyleSheet("color: #89b4fa; font-size: 12px;")
        self._status_lbl.setText("Contacting activation server...")
        # Short delay so the UI repaints before the blocking network call
        QTimer.singleShot(50, lambda: self._do_activate(key))

    def _do_activate(self, key: str):
        success, message = activate_license(key)
        if success:
            self._status_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            self._status_lbl.setText(f"✓  {message}")
            self._activated = True
            QTimer.singleShot(900, self.accept)
        else:
            self._status_lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")
            self._status_lbl.setText(message)
            self._activate_btn.setEnabled(True)
            self._activate_btn.setText("Activate")

    def was_activated(self) -> bool:
        return self._activated
