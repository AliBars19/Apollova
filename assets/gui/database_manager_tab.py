"""Database Manager Tab — browse, search, toggle, and delete songs in songs.db."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QCheckBox, QMessageBox, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from assets.gui.helpers import _label


# ─── Build ────────────────────────────────────────────────────────────────────

def build(app) -> None:
    tab = QWidget()
    lay = QVBoxLayout(tab)
    lay.setContentsMargins(20, 15, 20, 15)
    lay.setSpacing(10)

    lay.addWidget(_label("Database Manager", "title"))
    lay.addWidget(_label(
        "Toggle songs on/off to control which ones the SmartPicker can select.",
        "muted",
    ))

    # ── Stats bar ─────────────────────────────────────────────────────────────
    app.db_stats_label = _label("", "subtitle")
    lay.addWidget(app.db_stats_label)

    # ── Search + bulk controls ────────────────────────────────────────────────
    ctrl_row = QHBoxLayout()

    app.db_search_edit = QLineEdit()
    app.db_search_edit.setPlaceholderText("Search songs…")
    app.db_search_edit.textChanged.connect(lambda: _apply_filter(app))
    ctrl_row.addWidget(app.db_search_edit, stretch=3)

    btn_all_on = QPushButton("Enable All")
    btn_all_on.setObjectName("accent")
    btn_all_on.clicked.connect(lambda: _bulk_toggle(app, True))
    ctrl_row.addWidget(btn_all_on)

    btn_all_off = QPushButton("Disable All")
    btn_all_off.setObjectName("muted")
    btn_all_off.clicked.connect(lambda: _bulk_toggle(app, False))
    ctrl_row.addWidget(btn_all_off)

    btn_refresh = QPushButton("Refresh")
    btn_refresh.clicked.connect(lambda: _load_table(app))
    ctrl_row.addWidget(btn_refresh)

    lay.addLayout(ctrl_row)

    # ── Table ─────────────────────────────────────────────────────────────────
    tbl_group = QGroupBox("Songs")
    tbl_lay = QVBoxLayout(tbl_group)

    app.db_table = QTableWidget()
    app.db_table.setColumnCount(5)
    app.db_table.setHorizontalHeaderLabels(
        ["", "Song Title", "Uses", "Last Used", "Delete"]
    )
    app.db_table.horizontalHeader().setSectionResizeMode(
        1, QHeaderView.ResizeMode.Stretch
    )
    app.db_table.horizontalHeader().setSectionResizeMode(
        0, QHeaderView.ResizeMode.Fixed
    )
    app.db_table.setColumnWidth(0, 36)
    app.db_table.setColumnWidth(2, 60)
    app.db_table.setColumnWidth(3, 130)
    app.db_table.setColumnWidth(4, 70)
    app.db_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    app.db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    app.db_table.setAlternatingRowColors(True)
    app.db_table.verticalHeader().setVisible(False)
    app.db_table.setStyleSheet(
        "QTableWidget { alternate-background-color: #252535; }"
    )

    tbl_lay.addWidget(app.db_table)
    lay.addWidget(tbl_group, stretch=1)

    app.tabs.addTab(tab, "Database")

    # Initial load (deferred so the tab is visible first)
    QTimer.singleShot(0, lambda: _load_table(app))


# ─── Data loading ─────────────────────────────────────────────────────────────

def _load_table(app) -> None:
    """Fetch all songs from DB and populate the table."""
    rows = app.song_db.list_all_songs()
    app._db_all_rows = rows  # cache for filter
    _populate_table(app, rows)
    _refresh_stats(app)


def _populate_table(app, rows: list) -> None:
    tbl = app.db_table
    tbl.setRowCount(0)

    for song_title, use_count, last_used, toggled in rows:
        r = tbl.rowCount()
        tbl.insertRow(r)

        # Col 0 — toggle checkbox (centred)
        chk = QCheckBox()
        chk.setChecked(bool(toggled))
        chk.setToolTip("Enable/disable in SmartPicker")
        cell_w = QWidget()
        cell_lay = QHBoxLayout(cell_w)
        cell_lay.addWidget(chk)
        cell_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell_lay.setContentsMargins(0, 0, 0, 0)
        tbl.setCellWidget(r, 0, cell_w)
        chk.toggled.connect(_make_toggle_handler(app, song_title, chk, r))

        # Col 1 — title
        title_item = QTableWidgetItem(song_title)
        title_item.setForeground(
            QColor("#cdd6f4") if toggled else QColor("#6c7086")
        )
        tbl.setItem(r, 1, title_item)

        # Col 2 — use count
        count_item = QTableWidgetItem(str(use_count))
        count_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        tbl.setItem(r, 2, count_item)

        # Col 3 — last used
        last = (last_used or "Never")[:16]
        last_item = QTableWidgetItem(last)
        last_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        tbl.setItem(r, 3, last_item)

        # Col 4 — delete button
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("danger")
        del_btn.setFixedHeight(24)
        del_btn.clicked.connect(_make_delete_handler(app, song_title))
        tbl.setCellWidget(r, 4, del_btn)


def _apply_filter(app) -> None:
    query = app.db_search_edit.text().strip().lower()
    if not query:
        _populate_table(app, app._db_all_rows)
        return
    filtered = [
        row for row in app._db_all_rows
        if query in row[0].lower()
    ]
    _populate_table(app, filtered)


def _refresh_stats(app) -> None:
    stats = app.song_db.get_stats()
    total = stats["total_songs"]
    on = stats.get("toggled_on", total)
    app.db_stats_label.setText(
        f"{total} songs in database  |  {on} enabled  |  {total - on} disabled"
    )


# ─── Handlers ─────────────────────────────────────────────────────────────────

def _make_toggle_handler(app, song_title: str, chk: QCheckBox, row: int):
    def _handler(checked: bool):
        app.song_db.set_song_toggled(song_title, checked)
        tbl = app.db_table
        title_item = tbl.item(row, 1)
        if title_item:
            title_item.setForeground(
                QColor("#cdd6f4") if checked else QColor("#6c7086")
            )
        _refresh_stats(app)
        # Refresh SmartPicker stats if it's in that mode
        if hasattr(app, '_refresh_smart_picker_stats'):
            app._refresh_smart_picker_stats()
    return _handler


def _make_delete_handler(app, song_title: str):
    def _handler():
        reply = QMessageBox.question(
            app,
            "Delete Song",
            f"Permanently delete '{song_title}' from the database?\n\n"
            "This removes all cached lyrics, beats, and colors.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            app.song_db.delete_song(song_title)
            _load_table(app)
    return _handler


def _bulk_toggle(app, enabled: bool) -> None:
    app.song_db.set_all_toggled(enabled)
    _load_table(app)
    if hasattr(app, '_refresh_smart_picker_stats'):
        app._refresh_smart_picker_stats()


# ─── Public refresh (called from other tabs) ──────────────────────────────────

def refresh(app) -> None:
    """Reload table from DB — call after adding/deleting songs elsewhere."""
    _load_table(app)
