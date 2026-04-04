"""Apollova GUI — shared helper functions and WorkerSignals."""

import sys

from PyQt6.QtWidgets import (
    QApplication, QLabel, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QFont


# ── Worker signals (thread -> UI) ─────────────────────────────────────────────
class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(float)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    stats_refresh = pyqtSignal()
    batch_progress = pyqtSignal(str, float, str)
    batch_template_status = pyqtSignal(str, str)
    batch_finished = pyqtSignal(dict)
    discovery_progress = pyqtSignal(str, int, int, str)
    discovery_results = pyqtSignal(list)
    discovery_error = pyqtSignal(str)


# ── Label helpers ─────────────────────────────────────────────────────────────
def _label(text: str, style: str = "") -> QLabel:
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


def _set_label_style(lbl: QLabel, style: str) -> None:
    styles = {
        "success": "color:#a6e3a1;",
        "warning": "color:#f9e2af;",
        "error": "color:#f38ba8;",
        "muted": "color:#6c7086; font-size:11px;",
        "normal": "color:#cdd6f4;",
    }
    lbl.setStyleSheet(styles.get(style, "color:#cdd6f4;"))


def _scrollable(widget):
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    return scroll


# ── Safe startup error dialog ─────────────────────────────────────────────────
def _show_startup_error(title: str, message: str, fix: str = None) -> None:
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
