"""Job Creation tab — Manual Entry, Smart Picker, Discover modes."""

import os
import tempfile
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QRadioButton, QCheckBox, QTabWidget, QGroupBox, QTextEdit,
    QProgressBar, QListWidget, QButtonGroup, QFrame, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt

from assets.gui.constants import (
    AURORA_JOBS_DIR, JOBS_DIRS, _VALID_YT, _VALID_TIME, DiscoveryResult,
)
from assets.gui.helpers import _label, _set_label_style, _scrollable


def build(app) -> None:
    """Build the Job Creation tab. Sets all widgets on *app*."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)

    # Template
    tpl_grp = QGroupBox("Template")
    tpl_lay = QVBoxLayout(tpl_grp)
    app.job_tpl_group = QButtonGroup(app)
    for name, val, desc in [
        ("Auto", "auto", "Rotate Aurora / Mono / Onyx — max 2 each per batch (recommended)"),
        ("Aurora", "aurora", "Full visual with gradients, spectrum, beat-sync"),
        ("Mono", "mono", "Minimal text-only, black/white alternating"),
        ("Onyx", "onyx", "Hybrid — word-by-word lyrics + spinning vinyl disc"),
    ]:
        rb = QRadioButton(f"{name}  —  {desc}")
        rb.setProperty("tval", val)
        if val == "auto":
            rb.setChecked(True)
        app.job_tpl_group.addButton(rb)
        tpl_lay.addWidget(rb)

    path_row = QHBoxLayout()
    path_row.addWidget(_label("Output:", "muted"))
    app.output_path_label = _label("Auto: jobs spread across Aurora / Mono / Onyx", "muted")
    path_row.addWidget(app.output_path_label)
    path_row.addStretch()
    tpl_lay.addLayout(path_row)
    layout.addWidget(tpl_grp)
    app.job_tpl_group.buttonClicked.connect(app._on_template_change)

    # Song selection
    song_grp = QGroupBox("Song Selection")
    song_lay = QVBoxLayout(song_grp)
    app.song_tabs = QTabWidget()
    song_lay.addWidget(app.song_tabs)
    layout.addWidget(song_grp)

    _build_manual_entry(app)
    _build_smart_picker(app)
    _build_discover(app)

    app.song_tabs.currentChanged.connect(app._on_song_mode_changed)
    app._refresh_smart_picker_stats()

    # Job settings
    js_grp = QGroupBox("Job Settings")
    js_lay = QHBoxLayout(js_grp)
    js_lay.addWidget(QLabel("Number of Jobs:"))
    app.jobs_combo = QComboBox()
    app.jobs_combo.addItems(["1", "3", "6", "12"])
    app.jobs_combo.setCurrentText("12")
    app.jobs_combo.setFixedWidth(70)
    app.jobs_combo.currentIndexChanged.connect(app._on_jobs_count_changed)
    js_lay.addWidget(app.jobs_combo)
    js_lay.addSpacing(20)
    js_lay.addWidget(QLabel("Whisper Model:"))
    app.whisper_combo = QComboBox()
    app.whisper_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
    app.whisper_combo.setCurrentText(app.settings.get('whisper_model', 'small'))
    app.whisper_combo.setFixedWidth(110)
    js_lay.addWidget(app.whisper_combo)
    js_lay.addStretch()
    app.job_warning_label = _label("", "warning")
    js_lay.addWidget(app.job_warning_label)
    app.delete_jobs_btn = QPushButton("Delete Existing Jobs")
    app.delete_jobs_btn.setObjectName("danger")
    app.delete_jobs_btn.setVisible(False)
    app.delete_jobs_btn.clicked.connect(app._delete_existing_jobs)
    js_lay.addWidget(app.delete_jobs_btn)
    layout.addWidget(js_grp)
    app._check_existing_jobs()

    # Progress
    prog_grp = QGroupBox("Progress")
    prog_lay = QVBoxLayout(prog_grp)
    app.progress_bar = QProgressBar()
    app.progress_bar.setRange(0, 100)
    prog_lay.addWidget(app.progress_bar)
    app.status_label = QLabel("Ready")
    prog_lay.addWidget(app.status_label)
    app.log_text = QTextEdit()
    app.log_text.setReadOnly(True)
    app.log_text.setMinimumHeight(130)
    prog_lay.addWidget(app.log_text)
    layout.addWidget(prog_grp)

    # Buttons
    btn_row = QHBoxLayout()
    app.generate_btn = QPushButton("\U0001f680 Generate Jobs")
    app.generate_btn.setObjectName("primary")
    app.generate_btn.clicked.connect(app._start_generation)
    app.generate_btn.setEnabled(False)
    app.generate_btn.setToolTip("Add songs to queue first, or use Smart Picker")
    btn_row.addWidget(app.generate_btn)
    app.cancel_btn = QPushButton("\u2715  Cancel")
    app.cancel_btn.setObjectName("muted")
    app.cancel_btn.setEnabled(False)
    app.cancel_btn.setToolTip("Cancel running job generation")
    app.cancel_btn.clicked.connect(app._cancel_generation)
    btn_row.addWidget(app.cancel_btn)
    open_btn = QPushButton("\U0001f4c2  Open Jobs Folder")
    open_btn.clicked.connect(app._open_jobs_folder)
    btn_row.addWidget(open_btn)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    app.tabs.addTab(_scrollable(page), "  \U0001f4c1 Job Creation  ")


# ── Manual Entry sub-tab ──────────────────────────────────────────────────────

def _build_manual_entry(app) -> None:
    manual_w = QWidget()
    ml = QVBoxLayout(manual_w)
    ml.setSpacing(6)

    ml.addWidget(QLabel("Song Title (Artist - Song):"))
    app.title_edit = QLineEdit()
    app.title_edit.setPlaceholderText("e.g. Drake - God's Plan")
    app.title_edit.textChanged.connect(app._check_database)
    ml.addWidget(app.title_edit)
    app.db_match_label = _label("", "muted")
    ml.addWidget(app.db_match_label)
    ml.addWidget(QLabel("YouTube URL:"))
    app.url_edit = QLineEdit()
    app.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
    app.url_edit.textChanged.connect(app._on_url_changed)
    ml.addWidget(app.url_edit)
    app.url_error_label = _label("", "error")
    app.url_error_label.setVisible(False)
    ml.addWidget(app.url_error_label)
    tr = QHBoxLayout()
    tr.addWidget(QLabel("Start (MM:SS):"))
    app.start_edit = QLineEdit("00:00")
    app.start_edit.setFixedWidth(70)
    tr.addWidget(app.start_edit)
    tr.addSpacing(20)
    tr.addWidget(QLabel("End (MM:SS):"))
    app.end_edit = QLineEdit("01:01")
    app.end_edit.setFixedWidth(70)
    tr.addWidget(app.end_edit)
    tr.addStretch()
    ml.addLayout(tr)

    # Add to queue button
    add_row = QHBoxLayout()
    app.add_job_btn = QPushButton("\uff0b  Add to Queue")
    app.add_job_btn.setObjectName("accent")
    app.add_job_btn.clicked.connect(app._add_job_to_queue)
    add_row.addWidget(app.add_job_btn)
    add_row.addStretch()
    ml.addLayout(add_row)

    # Separator
    q_sep = QFrame()
    q_sep.setFrameShape(QFrame.Shape.HLine)
    q_sep.setStyleSheet("color:#313244; margin:4px 0;")
    ml.addWidget(q_sep)

    # Queue header with counter
    q_hdr = QHBoxLayout()
    q_hdr.addWidget(QLabel("Job Queue:"))
    q_hdr.addStretch()
    app.queue_counter_label = _label("0 / 12", "muted")
    q_hdr.addWidget(app.queue_counter_label)
    ml.addLayout(q_hdr)

    # Queue list
    app.queue_list = QListWidget()
    app.queue_list.setMinimumHeight(90)
    app.queue_list.setMaximumHeight(120)
    app.queue_list.itemSelectionChanged.connect(
        lambda: app.remove_job_btn.setEnabled(
            bool(app.queue_list.selectedItems()) and not app.is_processing))
    ml.addWidget(app.queue_list)

    # Queue action buttons
    q_btn_row = QHBoxLayout()
    app.remove_job_btn = QPushButton("\u2715  Remove Selected")
    app.remove_job_btn.setObjectName("muted")
    app.remove_job_btn.setEnabled(False)
    app.remove_job_btn.clicked.connect(app._remove_from_queue)
    q_btn_row.addWidget(app.remove_job_btn)
    app.clear_queue_btn = QPushButton("\U0001f5d1  Clear Queue")
    app.clear_queue_btn.setObjectName("danger")
    app.clear_queue_btn.setEnabled(False)
    app.clear_queue_btn.clicked.connect(app._clear_queue)
    q_btn_row.addWidget(app.clear_queue_btn)
    q_btn_row.addStretch()
    ml.addLayout(q_btn_row)

    ml.addStretch()
    app.song_tabs.addTab(manual_w, "  \u270f\ufe0f Manual Entry  ")


# ── Smart Picker sub-tab ─────────────────────────────────────────────────────

def _build_smart_picker(app) -> None:
    smart_w = QWidget()
    sl = QVBoxLayout(smart_w)
    sl.setSpacing(6)
    desc_lbl = _label(
        "Smart Picker automatically selects songs from your database.\n"
        "It ensures fair rotation \u2014 no song used twice until all used once.",
        "muted")
    desc_lbl.setWordWrap(True)
    sl.addWidget(desc_lbl)
    app.smart_stats_label = QLabel("Loading stats...")
    sl.addWidget(app.smart_stats_label)
    sp_btn_row = QHBoxLayout()
    ref_btn = QPushButton("\U0001f504 Refresh Stats")
    ref_btn.clicked.connect(app._refresh_smart_picker_stats)
    sp_btn_row.addWidget(ref_btn)
    app.reshuffle_btn = QPushButton("\U0001f500 Reshuffle Songs")
    app.reshuffle_btn.setObjectName("accent")
    app.reshuffle_btn.setToolTip(
        "Pick a different random selection from the same priority pool")
    app.reshuffle_btn.clicked.connect(app._reshuffle_songs)
    sp_btn_row.addWidget(app.reshuffle_btn)
    app.reset_uses_btn = QPushButton("\U0001f504 Reset Uses")
    app.reset_uses_btn.setToolTip("Reset all song use counts back to unused")
    app.reset_uses_btn.clicked.connect(app._reset_use_counts)
    sp_btn_row.addWidget(app.reset_uses_btn)
    sp_btn_row.addStretch()
    sl.addLayout(sp_btn_row)
    sl.addWidget(QLabel("Next songs to be selected:"))
    app.smart_listbox = QListWidget()
    app.smart_listbox.setMinimumHeight(150)
    sl.addWidget(app.smart_listbox)
    app.smart_warning_label = _label("", "warning")
    sl.addWidget(app.smart_warning_label)
    sl.addStretch()
    app.song_tabs.addTab(smart_w, "  \U0001f916 Smart Picker  ")


# ── Discover sub-tab ──────────────────────────────────────────────────────────

def _build_discover(app) -> None:
    discover_w = QWidget()
    dl = QVBoxLayout(discover_w)
    dl.setSpacing(6)

    # Not-configured warning
    app.discover_not_configured = _label(
        "Last.fm not configured \u2014 add your API key in Settings tab", "warning")
    app.discover_not_configured.setWordWrap(True)
    app.discover_not_configured.setVisible(False)
    dl.addWidget(app.discover_not_configured)

    # Row 1: source + limit + skip existing
    d_row1 = QHBoxLayout()
    d_row1.addWidget(QLabel("Source:"))
    app.discover_source_combo = QComboBox()
    from scripts.lastfm_discovery import CHART_SOURCES as _LFM_SOURCES
    for name in _LFM_SOURCES:
        app.discover_source_combo.addItem(name)
    d_row1.addWidget(app.discover_source_combo)
    d_row1.addSpacing(10)
    d_row1.addWidget(QLabel("Limit:"))
    app.discover_limit_combo = QComboBox()
    for v in ["25", "50", "100"]:
        app.discover_limit_combo.addItem(v)
    app.discover_limit_combo.setCurrentIndex(1)
    d_row1.addWidget(app.discover_limit_combo)
    d_row1.addSpacing(10)
    app.discover_skip_existing = QCheckBox("Skip songs already in DB")
    app.discover_skip_existing.setChecked(True)
    d_row1.addWidget(app.discover_skip_existing)
    d_row1.addStretch()
    dl.addLayout(d_row1)

    # Row 2: fetch + cancel buttons
    d_row2 = QHBoxLayout()
    app.discover_fetch_btn = QPushButton("Fetch Songs")
    app.discover_fetch_btn.setObjectName("primary")
    app.discover_fetch_btn.clicked.connect(app._start_discovery)
    d_row2.addWidget(app.discover_fetch_btn)
    app.discover_cancel_btn = QPushButton("Cancel")
    app.discover_cancel_btn.setObjectName("muted")
    app.discover_cancel_btn.setEnabled(False)
    app.discover_cancel_btn.clicked.connect(app._cancel_discovery)
    d_row2.addWidget(app.discover_cancel_btn)
    d_row2.addStretch()
    dl.addLayout(d_row2)

    # Progress section (hidden by default)
    app.discover_progress_bar = QProgressBar()
    app.discover_progress_bar.setVisible(False)
    dl.addWidget(app.discover_progress_bar)
    app.discover_phase_label = _label("", "muted")
    app.discover_phase_label.setVisible(False)
    dl.addWidget(app.discover_phase_label)

    # Results table
    app.discover_table = QTableWidget()
    app.discover_table.setColumnCount(8)
    app.discover_table.setHorizontalHeaderLabels(
        ["#", "", "Title", "Artist", "Start", "End", "YouTube", "Confidence"])
    app.discover_table.horizontalHeader().setSectionResizeMode(
        2, QHeaderView.ResizeMode.Stretch)
    app.discover_table.horizontalHeader().setSectionResizeMode(
        3, QHeaderView.ResizeMode.Stretch)
    app.discover_table.setColumnWidth(0, 35)
    app.discover_table.setColumnWidth(1, 30)
    app.discover_table.setColumnWidth(4, 60)
    app.discover_table.setColumnWidth(5, 60)
    app.discover_table.setColumnWidth(6, 180)
    app.discover_table.setColumnWidth(7, 90)
    app.discover_table.setStyleSheet(
        "QTableWidget { background: #181825; border: 1px solid #313244; "
        "border-radius: 4px; color: #cdd6f4; gridline-color: #313244; }"
        "QTableWidget::item { padding: 3px; }"
        "QHeaderView::section { background: #313244; color: #cdd6f4; "
        "padding: 4px; border: 1px solid #45475a; }")
    app.discover_table.setMinimumHeight(200)
    app.discover_table.itemChanged.connect(app._update_discover_add_btn)
    app.discover_table.setVisible(False)
    dl.addWidget(app.discover_table)

    # Action row
    d_action = QHBoxLayout()
    d_sel_all = QPushButton("Select All")
    d_sel_all.setObjectName("muted")
    d_sel_all.clicked.connect(app._discover_select_all)
    d_action.addWidget(d_sel_all)
    d_desel_all = QPushButton("Deselect All")
    d_desel_all.setObjectName("muted")
    d_desel_all.clicked.connect(app._discover_deselect_all)
    d_action.addWidget(d_desel_all)
    d_desel_low = QPushButton("Deselect Low")
    d_desel_low.setObjectName("muted")
    d_desel_low.clicked.connect(app._discover_deselect_low)
    d_action.addWidget(d_desel_low)
    d_action.addStretch()
    app.discover_add_btn = QPushButton("Add Selected Songs")
    app.discover_add_btn.setObjectName("primary")
    app.discover_add_btn.setEnabled(False)
    app.discover_add_btn.clicked.connect(app._discover_add_selected)
    d_action.addWidget(app.discover_add_btn)
    app.discover_action_row = QWidget()
    app.discover_action_row.setLayout(d_action)
    app.discover_action_row.setVisible(False)
    dl.addWidget(app.discover_action_row)

    # Summary label
    app.discover_summary_label = _label("", "success")
    app.discover_summary_label.setWordWrap(True)
    app.discover_summary_label.setVisible(False)
    dl.addWidget(app.discover_summary_label)

    dl.addStretch()
    app.song_tabs.addTab(discover_w, "  \U0001f50d Discover  ")


# ── Event handlers ────────────────────────────────────────────────────────────

def on_template_change(app) -> None:
    t = app._job_template()
    if t == "auto":
        app.output_path_label.setText(
            "Auto: jobs spread across Aurora / Mono / Onyx")
    else:
        app.output_path_label.setText(str(JOBS_DIRS.get(t, AURORA_JOBS_DIR)))
    app._check_existing_jobs()


def on_song_mode_changed(app, index: int) -> None:
    app.use_smart_picker = (index == 1)
    if index == 1:
        app._refresh_smart_picker_stats()
    elif index == 2:
        app._check_lastfm_configured()
    app._update_generate_btn_state()


def on_jobs_count_changed(app, _index: int) -> None:
    app._update_queue_counter()
    app._update_generate_btn_state()
    if app.use_smart_picker:
        app._refresh_smart_picker_stats()


def update_queue_counter(app) -> None:
    n = int(app.jobs_combo.currentText())
    count = len(app._job_queue)
    app.queue_counter_label.setText(f"{count} / {n}")


def update_generate_btn_state(app) -> None:
    if app.is_processing:
        app.generate_btn.setEnabled(False)
        return
    if app.use_smart_picker:
        app.generate_btn.setEnabled(True)
    else:
        n = int(app.jobs_combo.currentText())
        app.generate_btn.setEnabled(len(app._job_queue) >= n)


def add_job_to_queue(app) -> None:
    title = app.title_edit.text().strip()
    url = app.url_edit.text().strip()
    start = app.start_edit.text().strip()
    end = app.end_edit.text().strip()
    n = int(app.jobs_combo.currentText())

    if len(app._job_queue) >= n:
        QMessageBox.warning(app, "Queue Full",
            f"Queue already has {n} jobs.\n"
            "Increase the job count or clear the queue first.")
        return

    if not title:
        QMessageBox.critical(app, "Missing Info", "Song title is required.")
        return

    cached = app.song_db.get_song(title)
    effective_url = url or (cached['youtube_url'] if cached else "")

    errors = app._validate_song_record(effective_url, start, end)
    if errors:
        QMessageBox.critical(app, "Invalid Job Data",
            "Fix the following before adding this job to the queue:\n\n\u2022 " +
            "\n\u2022 ".join(errors))
        return

    app._job_queue.append(
        {'title': title, 'url': effective_url, 'start': start, 'end': end})
    app._rebuild_queue_list()
    app._update_queue_counter()
    app._update_generate_btn_state()

    app.title_edit.clear()
    app.url_edit.clear()
    app.start_edit.setText("00:00")
    app.end_edit.setText("01:01")
    app.db_match_label.setText("")
    for f in (app.url_edit, app.start_edit, app.end_edit):
        app._highlight_field(f, False)


def remove_from_queue(app) -> None:
    row = app.queue_list.currentRow()
    if row < 0:
        return
    app._job_queue.pop(row)
    app._rebuild_queue_list()
    app._update_queue_counter()
    app._update_generate_btn_state()


def clear_queue(app) -> None:
    if not app._job_queue:
        return
    reply = QMessageBox.question(
        app, "Clear Queue",
        f"Are you sure you want to delete all {len(app._job_queue)} job(s) "
        "from the queue?\n\nThis cannot be undone.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return
    app._job_queue.clear()
    app._rebuild_queue_list()
    app._update_queue_counter()
    app._update_generate_btn_state()


def rebuild_queue_list(app) -> None:
    app.queue_list.clear()
    for i, job in enumerate(app._job_queue, 1):
        app.queue_list.addItem(
            f"{i:2}. {job['title'][:35]:<35}  {job['start']} \u2192 {job['end']}")
    app.clear_queue_btn.setEnabled(bool(app._job_queue))
    app.remove_job_btn.setEnabled(False)


def job_template(app) -> str:
    btn = app.job_tpl_group.checkedButton()
    return btn.property("tval") if btn else "aurora"


# ── Smart Picker handlers ────────────────────────────────────────────────────

def refresh_smart_picker_stats(app) -> None:
    try:
        picker = app.smart_picker
        stats = picker.get_database_stats()
        if stats['total_songs'] == 0:
            _set_label_style(app.smart_stats_label, "warning")
            app.smart_stats_label.setText(
                "\U0001f4ca Database is empty. Add songs via Manual Entry first.")
            app.smart_warning_label.setText(
                "\u26a0\ufe0f No songs available. Use Manual Entry to add songs.")
            app.smart_listbox.clear()
            return

        app.smart_stats_label.setText(
            f"\U0001f4ca Total: {stats['total_songs']} | "
            f"Unused: {stats['unused_songs']} | "
            f"Uses: {stats['min_uses']}\u2013{stats['max_uses']} "
            f"(avg {stats['avg_uses']})")

        num_jobs = int(app.jobs_combo.currentText())
        songs = picker.get_available_songs(num_songs=num_jobs)
        app._smart_songs = songs
        app.smart_listbox.clear()
        for i, s in enumerate(songs, 1):
            tag = "\U0001f195 new" if s['use_count'] == 1 else \
                f"\U0001f4ca {s['use_count']}x"
            app.smart_listbox.addItem(
                f"{i:2}. {s['song_title'][:45]:<45} ({tag})")
        if len(songs) < num_jobs:
            app.smart_warning_label.setText(
                f"\u26a0\ufe0f Only {len(songs)} songs available, "
                f"{num_jobs} requested.")
        else:
            app.smart_warning_label.setText("")
    except Exception as e:
        _set_label_style(app.smart_stats_label, "error")
        app.smart_stats_label.setText(f"\u274c Error: {e}")


def reset_use_counts(app) -> None:
    """Reset all song use counts back to unused after confirmation."""
    reply = QMessageBox.question(
        app, "Reset Use Counts",
        "This will mark ALL songs as unused (use_count \u2192 1).\n\nContinue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return
    try:
        picker = app.smart_picker
        affected = picker.reset_all_use_counts()
        app._refresh_smart_picker_stats()
        QMessageBox.information(app, "Done",
            f"Reset use counts for {affected} songs.")
    except Exception as e:
        QMessageBox.critical(app, "Error", f"Failed to reset uses: {e}")


def reshuffle_songs(app) -> None:
    """Re-pick songs with randomization within each use_count tier."""
    try:
        picker = app.smart_picker
        stats = picker.get_database_stats()
        if stats['total_songs'] == 0:
            return

        app.smart_stats_label.setText(
            f"\U0001f4ca Total: {stats['total_songs']} | "
            f"Unused: {stats['unused_songs']} | "
            f"Uses: {stats['min_uses']}\u2013{stats['max_uses']} "
            f"(avg {stats['avg_uses']})")

        num_jobs = int(app.jobs_combo.currentText())
        songs = picker.get_available_songs(num_songs=num_jobs, shuffle=True)
        app._smart_songs = songs
        app.smart_listbox.clear()
        for i, s in enumerate(songs, 1):
            tag = "\U0001f195 new" if s['use_count'] == 1 else \
                f"\U0001f4ca {s['use_count']}x"
            app.smart_listbox.addItem(
                f"{i:2}. {s['song_title'][:45]:<45} ({tag})")
        if len(songs) < num_jobs:
            app.smart_warning_label.setText(
                f"\u26a0\ufe0f Only {len(songs)} songs available, "
                f"{num_jobs} requested.")
        else:
            app.smart_warning_label.setText("")
    except Exception as e:
        _set_label_style(app.smart_stats_label, "error")
        app.smart_stats_label.setText(f"\u274c Error: {e}")


# ── Discover handlers ────────────────────────────────────────────────────────

def check_lastfm_configured(app) -> None:
    """Show/hide the not-configured label based on env vars."""
    key = (os.getenv("LASTFM_API_KEY", "").strip()
           or app.settings.get('lastfm_api_key', ''))
    configured = bool(key)
    app.discover_not_configured.setVisible(not configured)
    app.discover_fetch_btn.setEnabled(
        configured and not app._discovery_in_progress)


def start_discovery(app) -> None:
    """Validate inputs, disable controls, start background discovery thread."""
    if app._discovery_in_progress:
        return

    source_name = app.discover_source_combo.currentText()
    limit = int(app.discover_limit_combo.currentText())
    skip_existing = app.discover_skip_existing.isChecked()

    app._discover_cancel_event.clear()
    app._discovery_in_progress = True
    app.discover_fetch_btn.setEnabled(False)
    app.discover_cancel_btn.setEnabled(True)
    app.discover_progress_bar.setVisible(True)
    app.discover_progress_bar.setValue(0)
    app.discover_phase_label.setVisible(True)
    app.discover_phase_label.setText("Starting...")
    app.discover_table.setVisible(False)
    app.discover_action_row.setVisible(False)
    app.discover_summary_label.setVisible(False)

    t = threading.Thread(
        target=run_discovery_pipeline,
        args=(app, source_name, limit, skip_existing),
        daemon=True)
    t.start()


def cancel_discovery(app) -> None:
    """Set cancel flag — thread checks this between each song."""
    app._discover_cancel_event.set()
    app.discover_cancel_btn.setEnabled(False)
    app.discover_phase_label.setText("Cancelling...")


def run_discovery_pipeline(app, source_name: str, limit: int,
                           skip_existing: bool) -> None:
    """Background thread: fetch Last.fm tracks -> find YouTube -> detect chorus."""
    from scripts.lastfm_discovery import fetch_tracks
    from scripts.youtube_finder import find_youtube_url
    from scripts.chorus_detector import detect_chorus, _heuristic_fallback
    # Import here to avoid circular — download_audio is set on module level
    from assets.apollova_gui import download_audio

    key = app.settings.get('lastfm_api_key', '').strip()
    if key:
        os.environ["LASTFM_API_KEY"] = key

    results = []

    # Step 1: Fetch Last.fm tracks
    app.signals.discovery_progress.emit(
        "lastfm", 0, limit, "Fetching chart data...")
    try:
        tracks = fetch_tracks(
            source_name=source_name,
            limit=limit,
            fetch_durations=True,
            progress_cb=lambda cur, tot, title:
                app.signals.discovery_progress.emit("lastfm", cur, tot, title)
        )
    except Exception as e:
        app.signals.discovery_error.emit(str(e))
        return

    if skip_existing:
        existing = {s[0].lower() for s in app.song_db.list_all_songs()}
        tracks = [t for t in tracks
                  if t.db_title.lower() not in existing
                  and t.title.lower() not in existing]

    total = len(tracks)
    if total == 0:
        app.signals.discovery_error.emit(
            "No new songs found. All tracks are already in your database."
            if skip_existing else "No tracks found for this source.")
        return

    for i, track in enumerate(tracks):
        if app._discover_cancel_event.is_set():
            break

        song_label = track.db_title
        app.signals.discovery_progress.emit("youtube", i + 1, total, song_label)

        try:
            yt_result = find_youtube_url(
                title=track.title,
                artist=track.artist,
                duration_sec=track.duration_sec_safe
            )
        except Exception:
            yt_result = None

        if not yt_result:
            results.append(DiscoveryResult(
                track=track, youtube_url=None, youtube_confidence="none",
                start_mmss="00:00", end_mmss="01:00",
                chorus_confidence=0.0, status="no_youtube",
            ))
            continue

        app.signals.discovery_progress.emit("chorus", i + 1, total, song_label)
        chorus = None
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = download_audio(yt_result.url, tmpdir)
                chorus = detect_chorus(audio_path)
        except Exception:
            chorus = _heuristic_fallback(
                track.duration_sec_safe, 60, "download_failed")

        results.append(DiscoveryResult(
            track=track, youtube_url=yt_result.url,
            youtube_confidence=yt_result.confidence,
            start_mmss=chorus.start_mmss, end_mmss=chorus.end_mmss,
            chorus_confidence=chorus.confidence, status="ready",
        ))

    app.signals.discovery_results.emit(results)


def on_discovery_progress(app, step: str, current: int, total: int,
                          title: str) -> None:
    """Update progress bar and phase label from signal."""
    if total > 0:
        if step == "lastfm":
            pct = int(current / total * 30)
        elif step == "youtube":
            pct = 30 + int(current / total * 35)
        else:
            pct = 65 + int(current / total * 35)
        app.discover_progress_bar.setValue(pct)

    phase_map = {
        "lastfm": "Fetching chart data",
        "youtube": "Finding YouTube URLs",
        "chorus": "Detecting choruses",
    }
    phase = phase_map.get(step, step)
    app.discover_phase_label.setText(
        f"{phase}: {title[:50]} ({current}/{total})")


def on_discovery_results(app, results: list) -> None:
    """Populate table and re-enable controls."""
    app._discovery_in_progress = False
    app._discovery_results = results
    app.discover_fetch_btn.setEnabled(True)
    app.discover_cancel_btn.setEnabled(False)
    app.discover_progress_bar.setVisible(False)
    app.discover_phase_label.setVisible(False)

    if not results:
        app.discover_phase_label.setText("No results found.")
        app.discover_phase_label.setVisible(True)
        return

    populate_discover_table(app, results)
    app.discover_table.setVisible(True)
    app.discover_action_row.setVisible(True)
    app._update_discover_add_btn()


def on_discovery_error(app, error_msg: str) -> None:
    """Show error message, re-enable controls."""
    app._discovery_in_progress = False
    app.discover_fetch_btn.setEnabled(True)
    app.discover_cancel_btn.setEnabled(False)
    app.discover_progress_bar.setVisible(False)
    _set_label_style(app.discover_phase_label, "error")
    app.discover_phase_label.setText(f"Error: {error_msg}")
    app.discover_phase_label.setVisible(True)


def populate_discover_table(app, results: list) -> None:
    """Fill QTableWidget rows with results."""
    app.discover_table.setRowCount(len(results))
    for row, r in enumerate(results):
        num_item = QTableWidgetItem(str(row + 1))
        num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        app.discover_table.setItem(row, 0, num_item)

        chk_item = QTableWidgetItem()
        if r.status == "no_youtube":
            chk_item.setFlags(
                chk_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        else:
            chk_item.setFlags(
                chk_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if r.youtube_confidence == "low":
                chk_item.setCheckState(Qt.CheckState.Unchecked)
            else:
                chk_item.setCheckState(Qt.CheckState.Checked)
        app.discover_table.setItem(row, 1, chk_item)

        title_item = QTableWidgetItem(r.track.title)
        title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        app.discover_table.setItem(row, 2, title_item)

        artist_item = QTableWidgetItem(r.track.artist)
        artist_item.setFlags(
            artist_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        app.discover_table.setItem(row, 3, artist_item)

        start_item = QTableWidgetItem(r.start_mmss)
        app.discover_table.setItem(row, 4, start_item)

        end_item = QTableWidgetItem(r.end_mmss)
        app.discover_table.setItem(row, 5, end_item)

        if r.youtube_url:
            url_display = (r.youtube_url[:35] + "..."
                           if len(r.youtube_url) > 35 else r.youtube_url)
        else:
            url_display = "Not found"
        url_item = QTableWidgetItem(url_display)
        url_item.setFlags(url_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if r.youtube_url:
            url_item.setToolTip(r.youtube_url)
        app.discover_table.setItem(row, 6, url_item)

        conf = r.youtube_confidence
        conf_item = QTableWidgetItem(
            conf.capitalize() if conf != "none" else "None")
        conf_item.setFlags(conf_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if conf == "high":
            conf_item.setForeground(Qt.GlobalColor.green)
        elif conf == "medium":
            conf_item.setForeground(Qt.GlobalColor.yellow)
        elif conf == "low":
            conf_item.setForeground(Qt.GlobalColor.red)
        else:
            conf_item.setForeground(Qt.GlobalColor.gray)
        app.discover_table.setItem(row, 7, conf_item)


def discover_select_all(app) -> None:
    for row in range(app.discover_table.rowCount()):
        item = app.discover_table.item(row, 1)
        if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            item.setCheckState(Qt.CheckState.Checked)
    app._update_discover_add_btn()


def discover_deselect_all(app) -> None:
    for row in range(app.discover_table.rowCount()):
        item = app.discover_table.item(row, 1)
        if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            item.setCheckState(Qt.CheckState.Unchecked)
    app._update_discover_add_btn()


def discover_deselect_low(app) -> None:
    for row, r in enumerate(app._discovery_results):
        if r.youtube_confidence == "low":
            item = app.discover_table.item(row, 1)
            if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Unchecked)
    app._update_discover_add_btn()


def update_discover_add_btn(app, *_args) -> None:
    """Update the add button text with count of selected songs."""
    count = 0
    for row in range(app.discover_table.rowCount()):
        item = app.discover_table.item(row, 1)
        if item and item.checkState() == Qt.CheckState.Checked:
            count += 1
    app.discover_add_btn.setText(
        f"Add {count} Selected Songs" if count else "Add Selected Songs")
    app.discover_add_btn.setEnabled(count > 0)


def discover_add_selected(app) -> None:
    """Add all checked rows to the song database."""
    added = 0
    skipped = 0
    for row in range(app.discover_table.rowCount()):
        chk = app.discover_table.item(row, 1)
        if not chk or chk.checkState() != Qt.CheckState.Checked:
            continue

        r = app._discovery_results[row]
        if not r.youtube_url:
            skipped += 1
            continue

        title = r.track.db_title
        start = app.discover_table.item(row, 4).text().strip()
        end = app.discover_table.item(row, 5).text().strip()

        if not _VALID_TIME.match(start):
            start = r.start_mmss
        if not _VALID_TIME.match(end):
            end = r.end_mmss

        app.song_db.add_song(
            song_title=title,
            youtube_url=r.youtube_url,
            start_time=start,
            end_time=end,
        )
        added += 1

    app.discover_summary_label.setText(
        f"{added} songs added to database."
        + (f" {skipped} skipped (no YouTube URL)." if skipped else ""))
    app.discover_summary_label.setVisible(True)

    app.discover_table.setRowCount(0)
    app.discover_table.setVisible(False)
    app.discover_action_row.setVisible(False)
    app._discovery_results = []

    if app.song_tabs.currentIndex() == 1:
        app._refresh_smart_picker_stats()


# ── Field validation helpers ──────────────────────────────────────────────────

def highlight_field(field, has_error: bool) -> None:
    """Apply or clear a red border on an input field."""
    if has_error:
        field.setStyleSheet(
            "border: 1px solid #f38ba8; border-radius: 4px;")
    else:
        field.setStyleSheet("")


def on_url_changed(app, text: str) -> None:
    url = text.strip()
    if url and not _VALID_YT.search(url):
        app._highlight_field(app.url_edit, True)
        app.url_error_label.setText("\u26a0  This is not a valid YouTube URL")
        app.url_error_label.setVisible(True)
    else:
        app._highlight_field(app.url_edit, False)
        app.url_error_label.setVisible(False)


def validate_song_record(url: str, start: str, end: str) -> list:
    """
    Validate a song's core database fields.
    Returns a list of human-readable error strings (empty = all valid).
    """
    errors = []

    if not url or not url.strip():
        errors.append("YouTube URL is missing")
    elif url.strip().lower() == "unknown":
        errors.append(
            "YouTube URL is set to 'unknown' \u2014 this song was never "
            "given a real YouTube link")
    elif not _VALID_YT.search(url):
        errors.append(
            f"YouTube URL is not a valid YouTube watch link: '{url[:70]}'")

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
    e_sec = _parse(end, "End time")
    if s_sec is not None and e_sec is not None and s_sec >= e_sec:
        errors.append(
            f"Start time ({start}) must be before end time ({end})")

    return errors


# ── Database check ────────────────────────────────────────────────────────────

def check_database(app) -> None:
    title = app.title_edit.text().strip()
    if len(title) < 3:
        app.db_match_label.setText("")
        for f in (app.url_edit, app.start_edit, app.end_edit):
            app._highlight_field(f, False)
        return
    cached = app.song_db.get_song(title)
    if cached:
        url = cached['youtube_url'] or ""
        start = cached['start_time'] or ""
        end = cached['end_time'] or ""
        app.url_edit.setText(url)
        app.start_edit.setText(start)
        app.end_edit.setText(end)

        errors = app._validate_song_record(url, start, end)

        app._highlight_field(app.url_edit,
                             any("URL" in e for e in errors))
        app._highlight_field(app.start_edit,
                             any("Start" in e for e in errors))
        app._highlight_field(app.end_edit,
                             any("End" in e or "end time" in e.lower()
                                 for e in errors))

        if errors:
            _set_label_style(app.db_match_label, "error")
            app.db_match_label.setText(
                "\u26a0 Found in database but has invalid data \u2014 "
                "fix the highlighted field(s):  " +
                "  |  ".join(errors))
        else:
            _set_label_style(app.db_match_label, "success")
            app.db_match_label.setText(
                "\u2713 Found in database! URL and timestamps loaded.")
    else:
        for f in (app.url_edit, app.start_edit, app.end_edit):
            app._highlight_field(f, False)
        matches = app.song_db.search_songs(title)
        if matches:
            _set_label_style(app.db_match_label, "warning")
            app.db_match_label.setText(
                f"Similar: {', '.join([m[0][:25] for m in matches[:3]])}")
        else:
            _set_label_style(app.db_match_label, "muted")
            app.db_match_label.setText(
                "New song \u2014 will be saved to database.")


# ── Jobs helpers ──────────────────────────────────────────────────────────────

def check_existing_jobs(app) -> None:
    t = app._job_template()
    if t == "auto":
        existing = []
        for d in JOBS_DIRS.values():
            if d.exists():
                existing.extend(d.glob("job_*"))
        if existing:
            app.job_warning_label.setText(
                f"\u26a0\ufe0f {len(existing)} existing job(s) detected across templates")
            app.delete_jobs_btn.setVisible(True)
        else:
            app.job_warning_label.setText("")
            app.delete_jobs_btn.setVisible(False)
        return
    d = JOBS_DIRS.get(t)
    if not d or not d.exists():
        app.job_warning_label.setText("")
        app.delete_jobs_btn.setVisible(False)
        return
    existing = list(d.glob("job_*"))
    if existing:
        app.job_warning_label.setText(
            f"\u26a0\ufe0f {len(existing)} existing job(s) detected")
        app.delete_jobs_btn.setVisible(True)
    else:
        app.job_warning_label.setText("")
        app.delete_jobs_btn.setVisible(False)


def delete_existing_jobs(app) -> None:
    import shutil
    if app.is_processing:
        QMessageBox.warning(app, "Processing",
                            "Cannot delete jobs while processing.")
        return
    t = app._job_template()
    if t == "auto":
        existing = []
        for d in JOBS_DIRS.values():
            if d.exists():
                existing.extend(d.glob("job_*"))
        if not existing:
            return
        reply = QMessageBox.question(
            app, "Confirm Deletion",
            f"Delete {len(existing)} job folder(s) from ALL templates?"
            "\n\nCannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        for j in existing:
            shutil.rmtree(j)
        QMessageBox.information(app, "Deleted",
                                f"Deleted {len(existing)} job folder(s).")
        app._check_existing_jobs()
        return
    d = JOBS_DIRS.get(t)
    existing = list(d.glob("job_*"))
    if not existing:
        return
    reply = QMessageBox.question(
        app, "Confirm Deletion",
        f"Delete {len(existing)} job folder(s) from {t.upper()}?"
        "\n\nCannot be undone.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return
    for j in existing:
        shutil.rmtree(j)
    QMessageBox.information(app, "Deleted",
                            f"Deleted {len(existing)} job folder(s).")
    app._check_existing_jobs()


def open_jobs_folder(app) -> None:
    t = app._job_template()
    if t == "auto":
        # Open the Aurora jobs folder as a representative entry point
        d = JOBS_DIRS["aurora"]
    else:
        d = JOBS_DIRS.get(t)
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(str(d))


def test_lastfm_connection(app) -> None:
    """Test Last.fm API connection from Settings tab."""
    key = app.lastfm_key_edit.text().strip()
    if not key:
        _set_label_style(app.lastfm_status_label, "warning")
        app.lastfm_status_label.setText("Enter your Last.fm API Key first")
        return
    try:
        os.environ["LASTFM_API_KEY"] = key
        from scripts.lastfm_discovery import test_connection
        ok, msg = test_connection()
        if ok:
            _set_label_style(app.lastfm_status_label, "success")
        else:
            _set_label_style(app.lastfm_status_label, "error")
        app.lastfm_status_label.setText(msg)
    except Exception as e:
        _set_label_style(app.lastfm_status_label, "error")
        app.lastfm_status_label.setText(f"Failed: {e}")
