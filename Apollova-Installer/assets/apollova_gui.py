#!/usr/bin/env python3
"""
Apollova - Lyric Video Job Generator
GUI Application with Job Creation and JSX Injection tabs
"""

import os
import sys
import json
import shutil
import threading
import tempfile
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime

# Determine if we're running as a bundled exe or script
if getattr(sys, 'frozen', False):
    # Running as compiled exe (launcher)
    BASE_DIR = Path(sys.executable).parent
    ASSETS_DIR = BASE_DIR / "assets"
    BUNDLED_JSX_DIR = ASSETS_DIR / "scripts" / "JSX"
else:
    # Running as script from assets folder
    ASSETS_DIR = Path(__file__).parent
    BASE_DIR = ASSETS_DIR.parent  # Go up from assets to main folder
    BUNDLED_JSX_DIR = ASSETS_DIR / "scripts" / "JSX"

# Add scripts directory to path for imports
sys.path.insert(0, str(ASSETS_DIR))

# Import processing modules
from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio, detect_beats
from scripts.image_processing import download_image, extract_colors
from scripts.lyric_processing import transcribe_audio
from scripts.song_database import SongDatabase
from scripts.genius_processing import fetch_genius_image
from scripts.smart_picker import SmartSongPicker


# Directory structure constants (relative to BASE_DIR, not assets)
INSTALL_DIR = BASE_DIR  # For compatibility with rest of code
TEMPLATES_DIR = BASE_DIR / "templates"
AURORA_JOBS_DIR = BASE_DIR / "Apollova-Aurora" / "jobs"
MONO_JOBS_DIR = BASE_DIR / "Apollova-Mono" / "jobs"
ONYX_JOBS_DIR = BASE_DIR / "Apollova-Onyx" / "jobs"
DATABASE_DIR = BASE_DIR / "database"
WHISPER_DIR = BASE_DIR / "whisper_models"
SETTINGS_FILE = BASE_DIR / "settings.json"

# Template paths
TEMPLATE_PATHS = {
    "aurora": TEMPLATES_DIR / "Apollova-Aurora.aep",
    "mono": TEMPLATES_DIR / "Apollova-Mono.aep",
    "onyx": TEMPLATES_DIR / "Apollova-Onyx.aep"
}

# Jobs directories
JOBS_DIRS = {
    "aurora": AURORA_JOBS_DIR,
    "mono": MONO_JOBS_DIR,
    "onyx": ONYX_JOBS_DIR
}

# JSX script names
JSX_SCRIPTS = {
    "aurora": "Apollova-Aurora-Injection.jsx",
    "mono": "Apollova-Mono-Injection.jsx",
    "onyx": "Apollova-Onyx-Injection.jsx"
}


class ScrollableFrame(ttk.Frame):
    """A scrollable frame container"""
    
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        self.scrollable_frame.bind('<Enter>', self._bind_mousewheel)
        self.scrollable_frame.bind('<Leave>', self._unbind_mousewheel)
    
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_frame, width=event.width)
    
    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class AppollovaApp:
    """Main GUI Application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Apollova - Lyric Video Generator")
        self.root.geometry("900x750")
        self.root.minsize(750, 550)
        self.root.resizable(True, True)
        
        # Set app icon (if exists)
        icon_path = INSTALL_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        
        # Initialize directories on first launch
        self._init_directories()
        
        # Initialize database
        self.song_db = SongDatabase(db_path=str(DATABASE_DIR / "songs.db"))
        
        # Load settings
        self.settings = self._load_settings()
        
        # Processing state
        self.is_processing = False
        self.cancel_requested = False
        
        # Track input widgets for locking
        self.input_widgets = []
        
        # Setup UI
        self._setup_styles()
        self._create_widgets()
        
        # Auto-detect After Effects
        if not self.settings.get('after_effects_path'):
            detected = self._auto_detect_after_effects()
            if detected:
                self.settings['after_effects_path'] = detected
                self._save_settings()
    
    def _init_directories(self):
        """Create required directories on first launch"""
        dirs_to_create = [
            AURORA_JOBS_DIR,
            MONO_JOBS_DIR,
            ONYX_JOBS_DIR,
            DATABASE_DIR,
            WHISPER_DIR,
            TEMPLATES_DIR
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _load_settings(self):
        """Load settings from file"""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            'after_effects_path': None,
            'genius_api_token': Config.GENIUS_API_TOKEN,
            'whisper_model': Config.WHISPER_MODEL
        }
    
    def _save_settings(self):
        """Save settings to file"""
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=2)
    
    def _auto_detect_after_effects(self):
        """Auto-detect After Effects installation"""
        possible_paths = []
        
        # Check Program Files for various AE versions
        program_files = [
            Path("C:/Program Files/Adobe"),
            Path("C:/Program Files (x86)/Adobe")
        ]
        
        ae_versions = [
            "Adobe After Effects 2025",
            "Adobe After Effects 2024",
            "Adobe After Effects 2023",
            "Adobe After Effects CC 2024",
            "Adobe After Effects CC 2023",
            "Adobe After Effects CC 2022",
            "Adobe After Effects CC 2021",
            "Adobe After Effects CC 2020",
        ]
        
        for pf in program_files:
            if pf.exists():
                for version in ae_versions:
                    ae_path = pf / version / "Support Files" / "AfterFX.exe"
                    if ae_path.exists():
                        return str(ae_path)
        
        return None
    
    def _setup_styles(self):
        """Configure ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'))
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10), foreground='#666666')
        style.configure('Section.TLabelframe.Label', font=('Segoe UI', 10, 'bold'))
        style.configure('Generate.TButton', font=('Segoe UI', 11, 'bold'), padding=10)
        style.configure('Inject.TButton', font=('Segoe UI', 11, 'bold'), padding=10)
        style.configure('Status.TLabel', font=('Segoe UI', 9))
        style.configure('Warning.TLabel', font=('Segoe UI', 9), foreground='#f59e0b')
        style.configure('Success.TLabel', font=('Segoe UI', 9), foreground='#22c55e')
        style.configure('Error.TLabel', font=('Segoe UI', 9), foreground='#ef4444')
        
    def _create_widgets(self):
        """Create all UI widgets"""
        
        # Main container
        outer_frame = ttk.Frame(self.root)
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # === HEADER ===
        header_frame = ttk.Frame(outer_frame, padding="20 15 20 10")
        header_frame.pack(fill=tk.X)
        
        ttk.Label(header_frame, text="🎬 Apollova", style='Title.TLabel').pack(side=tk.LEFT)
        ttk.Label(header_frame, text="Lyric Video Generator", 
                  style='Subtitle.TLabel').pack(side=tk.LEFT, padx=(10, 0), pady=(5, 0))
        
        # Database stats
        stats = self.song_db.get_stats()
        stats_text = f"📊 Database: {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics"
        self.stats_label = ttk.Label(header_frame, text=stats_text, style='Subtitle.TLabel')
        self.stats_label.pack(side=tk.RIGHT)
        
        ttk.Separator(outer_frame, orient='horizontal').pack(fill=tk.X, padx=20)
        
        # === NOTEBOOK (Tabs) ===
        self.notebook = ttk.Notebook(outer_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Tab 1: Job Creation
        self.job_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.job_tab, text="  📁 Job Creation  ")
        self._create_job_tab()
        
        # Tab 2: JSX Injection
        self.inject_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.inject_tab, text="  🚀 JSX Injection  ")
        self._create_inject_tab()
        
        # Tab 3: Settings
        self.settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text="  ⚙ Settings  ")
        self._create_settings_tab()
        
        # Update injection tab when switching to it
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
    
    def _create_job_tab(self):
        """Create the Job Creation tab with Manual/Smart Picker sub-tabs"""
        
        # Scrollable content
        scroll_frame = ScrollableFrame(self.job_tab)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        
        content = scroll_frame.scrollable_frame
        content_padding = ttk.Frame(content, padding="10")
        content_padding.pack(fill=tk.BOTH, expand=True)
        
        # === TEMPLATE SELECTION ===
        template_frame = ttk.LabelFrame(content_padding, text="Template", style='Section.TLabelframe', padding="10")
        template_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.job_template_var = tk.StringVar(value="aurora")
        self.job_template_var.trace_add('write', self._on_template_change)
        
        templates = [
            ("Aurora", "aurora", "Full visual with gradients, spectrum, beat-sync"),
            ("Mono", "mono", "Minimal text-only, black/white alternating"),
            ("Onyx", "onyx", "Hybrid - word-by-word lyrics + spinning vinyl disc")
        ]
        
        for name, value, desc in templates:
            frame = ttk.Frame(template_frame)
            frame.pack(fill=tk.X, pady=2)
            
            rb = ttk.Radiobutton(frame, text=name, variable=self.job_template_var, value=value)
            rb.pack(side=tk.LEFT)
            self.input_widgets.append(rb)
            ttk.Label(frame, text=f"  - {desc}", foreground='#666666').pack(side=tk.LEFT)
        
        # Output path display (read-only)
        path_frame = ttk.Frame(template_frame)
        path_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(path_frame, text="Output:", foreground='#666666').pack(side=tk.LEFT)
        self.output_path_label = ttk.Label(path_frame, text=str(AURORA_JOBS_DIR), foreground='#888888')
        self.output_path_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # === SONG INPUT with Sub-Tabs ===
        song_frame = ttk.LabelFrame(content_padding, text="Song Selection", style='Section.TLabelframe', padding="10")
        song_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Sub-notebook for Manual vs Smart Picker
        self.song_notebook = ttk.Notebook(song_frame)
        self.song_notebook.pack(fill=tk.X, expand=True)
        
        # --- Manual Entry Tab ---
        manual_tab = ttk.Frame(self.song_notebook, padding="10")
        self.song_notebook.add(manual_tab, text="  ✏️ Manual Entry  ")
        
        ttk.Label(manual_tab, text="Song Title (Artist - Song):").pack(anchor=tk.W)
        self.title_entry = ttk.Entry(manual_tab, width=60, font=('Segoe UI', 10))
        self.title_entry.pack(fill=tk.X, pady=(2, 10))
        self.title_entry.bind('<KeyRelease>', self._check_database)
        self.input_widgets.append(self.title_entry)
        
        self.db_match_label = ttk.Label(manual_tab, text="", foreground='#666666')
        self.db_match_label.pack(anchor=tk.W)
        
        ttk.Label(manual_tab, text="YouTube URL:").pack(anchor=tk.W, pady=(10, 0))
        self.url_entry = ttk.Entry(manual_tab, width=60, font=('Segoe UI', 10))
        self.url_entry.pack(fill=tk.X, pady=(2, 10))
        self.input_widgets.append(self.url_entry)
        
        time_frame = ttk.Frame(manual_tab)
        time_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(time_frame, text="Start Time (MM:SS):").pack(side=tk.LEFT)
        self.start_entry = ttk.Entry(time_frame, width=8, font=('Segoe UI', 10))
        self.start_entry.pack(side=tk.LEFT, padx=(5, 20))
        self.start_entry.insert(0, "00:00")
        self.input_widgets.append(self.start_entry)
        
        ttk.Label(time_frame, text="End Time (MM:SS):").pack(side=tk.LEFT)
        self.end_entry = ttk.Entry(time_frame, width=8, font=('Segoe UI', 10))
        self.end_entry.pack(side=tk.LEFT, padx=(5, 0))
        self.end_entry.insert(0, "01:01")
        self.input_widgets.append(self.end_entry)
        
        # --- Smart Picker Tab ---
        smart_tab = ttk.Frame(self.song_notebook, padding="10")
        self.song_notebook.add(smart_tab, text="  🤖 Smart Picker  ")
        
        # Smart Picker description
        desc_text = "Smart Picker automatically selects songs from your database.\n" \
                    "It ensures fair rotation: no song is used twice until all songs have been used once."
        ttk.Label(smart_tab, text=desc_text, foreground='#666666', wraplength=500, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 15))
        
        # Database stats frame
        stats_frame = ttk.Frame(smart_tab)
        stats_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.smart_stats_label = ttk.Label(stats_frame, text="Loading database stats...", style='Status.TLabel')
        self.smart_stats_label.pack(anchor=tk.W)
        
        # Refresh stats button
        ttk.Button(stats_frame, text="🔄 Refresh Stats", command=self._refresh_smart_picker_stats).pack(anchor=tk.W, pady=(5, 0))
        
        # Song preview listbox
        ttk.Label(smart_tab, text="Next songs to be selected:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(10, 5))
        
        list_frame = ttk.Frame(smart_tab)
        list_frame.pack(fill=tk.X)
        
        self.smart_listbox = tk.Listbox(list_frame, height=8, font=('Consolas', 9),
                                         bg='#f5f5f5', selectmode=tk.SINGLE)
        self.smart_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        list_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.smart_listbox.yview)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.smart_listbox.configure(yscrollcommand=list_scrollbar.set)
        
        # Smart picker warning if no songs
        self.smart_warning_label = ttk.Label(smart_tab, text="", style='Warning.TLabel')
        self.smart_warning_label.pack(anchor=tk.W, pady=(10, 0))
        
        # Initialize smart picker display
        self._refresh_smart_picker_stats()
        
        # Track which mode is selected
        self.song_notebook.bind("<<NotebookTabChanged>>", self._on_song_mode_changed)
        self.use_smart_picker = False
        
        # === SETTINGS ===
        settings_frame = ttk.LabelFrame(content_padding, text="Job Settings", style='Section.TLabelframe', padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 15))
        
        settings_row = ttk.Frame(settings_frame)
        settings_row.pack(fill=tk.X)
        
        ttk.Label(settings_row, text="Number of Jobs:").pack(side=tk.LEFT)
        self.jobs_var = tk.StringVar(value="12")
        self.jobs_combo = ttk.Combobox(settings_row, textvariable=self.jobs_var, 
                                       values=["1", "3", "6", "12"], width=5, state='readonly')
        self.jobs_combo.pack(side=tk.LEFT, padx=(5, 20))
        self.input_widgets.append(self.jobs_combo)
        
        ttk.Label(settings_row, text="Whisper Model:").pack(side=tk.LEFT)
        self.whisper_var = tk.StringVar(value=self.settings.get('whisper_model', 'small'))
        self.whisper_combo = ttk.Combobox(settings_row, textvariable=self.whisper_var,
                                          values=["tiny", "base", "small", "medium", "large-v3"],
                                          width=10, state='readonly')
        self.whisper_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.input_widgets.append(self.whisper_combo)
        
        # Job folder warning
        self.job_warning_frame = ttk.Frame(settings_frame)
        self.job_warning_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.job_warning_label = ttk.Label(self.job_warning_frame, text="", style='Warning.TLabel')
        self.job_warning_label.pack(side=tk.LEFT)
        
        self.delete_jobs_btn = ttk.Button(self.job_warning_frame, text="Delete Existing Jobs", 
                                          command=self._delete_existing_jobs)
        self.delete_jobs_btn.pack_forget()
        
        self._check_existing_jobs()
        
        # === PROGRESS ===
        progress_frame = ttk.LabelFrame(content_padding, text="Progress", style='Section.TLabelframe', padding="10")
        progress_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                            maximum=100, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.status_var, style='Status.TLabel').pack(anchor=tk.W)
        
        log_frame = ttk.Frame(progress_frame)
        log_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.log_text = tk.Text(log_frame, height=8, font=('Consolas', 9), 
                                bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
        self.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        # === BUTTONS ===
        button_frame = ttk.Frame(content_padding)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.generate_btn = ttk.Button(button_frame, text="🚀 Generate Jobs", 
                                       style='Generate.TButton', command=self._start_generation)
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.cancel_btn = ttk.Button(button_frame, text="Cancel", command=self._cancel_generation, state='disabled')
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(button_frame, text="Open Jobs Folder", command=self._open_jobs_folder).pack(side=tk.LEFT)
    
    def _on_song_mode_changed(self, event=None):
        """Handle switching between Manual and Smart Picker modes"""
        selected_tab = self.song_notebook.index(self.song_notebook.select())
        self.use_smart_picker = (selected_tab == 1)  # 0 = Manual, 1 = Smart Picker
        
        if self.use_smart_picker:
            self._refresh_smart_picker_stats()
    
    def _refresh_smart_picker_stats(self):
        """Refresh the Smart Picker statistics and song list"""
        try:
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            stats = picker.get_database_stats()
            
            # Update stats label
            if stats['total_songs'] == 0:
                self.smart_stats_label.config(
                    text="📊 Database is empty. Add songs using Manual Entry first.",
                    style='Warning.TLabel'
                )
                self.smart_warning_label.config(
                    text="⚠️ No songs available. Use Manual Entry to add songs to the database."
                )
                self.smart_listbox.delete(0, tk.END)
                return
            
            stats_text = f"📊 Total: {stats['total_songs']} songs | " \
                        f"Unused: {stats['unused_songs']} | " \
                        f"Uses: {stats['min_uses']}-{stats['max_uses']} (avg: {stats['avg_uses']})"
            self.smart_stats_label.config(text=stats_text, style='Status.TLabel')
            
            # Get preview of next songs
            num_jobs = int(self.jobs_var.get())
            songs = picker.get_available_songs(num_songs=num_jobs)
            
            # Update listbox
            self.smart_listbox.delete(0, tk.END)
            for i, song in enumerate(songs, 1):
                status = "🆕 new" if song['use_count'] == 1 else f"📊 {song['use_count']}x"
                display = f"{i:2}. {song['song_title'][:45]:<45} ({status})"
                self.smart_listbox.insert(tk.END, display)
            
            # Update warning
            if len(songs) < num_jobs:
                self.smart_warning_label.config(
                    text=f"⚠️ Only {len(songs)} songs available, but {num_jobs} requested."
                )
            else:
                self.smart_warning_label.config(text="")
                
        except Exception as e:
            self.smart_stats_label.config(
                text=f"❌ Error loading database: {e}",
                style='Error.TLabel'
            )
    
    def _create_inject_tab(self):
        """Create the JSX Injection tab"""
        
        # Create outer frame to hold canvas and scrollbar
        outer_frame = ttk.Frame(self.inject_tab)
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create canvas and scrollbar for scrolling
        inject_canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=inject_canvas.yview)
        scrollable_frame = ttk.Frame(inject_canvas, padding="20")
        
        # Create window and store the ID
        canvas_window = inject_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Configure scroll region when frame size changes
        def configure_scroll(event):
            inject_canvas.configure(scrollregion=inject_canvas.bbox("all"))
        scrollable_frame.bind("<Configure>", configure_scroll)
        
        # Resize the canvas window width when canvas is resized
        def configure_canvas(event):
            inject_canvas.itemconfig(canvas_window, width=event.width)
        inject_canvas.bind("<Configure>", configure_canvas)
        
        inject_canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enable mousewheel scrolling only when mouse is over this canvas
        def _on_mousewheel_inject(event):
            inject_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel_inject(event):
            inject_canvas.bind_all("<MouseWheel>", _on_mousewheel_inject)
        
        def _unbind_mousewheel_inject(event):
            inject_canvas.unbind_all("<MouseWheel>")
        
        inject_canvas.bind("<Enter>", _bind_mousewheel_inject)
        inject_canvas.bind("<Leave>", _unbind_mousewheel_inject)
        
        scrollbar.pack(side="right", fill="y")
        inject_canvas.pack(side="left", fill="both", expand=True)
        
        content = scrollable_frame
        
        # === TEMPLATE SELECTION ===
        template_frame = ttk.LabelFrame(content, text="Individual Template Injection", style='Section.TLabelframe', padding="15")
        template_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.inject_template_var = tk.StringVar(value="aurora")
        self.inject_template_var.trace_add('write', self._update_inject_status)
        
        templates = [
            ("Aurora", "aurora", "Full visual template"),
            ("Mono", "mono", "Minimal text template"),
            ("Onyx", "onyx", "Hybrid vinyl template")
        ]
        
        for name, value, desc in templates:
            frame = ttk.Frame(template_frame)
            frame.pack(fill=tk.X, pady=3)
            
            rb = ttk.Radiobutton(frame, text=f"{name}", variable=self.inject_template_var, value=value)
            rb.pack(side=tk.LEFT)
            ttk.Label(frame, text=f"  - {desc}", foreground='#666666').pack(side=tk.LEFT)
        
        # === STATUS ===
        status_frame = ttk.LabelFrame(content, text="Status", style='Section.TLabelframe', padding="15")
        status_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Jobs status
        jobs_row = ttk.Frame(status_frame)
        jobs_row.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(jobs_row, text="Jobs:", width=15, anchor='w').pack(side=tk.LEFT)
        self.inject_jobs_label = ttk.Label(jobs_row, text="Checking...", style='Status.TLabel')
        self.inject_jobs_label.pack(side=tk.LEFT)
        
        # Template status
        template_row = ttk.Frame(status_frame)
        template_row.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(template_row, text="Template File:", width=15, anchor='w').pack(side=tk.LEFT)
        self.inject_template_label = ttk.Label(template_row, text="Checking...", style='Status.TLabel')
        self.inject_template_label.pack(side=tk.LEFT)
        
        # After Effects status
        ae_row = ttk.Frame(status_frame)
        ae_row.pack(fill=tk.X)
        
        ttk.Label(ae_row, text="After Effects:", width=15, anchor='w').pack(side=tk.LEFT)
        self.inject_ae_label = ttk.Label(ae_row, text="Checking...", style='Status.TLabel')
        self.inject_ae_label.pack(side=tk.LEFT)
        
        # Refresh button
        refresh_row = ttk.Frame(status_frame)
        refresh_row.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(refresh_row, text="Refresh Status", command=self._update_inject_status).pack(side=tk.LEFT)
        
        # Install path info (for debugging)
        path_row = ttk.Frame(status_frame)
        path_row.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(path_row, text=f"Install Dir: {INSTALL_DIR}", foreground='#888888', font=('Consolas', 8)).pack(anchor=tk.W)
        
        # === INJECT BUTTON ===
        button_frame = ttk.Frame(content)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.inject_btn = ttk.Button(button_frame, text="Launch After Effects & Inject", 
                                     style='Inject.TButton', command=self._run_injection)
        self.inject_btn.pack(side=tk.LEFT)
        
        # Info text
        info_frame = ttk.Frame(content)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        info_text = (
            "This will launch AE, open the template, and inject job data.\n"
            "After injection, review the comps and manually add to render queue."
        )
        ttk.Label(info_frame, text=info_text, foreground='#666666', justify=tk.LEFT).pack(anchor=tk.W)
        
        # === BATCH RENDER ALL SECTION ===
        batch_frame = ttk.LabelFrame(content, text="Batch Render All Templates", style='Section.TLabelframe', padding="15")
        batch_frame.pack(fill=tk.X, pady=(20, 0))
        
        # Batch status header
        ttk.Label(batch_frame, text="Templates Ready:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)
        
        # Status for each template
        self.batch_status_labels = {}
        for name, value, desc in templates:
            row = ttk.Frame(batch_frame)
            row.pack(fill=tk.X, pady=2)
            
            self.batch_status_labels[value] = ttk.Label(row, text=f"  {name}: Checking...", style='Status.TLabel')
            self.batch_status_labels[value].pack(side=tk.LEFT)
        
        # Batch progress section
        progress_frame = ttk.Frame(batch_frame)
        progress_frame.pack(fill=tk.X, pady=(15, 10))
        
        self.batch_status_var = tk.StringVar(value="Status: Idle")
        self.batch_status_label = ttk.Label(progress_frame, textvariable=self.batch_status_var, font=('Segoe UI', 9))
        self.batch_status_label.pack(anchor=tk.W)
        
        self.batch_progress_var = tk.DoubleVar(value=0)
        self.batch_progress = ttk.Progressbar(progress_frame, variable=self.batch_progress_var, maximum=100, length=400)
        self.batch_progress.pack(fill=tk.X, pady=(5, 5))
        
        self.batch_current_var = tk.StringVar(value="")
        self.batch_current_label = ttk.Label(progress_frame, textvariable=self.batch_current_var, foreground='#666666')
        self.batch_current_label.pack(anchor=tk.W)
        
        # Render All button
        batch_btn_frame = ttk.Frame(batch_frame)
        batch_btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.render_all_btn = ttk.Button(batch_btn_frame, text="Render All", 
                                          style='Inject.TButton', command=self._start_batch_render)
        self.render_all_btn.pack(side=tk.LEFT)
        
        self.batch_cancel_btn = ttk.Button(batch_btn_frame, text="Cancel", 
                                            command=self._cancel_batch_render, state='disabled')
        self.batch_cancel_btn.pack(side=tk.LEFT, padx=(10, 0))
        
        # Batch info
        batch_info = (
            "Renders all templates with jobs sequentially (Aurora → Mono → Onyx).\n"
            "Each template will auto-inject, render, then close before the next starts.\n"
            "Requires at least 2 templates with jobs to enable."
        )
        ttk.Label(batch_frame, text=batch_info, foreground='#666666', justify=tk.LEFT).pack(anchor=tk.W, pady=(10, 0))
        
        # Batch render state
        self.batch_render_active = False
        self.batch_render_cancelled = False
        self.batch_results = {}
        
        # Update status
        self._update_inject_status()
        self._update_batch_status()
    
    def _create_settings_tab(self):
        """Create the Settings tab"""
        
        # Create outer frame to hold canvas and scrollbar
        outer_frame = ttk.Frame(self.settings_tab)
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create canvas and scrollbar for scrolling
        settings_canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=settings_canvas.yview)
        scrollable_frame = ttk.Frame(settings_canvas, padding="20")
        
        # Create window and store the ID
        canvas_window = settings_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Configure scroll region when frame size changes
        def configure_scroll(event):
            settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
        scrollable_frame.bind("<Configure>", configure_scroll)
        
        # Resize the canvas window width when canvas is resized
        def configure_canvas(event):
            settings_canvas.itemconfig(canvas_window, width=event.width)
        settings_canvas.bind("<Configure>", configure_canvas)
        
        settings_canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enable mousewheel scrolling only when mouse is over this canvas
        def _on_mousewheel_settings(event):
            settings_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel_settings(event):
            settings_canvas.bind_all("<MouseWheel>", _on_mousewheel_settings)
        
        def _unbind_mousewheel_settings(event):
            settings_canvas.unbind_all("<MouseWheel>")
        
        settings_canvas.bind("<Enter>", _bind_mousewheel_settings)
        settings_canvas.bind("<Leave>", _unbind_mousewheel_settings)
        
        scrollbar.pack(side="right", fill="y")
        settings_canvas.pack(side="left", fill="both", expand=True)
        
        content = scrollable_frame
        
        # === AFTER EFFECTS ===
        ae_frame = ttk.LabelFrame(content, text="Adobe After Effects", style='Section.TLabelframe', padding="15")
        ae_frame.pack(fill=tk.X, pady=(0, 20))
        
        ae_path_row = ttk.Frame(ae_frame)
        ae_path_row.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ae_path_row, text="Path:").pack(side=tk.LEFT)
        
        self.ae_path_var = tk.StringVar(value=self.settings.get('after_effects_path', ''))
        self.ae_path_entry = ttk.Entry(ae_path_row, textvariable=self.ae_path_var, width=50)
        self.ae_path_entry.pack(side=tk.LEFT, padx=(10, 10), fill=tk.X, expand=True)
        
        ttk.Button(ae_path_row, text="Browse...", command=self._browse_ae_path).pack(side=tk.LEFT)
        ttk.Button(ae_path_row, text="Auto-Detect", command=self._auto_detect_ae_click).pack(side=tk.LEFT, padx=(5, 0))
        
        # AE status
        self.ae_status_label = ttk.Label(ae_frame, text="", style='Status.TLabel')
        self.ae_status_label.pack(anchor=tk.W)
        self._update_ae_status()
        
        # === GENIUS API ===
        genius_frame = ttk.LabelFrame(content, text="Genius API", style='Section.TLabelframe', padding="15")
        genius_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(genius_frame, text="API Token:").pack(anchor=tk.W)
        
        self.genius_var = tk.StringVar(value=self.settings.get('genius_api_token', ''))
        genius_entry = ttk.Entry(genius_frame, textvariable=self.genius_var, width=60, show='*')
        genius_entry.pack(fill=tk.X, pady=(5, 5))
        
        ttk.Label(genius_frame, text="Get your token at: https://genius.com/api-clients", 
                  foreground='#666666').pack(anchor=tk.W)
        
        # === FFMPEG ===
        ffmpeg_frame = ttk.LabelFrame(content, text="FFmpeg", style='Section.TLabelframe', padding="15")
        ffmpeg_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.ffmpeg_status_label = ttk.Label(ffmpeg_frame, text="Checking...", style='Status.TLabel')
        self.ffmpeg_status_label.pack(anchor=tk.W)
        self._check_ffmpeg()
        
        # === SAVE BUTTON ===
        button_frame = ttk.Frame(content)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(button_frame, text="Save Settings", command=self._save_all_settings).pack(side=tk.LEFT)
        
        # === PATHS INFO ===
        paths_frame = ttk.LabelFrame(content, text="Installation Paths (Read-Only)", style='Section.TLabelframe', padding="15")
        paths_frame.pack(fill=tk.X, pady=(20, 0))
        
        paths_info = f"""Install Directory: {INSTALL_DIR}
Templates: {TEMPLATES_DIR}
Aurora Jobs: {AURORA_JOBS_DIR}
Mono Jobs: {MONO_JOBS_DIR}
Onyx Jobs: {ONYX_JOBS_DIR}
Database: {DATABASE_DIR}"""
        
        ttk.Label(paths_frame, text=paths_info, foreground='#666666', font=('Consolas', 8)).pack(anchor=tk.W)
    
    def _on_tab_changed(self, event):
        """Handle tab change events"""
        selected_tab = self.notebook.index(self.notebook.select())
        if selected_tab == 1:  # JSX Injection tab
            self._update_inject_status()
            self._update_batch_status()
    
    def _on_template_change(self, *args):
        """Update output path when template changes"""
        template = self.job_template_var.get()
        jobs_dir = JOBS_DIRS.get(template, AURORA_JOBS_DIR)
        self.output_path_label.config(text=str(jobs_dir))
        self._check_existing_jobs()
    
    def _update_inject_status(self, *args):
        """Update the injection tab status"""
        template = self.inject_template_var.get()
        
        # Check jobs
        jobs_dir = JOBS_DIRS.get(template)
        if jobs_dir and jobs_dir.exists():
            job_folders = list(jobs_dir.glob("job_*"))
            if job_folders:
                self.inject_jobs_label.config(
                    text=f"✓ {len(job_folders)} job(s) found in {jobs_dir.name}",
                    style='Success.TLabel'
                )
                jobs_ok = True
            else:
                self.inject_jobs_label.config(
                    text=f"✗ No jobs in {jobs_dir}",
                    style='Error.TLabel'
                )
                jobs_ok = False
        else:
            self.inject_jobs_label.config(
                text=f"✗ Folder not found: {jobs_dir}",
                style='Error.TLabel'
            )
            jobs_ok = False
        
        # Check template file
        template_path = TEMPLATE_PATHS.get(template)
        if template_path and template_path.exists():
            self.inject_template_label.config(
                text=f"✓ {template_path.name}",
                style='Success.TLabel'
            )
            template_ok = True
        else:
            self.inject_template_label.config(
                text=f"✗ Template not found: {template_path.name if template_path else 'Unknown'}",
                style='Error.TLabel'
            )
            template_ok = False
        
        # Check After Effects
        ae_path = self.settings.get('after_effects_path')
        if ae_path and Path(ae_path).exists():
            self.inject_ae_label.config(
                text=f"✓ Found",
                style='Success.TLabel'
            )
            ae_ok = True
        else:
            self.inject_ae_label.config(
                text="✗ Not configured - go to Settings tab",
                style='Error.TLabel'
            )
            ae_ok = False
        
        # Enable/disable inject button
        if jobs_ok and template_ok and ae_ok:
            self.inject_btn.config(state='normal')
        else:
            self.inject_btn.config(state='disabled')
    
    def _update_ae_status(self):
        """Update After Effects status in settings"""
        ae_path = self.ae_path_var.get()
        if ae_path and Path(ae_path).exists():
            self.ae_status_label.config(text="✓ After Effects found", style='Success.TLabel')
        elif ae_path:
            self.ae_status_label.config(text="✗ Path not found", style='Error.TLabel')
        else:
            self.ae_status_label.config(text="⚠ Not configured - click Auto-Detect or Browse", style='Warning.TLabel')
    
    def _check_ffmpeg(self):
        """Check FFmpeg availability"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                self.ffmpeg_status_label.config(text="✓ FFmpeg found in PATH", style='Success.TLabel')
            else:
                self.ffmpeg_status_label.config(text="✗ FFmpeg not working properly", style='Error.TLabel')
        except FileNotFoundError:
            self.ffmpeg_status_label.config(text="✗ FFmpeg not found - please install and add to PATH", style='Error.TLabel')
        except Exception as e:
            self.ffmpeg_status_label.config(text=f"✗ Error checking FFmpeg: {e}", style='Error.TLabel')
    
    def _browse_ae_path(self):
        """Browse for After Effects executable"""
        path = filedialog.askopenfilename(
            title="Select AfterFX.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
            initialdir="C:/Program Files/Adobe"
        )
        if path:
            self.ae_path_var.set(path)
            self._update_ae_status()
    
    def _auto_detect_ae_click(self):
        """Handle auto-detect button click"""
        detected = self._auto_detect_after_effects()
        if detected:
            self.ae_path_var.set(detected)
            self._update_ae_status()
            messagebox.showinfo("Found", f"After Effects found:\n{detected}")
        else:
            messagebox.showwarning("Not Found", "Could not auto-detect After Effects.\n\nPlease browse manually.")
    
    def _save_all_settings(self):
        """Save all settings"""
        self.settings['after_effects_path'] = self.ae_path_var.get()
        self.settings['genius_api_token'] = self.genius_var.get()
        self.settings['whisper_model'] = self.whisper_var.get()
        
        # Update config
        Config.GENIUS_API_TOKEN = self.genius_var.get()
        Config.WHISPER_MODEL = self.whisper_var.get()
        
        # Save to file
        self._save_settings()
        
        # Also save to .env for compatibility
        env_path = INSTALL_DIR / ".env"
        with open(env_path, 'w') as f:
            f.write(f"GENIUS_API_TOKEN={self.genius_var.get()}\n")
            f.write(f"WHISPER_MODEL={self.whisper_var.get()}\n")
        
        messagebox.showinfo("Saved", "Settings saved successfully!")
        
        # Update inject status
        self._update_inject_status()
    
    def _run_injection(self):
        """Run the JSX injection"""
        template = self.inject_template_var.get()
        
        # Get paths
        ae_path = self.settings.get('after_effects_path')
        template_path = TEMPLATE_PATHS.get(template)
        jobs_dir = JOBS_DIRS.get(template)
        jsx_name = JSX_SCRIPTS.get(template)
        
        # Extract JSX to temp file
        try:
            jsx_source = BUNDLED_JSX_DIR / jsx_name
            if not jsx_source.exists():
                # Fallback: check install dir
                jsx_source = ASSETS_DIR / "scripts" / "JSX" / jsx_name
            
            if not jsx_source.exists():
                messagebox.showerror("Error", f"JSX script not found: {jsx_name}\n\nPlease reinstall the application.")
                return
            
            # Copy to temp
            temp_dir = Path(tempfile.gettempdir()) / "Apollova"
            temp_dir.mkdir(exist_ok=True)
            temp_jsx = temp_dir / jsx_name
            
            shutil.copy(jsx_source, temp_jsx)
            
            # Inject the jobs path into the JSX
            self._prepare_jsx_with_path(temp_jsx, jobs_dir, template_path)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to prepare JSX script:\n{e}")
            return
        
        # Launch After Effects with the script
        # The script itself will open the template via app.open()
        try:
            # Only pass the script - it will open the .aep via app.open()
            cmd = [ae_path, "-r", str(temp_jsx)]
            subprocess.Popen(cmd)
            
            messagebox.showinfo(
                "Launched",
                f"After Effects is launching...\n\n"
                f"Template: {template_path.name}\n"
                f"Jobs: {jobs_dir}\n\n"
                "The script will open the project and inject the jobs.\n"
                "Please wait for the process to complete."
            )
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch After Effects:\n{e}")
    
    def _prepare_jsx_with_path(self, jsx_path, jobs_dir, template_path, auto_render=False):
        """Inject the jobs path into the JSX file"""
        with open(jsx_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace placeholder paths
        content = content.replace('{{JOBS_PATH}}', str(jobs_dir).replace('\\', '/'))
        content = content.replace('{{TEMPLATE_PATH}}', str(template_path).replace('\\', '/'))
        content = content.replace('{{AUTO_RENDER}}', 'true' if auto_render else 'false')
        
        with open(jsx_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _update_batch_status(self):
        """Update the batch render status for all templates"""
        templates_ready = []
        ae_path = self.settings.get('after_effects_path')
        ae_ok = ae_path and Path(ae_path).exists()
        
        for template in ['aurora', 'mono', 'onyx']:
            jobs_dir = JOBS_DIRS.get(template)
            template_path = TEMPLATE_PATHS.get(template)
            jsx_name = JSX_SCRIPTS.get(template)
            
            # Check all prerequisites (same as individual render)
            jobs_ok = jobs_dir and jobs_dir.exists() and list(jobs_dir.glob("job_*"))
            template_ok = template_path and template_path.exists()
            
            # Check JSX script exists
            jsx_source = BUNDLED_JSX_DIR / jsx_name if jsx_name else None
            if jsx_source and not jsx_source.exists():
                jsx_source = ASSETS_DIR / "scripts" / "JSX" / jsx_name
            jsx_ok = jsx_source and jsx_source.exists()
            
            if jobs_ok:
                job_count = len(list(jobs_dir.glob("job_*")))
                if template_ok and jsx_ok:
                    self.batch_status_labels[template].config(
                        text=f"  {template.capitalize()}: {job_count} jobs ready",
                        style='Success.TLabel'
                    )
                    templates_ready.append(template)
                elif not template_ok:
                    self.batch_status_labels[template].config(
                        text=f"  {template.capitalize()}: {job_count} jobs (no template file)",
                        style='Warning.TLabel'
                    )
                elif not jsx_ok:
                    self.batch_status_labels[template].config(
                        text=f"  {template.capitalize()}: {job_count} jobs (JSX script missing)",
                        style='Warning.TLabel'
                    )
            else:
                self.batch_status_labels[template].config(
                    text=f"  {template.capitalize()}: No jobs",
                    style='Status.TLabel'
                )
        
        # Enable/disable Render All button (need at least 2 templates ready + AE)
        if len(templates_ready) >= 2 and ae_ok and not self.batch_render_active:
            self.render_all_btn.config(state='normal')
        else:
            self.render_all_btn.config(state='disabled')
        
        return templates_ready
    
    def _start_batch_render(self):
        """Start the batch render process"""
        templates_ready = self._update_batch_status()
        
        if len(templates_ready) < 2:
            messagebox.showerror("Error", "Need at least 2 templates with jobs to use Render All.")
            return
        
        # Build summary
        summary_lines = ["Ready to render:"]
        for t in templates_ready:
            jobs_dir = JOBS_DIRS.get(t)
            job_count = len(list(jobs_dir.glob("job_*")))
            summary_lines.append(f"  - {t.capitalize()}: {job_count} jobs")
        summary_lines.append("")
        summary_lines.append("This will take a while. AE will open, inject, render,")
        summary_lines.append("and close for each template automatically.")
        summary_lines.append("")
        summary_lines.append("Continue?")
        
        if not messagebox.askyesno("Confirm Batch Render", "\n".join(summary_lines)):
            return
        
        # Start batch render in thread
        self.batch_render_active = True
        self.batch_render_cancelled = False
        self.batch_results = {}
        
        # Update UI
        self.render_all_btn.config(state='disabled')
        self.batch_cancel_btn.config(state='normal')
        self.inject_btn.config(state='disabled')
        
        # Start thread
        thread = threading.Thread(target=self._batch_render_thread, args=(templates_ready,), daemon=True)
        thread.start()
    
    def _cancel_batch_render(self):
        """Cancel the batch render process"""
        if messagebox.askyesno("Cancel Batch Render", "Are you sure you want to cancel?\n\nThe current render will complete, but no more templates will be processed."):
            self.batch_render_cancelled = True
            self.batch_status_var.set("Status: Cancelling after current render...")
    
    def _batch_render_thread(self, templates):
        """Thread function for batch rendering"""
        total = len(templates)
        
        for idx, template in enumerate(templates):
            if self.batch_render_cancelled:
                self.root.after(0, lambda: self._batch_update_progress(
                    f"Status: Cancelled",
                    (idx / total) * 100,
                    "Batch render was cancelled"
                ))
                break
            
            # Update progress
            self.root.after(0, lambda t=template, i=idx: self._batch_update_progress(
                f"Status: Rendering {t.capitalize()} ({i+1}/{total})",
                (i / total) * 100,
                f"Launching After Effects for {t.capitalize()}..."
            ))
            
            # Run injection + render for this template
            success, error_msg = self._run_batch_template(template)
            
            self.batch_results[template] = {
                'success': success,
                'error': error_msg
            }
            
            if success:
                self.root.after(0, lambda t=template: self._batch_update_template_status(
                    t, f"  {t.capitalize()}: Complete", 'Success.TLabel'
                ))
            else:
                self.root.after(0, lambda t=template, e=error_msg: self._batch_update_template_status(
                    t, f"  {t.capitalize()}: Failed - {e}", 'Error.TLabel'
                ))
        
        # Complete
        self.root.after(0, self._batch_render_complete)
    
    def _batch_update_progress(self, status, progress, current):
        """Update batch progress UI (called from main thread)"""
        self.batch_status_var.set(status)
        self.batch_progress_var.set(progress)
        self.batch_current_var.set(current)
    
    def _batch_update_template_status(self, template, text, style):
        """Update individual template status (called from main thread)"""
        self.batch_status_labels[template].config(text=text, style=style)
    
    def _run_batch_template(self, template):
        """Run injection + render for a single template. Returns (success, error_msg)"""
        ae_path = self.settings.get('after_effects_path')
        template_path = TEMPLATE_PATHS.get(template)
        jobs_dir = JOBS_DIRS.get(template)
        jsx_name = JSX_SCRIPTS.get(template)
        
        try:
            # Find JSX source
            jsx_source = BUNDLED_JSX_DIR / jsx_name
            if not jsx_source.exists():
                jsx_source = ASSETS_DIR / "scripts" / "JSX" / jsx_name
            
            if not jsx_source.exists():
                return False, f"JSX not found: {jsx_name}"
            
            # Copy to temp and inject paths with AUTO_RENDER=true
            temp_dir = Path(tempfile.gettempdir()) / "Apollova"
            temp_dir.mkdir(exist_ok=True)
            temp_jsx = temp_dir / f"batch_{jsx_name}"
            
            shutil.copy(jsx_source, temp_jsx)
            self._prepare_jsx_with_path(temp_jsx, jobs_dir, template_path, auto_render=True)
            
            # Create error log path (JSX will write here if error occurs)
            error_log = jobs_dir / "batch_error.txt"
            if error_log.exists():
                error_log.unlink()
            
            # Launch AE and wait for it to complete
            cmd = [ae_path, "-r", str(temp_jsx)]
            
            self.root.after(0, lambda: self._batch_update_progress(
                self.batch_status_var.get(),
                self.batch_progress_var.get(),
                f"Rendering {template.capitalize()}... (this may take a while)"
            ))
            
            process = subprocess.Popen(cmd)
            
            # Wait for process to complete
            process.wait()
            
            # Check for error log
            if error_log.exists():
                with open(error_log, 'r') as f:
                    error_msg = f.read().strip()
                return False, error_msg
            
            return True, None
            
        except Exception as e:
            return False, str(e)
    
    def _batch_render_complete(self):
        """Called when batch render is complete"""
        self.batch_render_active = False
        
        # Update UI
        self.render_all_btn.config(state='normal')
        self.batch_cancel_btn.config(state='disabled')
        self.inject_btn.config(state='normal')
        self.batch_progress_var.set(100)
        
        # Build results summary
        success_count = sum(1 for r in self.batch_results.values() if r['success'])
        fail_count = sum(1 for r in self.batch_results.values() if not r['success'])
        
        if self.batch_render_cancelled:
            self.batch_status_var.set("Status: Cancelled")
            self.batch_current_var.set(f"Completed {success_count} template(s) before cancellation")
        else:
            self.batch_status_var.set("Status: Complete")
            self.batch_current_var.set(f"Success: {success_count}, Failed: {fail_count}")
        
        # Show summary dialog
        summary_lines = ["Batch Render Complete\n"]
        for template, result in self.batch_results.items():
            if result['success']:
                summary_lines.append(f"{template.capitalize()}: Success")
            else:
                summary_lines.append(f"{template.capitalize()}: Failed - {result['error']}")
        
        if self.batch_render_cancelled:
            summary_lines.append("\nBatch was cancelled by user.")
        
        messagebox.showinfo("Batch Render Complete", "\n".join(summary_lines))
        
        # Refresh status
        self._update_batch_status()
    
    def _check_existing_jobs(self):
        """Check if job folders already exist"""
        template = self.job_template_var.get()
        jobs_dir = JOBS_DIRS.get(template)
        
        if not jobs_dir or not jobs_dir.exists():
            self.job_warning_label.config(text="")
            self.delete_jobs_btn.pack_forget()
            return
        
        existing_jobs = list(jobs_dir.glob("job_*"))
        
        if existing_jobs:
            self.job_warning_label.config(
                text=f"⚠️ {len(existing_jobs)} existing job folder(s) detected"
            )
            self.delete_jobs_btn.pack(side=tk.LEFT, padx=(10, 0))
        else:
            self.job_warning_label.config(text="")
            self.delete_jobs_btn.pack_forget()
    
    def _delete_existing_jobs(self):
        """Delete existing job folders"""
        if self.is_processing:
            messagebox.showwarning("Processing", "Cannot delete jobs while processing.")
            return
        
        template = self.job_template_var.get()
        jobs_dir = JOBS_DIRS.get(template)
        existing_jobs = list(jobs_dir.glob("job_*"))
        
        if not existing_jobs:
            return
        
        result = messagebox.askyesno(
            "Confirm Deletion",
            f"Delete {len(existing_jobs)} job folder(s) from {template.upper()}?\n\nThis cannot be undone.",
            icon='warning'
        )
        
        if not result:
            return
        
        for job_folder in existing_jobs:
            try:
                shutil.rmtree(job_folder)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete {job_folder.name}: {e}")
                return
        
        messagebox.showinfo("Deleted", f"Deleted {len(existing_jobs)} job folder(s).")
        self._check_existing_jobs()
    
    def _check_database(self, event=None):
        """Check if song exists in database"""
        title = self.title_entry.get().strip()
        if len(title) < 3:
            self.db_match_label.config(text="")
            return
        
        cached = self.song_db.get_song(title)
        if cached:
            self.db_match_label.config(
                text="✓ Found in database! URL and timestamps loaded.",
                foreground='#22c55e'
            )
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, cached['youtube_url'])
            self.start_entry.delete(0, tk.END)
            self.start_entry.insert(0, cached['start_time'])
            self.end_entry.delete(0, tk.END)
            self.end_entry.insert(0, cached['end_time'])
        else:
            matches = self.song_db.search_songs(title)
            if matches:
                self.db_match_label.config(
                    text=f"Similar: {', '.join([m[0][:25] for m in matches[:3]])}",
                    foreground='#f59e0b'
                )
            else:
                self.db_match_label.config(
                    text="New song - will be saved to database.",
                    foreground='#666666'
                )
    
    def _open_jobs_folder(self):
        """Open the jobs folder"""
        template = self.job_template_var.get()
        jobs_dir = JOBS_DIRS.get(template)
        jobs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(jobs_dir))
    
    def _log(self, message):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')
        self.status_var.set(message[:80])
    
    def _validate_inputs(self):
        """Validate inputs based on current mode (Manual or Smart Picker)"""
        errors = []
        
        if self.use_smart_picker:
            # Smart Picker mode - check database has songs
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            stats = picker.get_database_stats()
            
            if stats['total_songs'] == 0:
                errors.append("Database is empty. Add songs using Manual Entry first.")
            else:
                num_jobs = int(self.jobs_var.get())
                songs = picker.get_available_songs(num_songs=num_jobs)
                if len(songs) == 0:
                    errors.append("No songs available in database.")
        else:
            # Manual mode - validate form fields
            if not self.title_entry.get().strip():
                errors.append("Song title is required")
            
            if not self.url_entry.get().strip():
                cached = self.song_db.get_song(self.title_entry.get().strip())
                if not cached:
                    errors.append("YouTube URL is required")
            
            start = self.start_entry.get().strip()
            end = self.end_entry.get().strip()
            
            try:
                s_parts = start.split(':')
                e_parts = end.split(':')
                if len(s_parts) != 2 or len(e_parts) != 2:
                    raise ValueError()
                s_ms = int(s_parts[0]) * 60 + int(s_parts[1])
                e_ms = int(e_parts[0]) * 60 + int(e_parts[1])
                if s_ms >= e_ms:
                    errors.append("End time must be after start time")
            except:
                errors.append("Invalid time format (use MM:SS)")
        
        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors))
            return False
        return True
    
    def _lock_inputs(self, lock=True):
        """Lock/unlock inputs"""
        state = 'disabled' if lock else 'normal'
        for widget in self.input_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state='disabled' if lock else 'readonly')
                else:
                    widget.configure(state=state)
            except:
                pass
    
    def _start_generation(self):
        """Start job generation"""
        if not self._validate_inputs():
            return
        
        template = self.job_template_var.get()
        jobs_dir = JOBS_DIRS.get(template)
        existing = list(jobs_dir.glob("job_*")) if jobs_dir.exists() else []
        
        # Smart Picker confirmation
        if self.use_smart_picker:
            num_jobs = int(self.jobs_var.get())
            picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
            songs = picker.get_available_songs(num_songs=num_jobs)
            
            # Build confirmation message
            song_list = "\n".join([f"  {i+1}. {s['song_title'][:40]}" for i, s in enumerate(songs[:12])])
            if len(songs) > 12:
                song_list += f"\n  ... and {len(songs) - 12} more"
            
            result = messagebox.askyesno(
                "Smart Picker Confirmation",
                f"Generate {len(songs)} jobs for {template.upper()} template?\n\n"
                f"Songs selected:\n{song_list}\n\n"
                "Continue?",
                icon='question'
            )
            if not result:
                return
        
        if existing:
            result = messagebox.askyesnocancel(
                "Existing Jobs",
                f"Found {len(existing)} existing jobs.\n\n"
                "Yes = Delete and continue\n"
                "No = Keep and continue\n"
                "Cancel = Abort"
            )
            if result is None:
                return
            elif result:
                for j in existing:
                    shutil.rmtree(j)
                self._check_existing_jobs()
        
        self.is_processing = True
        self.cancel_requested = False
        self._lock_inputs(True)
        self.generate_btn.configure(state='disabled')
        self.cancel_btn.configure(state='normal')
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.progress_var.set(0)
        
        thread = threading.Thread(target=self._process_jobs, daemon=True)
        thread.start()
    
    def _cancel_generation(self):
        """Cancel generation"""
        self.cancel_requested = True
        self._log("Cancellation requested...")
    
    def _process_jobs(self):
        """Process jobs (runs in thread) - handles both Manual and Smart Picker modes"""
        try:
            num_jobs = int(self.jobs_var.get())
            template = self.job_template_var.get()
            output_dir = JOBS_DIRS.get(template)
            
            Config.WHISPER_MODEL = self.whisper_var.get()
            
            if self.use_smart_picker:
                # SMART PICKER MODE - process multiple different songs
                self._log(f"🤖 Smart Picker Mode: {num_jobs} songs")
                self._log(f"Template: {template.upper()}")
                
                picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
                songs = picker.get_available_songs(num_songs=num_jobs)
                
                output_dir.mkdir(parents=True, exist_ok=True)
                
                total_songs = len(songs)
                for idx, song in enumerate(songs, 1):
                    if self.cancel_requested:
                        raise Exception("Cancelled by user")
                    
                    self._log(f"\n{'='*40}")
                    self._log(f"📀 Job {idx}/{total_songs}: {song['song_title'][:40]}")
                    
                    # Process this song
                    self._process_single_song(
                        job_number=idx,
                        song_title=song['song_title'],
                        youtube_url=song['youtube_url'],
                        start_time=song['start_time'],
                        end_time=song['end_time'],
                        template=template,
                        output_dir=output_dir
                    )
                    
                    # Mark as used
                    picker.mark_song_used(song['song_title'])
                    
                    # Update progress
                    progress = (idx / total_songs) * 100
                    self.root.after(0, lambda p=progress: self.progress_var.set(p))
                
                # Done
                self._log(f"\n{'='*40}")
                self._log(f"🎉 SUCCESS! {total_songs} job(s) created!")
                self._log(f"📂 {output_dir}")
                self._log("")
                self._log("Next: Go to JSX Injection tab")
                
            else:
                # MANUAL MODE - single song, possibly duplicated
                song_title = self.title_entry.get().strip()
                youtube_url = self.url_entry.get().strip()
                start_time = self.start_entry.get().strip()
                end_time = self.end_entry.get().strip()
                
                self._log(f"Starting {num_jobs} job(s): {song_title}")
                self._log(f"Template: {template.upper()}")
                
                cached = self.song_db.get_song(song_title)
                if cached:
                    self._log("✓ Using cached data")
                    youtube_url = cached['youtube_url']
                    start_time = cached['start_time']
                    end_time = cached['end_time']
                
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Process first job
                job_data, job_folder = self._process_single_song(
                    job_number=1,
                    song_title=song_title,
                    youtube_url=youtube_url,
                    start_time=start_time,
                    end_time=end_time,
                    template=template,
                    output_dir=output_dir,
                    return_data=True
                )
                
                # Duplicate for remaining jobs (same song)
                if num_jobs > 1:
                    self._log(f"Creating {num_jobs - 1} duplicate job folders...")
                    image_path = job_folder / "cover.png"
                    
                    for i in range(2, num_jobs + 1):
                        dest = output_dir / f"job_{i:03}"
                        dest.mkdir(parents=True, exist_ok=True)
                        
                        # Copy common files
                        for file in ['audio_trimmed.wav', 'lyrics.txt', 'beats.json']:
                            src = job_folder / file
                            if src.exists():
                                shutil.copy(src, dest / file)
                        
                        # Copy template-specific data file
                        for data_file in ['mono_data.json', 'onyx_data.json']:
                            src = job_folder / data_file
                            if src.exists():
                                shutil.copy(src, dest / data_file)
                        
                        if image_path.exists():
                            shutil.copy(image_path, dest / "cover.png")
                        
                        jd = job_data.copy()
                        jd['job_id'] = i
                        jd['audio_trimmed'] = str(dest / "audio_trimmed.wav")
                        jd['cover_image'] = str(dest / "cover.png") if image_path.exists() else None
                        jd['lyrics_file'] = str(dest / "lyrics.txt")
                        
                        with open(dest / "job_data.json", 'w') as f:
                            json.dump(jd, f, indent=4)
                
                # Done
                self.progress_var.set(100)
                self._log("=" * 40)
                self._log(f"🎉 SUCCESS! {num_jobs} job(s) created!")
                self._log(f"📂 {output_dir}")
                self._log("")
                self._log("Next: Go to JSX Injection tab")
            
            # Update stats
            stats = self.song_db.get_stats()
            self.root.after(0, lambda: self.stats_label.config(
                text=f"📊 Database: {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics"
            ))
            
            # Refresh smart picker if it was used
            if self.use_smart_picker:
                self.root.after(0, self._refresh_smart_picker_stats)
            
            self.root.after(0, lambda: messagebox.showinfo(
                "Complete!",
                f"Created {num_jobs} job(s) for {template.upper()}!\n\n"
                "Go to the JSX Injection tab to inject into After Effects."
            ))
            
        except Exception as e:
            self._log(f"❌ Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self._lock_inputs(False))
            self.root.after(0, lambda: self.generate_btn.configure(state='normal'))
            self.root.after(0, lambda: self.cancel_btn.configure(state='disabled'))
            self.root.after(0, self._check_existing_jobs)
    
    def _build_markers_from_lyrics(self, lyrics_data):
        """Convert lyrics.txt format to markers format for Mono/Onyx.
        Uses real word-level timestamps from Whisper when available,
        otherwise falls back to estimated timing."""
        markers = []

        for i, seg in enumerate(lyrics_data):
            text = seg.get('lyric_current', '') or seg.get('text', '')
            if not text or not text.strip():
                continue

            clean_text = text.replace('\\r', ' ').replace('\r', ' ')
            clean_text = ' '.join(clean_text.split()).strip()

            time_val = float(seg.get('t', 0) or seg.get('time', 0))
            seg_end  = float(seg.get('end', time_val + 3))

            # Use real Whisper word timestamps if present
            raw_words = seg.get('words', [])
            if raw_words:
                words = [
                    {
                        "word":  w.get('word', '').strip(),
                        "start": float(w.get('start', time_val)),
                        "end":   float(w.get('end',   time_val)),
                    }
                    for w in raw_words if w.get('word', '').strip()
                ]
            else:
                # Fallback: spread words evenly across segment duration
                word_list = clean_text.split()
                duration  = max(seg_end - time_val, 0.25)
                per_word  = duration / max(len(word_list), 1)
                words = [
                    {
                        "word":  w,
                        "start": time_val + idx * per_word,
                        "end":   time_val + (idx + 1) * per_word,
                    }
                    for idx, w in enumerate(word_list)
                ]

            # end_time = start of next segment (or +3s for the last one)
            if i < len(lyrics_data) - 1:
                next_t = float(lyrics_data[i + 1].get('t', 0) or lyrics_data[i + 1].get('time', 0))
                end_time = next_t if next_t > time_val else seg_end
            else:
                end_time = seg_end

            markers.append({
                "time":     time_val,
                "text":     clean_text,
                "words":    words,
                "color":    "white" if len(markers) % 2 == 0 else "black",
                "end_time": end_time,
            })

        return markers
    
    def _process_single_song(self, job_number, song_title, youtube_url, start_time, end_time, 
                              template, output_dir, return_data=False):
        """Process a single song into a job folder"""
        job_folder = output_dir / f"job_{job_number:03}"
        job_folder.mkdir(parents=True, exist_ok=True)
        
        needs_image = template in ['aurora', 'onyx']
        
        # Check cache
        cached = self.song_db.get_song(song_title)
        if cached:
            self._log("  ✓ Using cached data")
            youtube_url = cached['youtube_url']
            start_time = cached['start_time']
            end_time = cached['end_time']
        
        # Download
        if self.cancel_requested: raise Exception("Cancelled")
        audio_path = job_folder / "audio_source.mp3"
        if not audio_path.exists():
            self._log("  Downloading audio...")
            download_audio(youtube_url, str(job_folder))
            self._log("  ✓ Audio downloaded")
        else:
            self._log("  ✓ Audio exists")
        
        # Trim
        if self.cancel_requested: raise Exception("Cancelled")
        trimmed_path = job_folder / "audio_trimmed.wav"
        if not trimmed_path.exists():
            self._log(f"  Trimming ({start_time} → {end_time})...")
            trim_audio(str(job_folder), start_time, end_time)
            self._log("  ✓ Audio trimmed")
        else:
            self._log("  ✓ Trimmed audio exists")
        
        # Beats
        if self.cancel_requested: raise Exception("Cancelled")
        beats_path = job_folder / "beats.json"
        if cached and cached.get('beats'):
            beats = cached['beats']
            with open(beats_path, 'w') as f:
                json.dump(beats, f, indent=4)
            self._log("  ✓ Using cached beats")
        elif not beats_path.exists():
            self._log("  Detecting beats...")
            beats = detect_beats(str(job_folder))
            with open(beats_path, 'w') as f:
                json.dump(beats, f, indent=4)
            self._log(f"  ✓ {len(beats)} beats detected")
        else:
            with open(beats_path, 'r') as f:
                beats = json.load(f)
            self._log("  ✓ Beats exist")
        
        # Transcribe
        if self.cancel_requested: raise Exception("Cancelled")
        lyrics_path = job_folder / "lyrics.txt"
        if cached and cached.get('transcribed_lyrics'):
            with open(lyrics_path, 'w', encoding='utf-8') as f:
                json.dump(cached['transcribed_lyrics'], f, indent=4, ensure_ascii=False)
            self._log(f"  ✓ Using cached lyrics ({len(cached['transcribed_lyrics'])} segments)")
        elif not lyrics_path.exists():
            self._log(f"  Transcribing ({Config.WHISPER_MODEL})...")
            transcribe_audio(str(job_folder), song_title)
            self._log("  ✓ Transcription complete")
        else:
            self._log("  ✓ Lyrics exist")
        
        # Image & Colors
        image_path = job_folder / "cover.png"
        colors = ['#ffffff', '#000000']
        
        if needs_image:
            if self.cancel_requested: raise Exception("Cancelled")
            if cached and cached.get('genius_image_url'):
                if not image_path.exists():
                    self._log("  Downloading cached image...")
                    download_image(str(job_folder), cached['genius_image_url'])
                self._log("  ✓ Using cached image")
            elif not image_path.exists():
                self._log("  Fetching cover image...")
                result = fetch_genius_image(song_title, str(job_folder))
                if result:
                    self._log("  ✓ Cover downloaded")
                else:
                    self._log("  ⚠ No cover found")
            else:
                self._log("  ✓ Cover exists")
            
            if self.cancel_requested: raise Exception("Cancelled")
            if image_path.exists():
                if cached and cached.get('colors'):
                    colors = cached['colors']
                    self._log(f"  ✓ Using cached colors")
                else:
                    self._log("  Extracting colors...")
                    colors = extract_colors(str(job_folder))
                    self._log(f"  ✓ Colors: {', '.join(colors)}")
        
        # Read lyrics data
        with open(lyrics_path, 'r', encoding='utf-8') as f:
            lyrics_data = json.load(f)
        
        # Save job data
        job_data = {
            "job_id": job_number,
            "song_title": song_title,
            "youtube_url": youtube_url,
            "start_time": start_time,
            "end_time": end_time,
            "template": template,
            "audio_trimmed": str(job_folder / "audio_trimmed.wav"),
            "cover_image": str(image_path) if image_path.exists() else None,
            "colors": colors,
            "lyrics_file": str(lyrics_path),
            "beats": beats,
            "created_at": datetime.now().isoformat()
        }
        
        with open(job_folder / "job_data.json", 'w') as f:
            json.dump(job_data, f, indent=4)
        
        # Create template-specific data files (mono_data.json / onyx_data.json)
        if template in ['mono', 'onyx']:
            markers = self._build_markers_from_lyrics(lyrics_data)
            template_data = {
                "markers": markers,
                "total_markers": len(markers)
            }
            if template == 'onyx':
                template_data["colors"] = colors
                template_data["cover_image"] = "cover.png" if image_path.exists() else None
            
            data_filename = f"{template}_data.json"
            with open(job_folder / data_filename, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=4, ensure_ascii=False)
            self._log(f"  ✓ Created {data_filename} ({len(markers)} markers)")
        
        # Save to database if not cached (only in manual mode to avoid duplicates)
        if not cached and not self.use_smart_picker:
            self._log("  Saving to database...")
            self.song_db.add_song(
                song_title=song_title,
                youtube_url=youtube_url,
                start_time=start_time,
                end_time=end_time,
                genius_image_url=None,
                transcribed_lyrics=lyrics_data,
                colors=colors,
                beats=beats
            )
        elif cached and not self.use_smart_picker:
            self.song_db.mark_song_used(song_title)
        
        self._log(f"  ✓ Job {job_number} complete")
        
        if return_data:
            return job_data, job_folder
        return None


def main():
    root = tk.Tk()
    app = AppollovaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
