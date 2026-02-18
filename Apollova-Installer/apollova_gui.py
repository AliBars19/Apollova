#!/usr/bin/env python3
"""
Apollova - Lyric Video Job Generator
GUI Application for creating After Effects job folders
"""

import os
import sys
import json
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import processing modules
from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio, detect_beats
from scripts.image_processing import download_image, extract_colors
from scripts.lyric_processing import transcribe_audio
from scripts.song_database import SongDatabase
from scripts.genius_processing import fetch_genius_image


class ScrollableFrame(ttk.Frame):
    """A scrollable frame container"""
    
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        
        # Create canvas and scrollbar
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        # Configure scrolling
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Bind canvas resize to update frame width
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        # Pack widgets
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel
        self.scrollable_frame.bind('<Enter>', self._bind_mousewheel)
        self.scrollable_frame.bind('<Leave>', self._unbind_mousewheel)
    
    def _on_canvas_configure(self, event):
        """Update the frame width when canvas is resized"""
        self.canvas.itemconfig(self.canvas_frame, width=event.width)
    
    def _bind_mousewheel(self, event):
        """Bind mousewheel when mouse enters"""
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _unbind_mousewheel(self, event):
        """Unbind mousewheel when mouse leaves"""
        self.canvas.unbind_all("<MouseWheel>")
    
    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class AppollovaApp:
    """Main GUI Application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Apollova - Lyric Video Generator")
        self.root.geometry("850x700")
        self.root.minsize(700, 500)  # Minimum window size
        self.root.resizable(True, True)
        
        # Set app icon (if exists)
        icon_path = SCRIPT_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        
        # Initialize database
        self.db_path = SCRIPT_DIR / "database" / "songs.db"
        self.song_db = SongDatabase(db_path=str(self.db_path))
        
        # Processing state
        self.is_processing = False
        self.cancel_requested = False
        self.current_jobs = []
        
        # Track all input widgets for locking
        self.input_widgets = []
        
        # Setup UI
        self._setup_styles()
        self._create_widgets()
        self._load_settings()
        
    def _setup_styles(self):
        """Configure ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Custom colors
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'))
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10), foreground='#666666')
        style.configure('Section.TLabelframe.Label', font=('Segoe UI', 10, 'bold'))
        style.configure('Generate.TButton', font=('Segoe UI', 11, 'bold'), padding=10)
        style.configure('Status.TLabel', font=('Segoe UI', 9))
        style.configure('Warning.TLabel', font=('Segoe UI', 9), foreground='#f59e0b')
        
    def _create_widgets(self):
        """Create all UI widgets"""
        
        # Create outer container
        outer_frame = ttk.Frame(self.root)
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # === HEADER (Fixed at top) ===
        header_frame = ttk.Frame(outer_frame, padding="20 15 20 10")
        header_frame.pack(fill=tk.X)
        
        ttk.Label(header_frame, text="🎬 Apollova", style='Title.TLabel').pack(side=tk.LEFT)
        ttk.Label(header_frame, text="Lyric Video Job Generator", 
                  style='Subtitle.TLabel').pack(side=tk.LEFT, padx=(10, 0), pady=(5, 0))
        
        # Database stats
        stats = self.song_db.get_stats()
        stats_text = f"📊 Database: {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics"
        self.stats_label = ttk.Label(header_frame, text=stats_text, style='Subtitle.TLabel')
        self.stats_label.pack(side=tk.RIGHT)
        
        # Separator
        ttk.Separator(outer_frame, orient='horizontal').pack(fill=tk.X, padx=20)
        
        # === SCROLLABLE CONTENT AREA ===
        self.scroll_frame = ScrollableFrame(outer_frame)
        self.scroll_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        content_frame = self.scroll_frame.scrollable_frame
        content_padding = ttk.Frame(content_frame, padding="0 0 20 0")
        content_padding.pack(fill=tk.BOTH, expand=True)
        
        # === TEMPLATE SELECTION ===
        template_frame = ttk.LabelFrame(content_padding, text="Template", style='Section.TLabelframe', padding="10")
        template_frame.pack(fill=tk.X, pady=(10, 15))
        
        self.template_var = tk.StringVar(value="aurora")
        
        templates = [
            ("Aurora", "aurora", "Full visual with gradients, spectrum, beat-sync"),
            ("Mono", "mono", "Minimal text-only, black/white alternating"),
            ("Onyx", "onyx", "Hybrid - word-by-word lyrics + spinning vinyl disc")
        ]
        
        for i, (name, value, desc) in enumerate(templates):
            frame = ttk.Frame(template_frame)
            frame.pack(fill=tk.X, pady=2)
            
            rb = ttk.Radiobutton(frame, text=name, variable=self.template_var, value=value)
            rb.pack(side=tk.LEFT)
            self.input_widgets.append(rb)
            ttk.Label(frame, text=f"  - {desc}", foreground='#666666').pack(side=tk.LEFT)
        
        # === SONG INPUT ===
        song_frame = ttk.LabelFrame(content_padding, text="Song Details", style='Section.TLabelframe', padding="10")
        song_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Song Title
        ttk.Label(song_frame, text="Song Title (Artist - Song):").pack(anchor=tk.W)
        self.title_entry = ttk.Entry(song_frame, width=60, font=('Segoe UI', 10))
        self.title_entry.pack(fill=tk.X, pady=(2, 10))
        self.title_entry.bind('<KeyRelease>', self._check_database)
        self.input_widgets.append(self.title_entry)
        
        # Database match indicator
        self.db_match_label = ttk.Label(song_frame, text="", foreground='#666666')
        self.db_match_label.pack(anchor=tk.W)
        
        # YouTube URL
        ttk.Label(song_frame, text="YouTube URL:").pack(anchor=tk.W, pady=(10, 0))
        self.url_entry = ttk.Entry(song_frame, width=60, font=('Segoe UI', 10))
        self.url_entry.pack(fill=tk.X, pady=(2, 10))
        self.input_widgets.append(self.url_entry)
        
        # Timestamps
        time_frame = ttk.Frame(song_frame)
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
        
        # === JOB SETTINGS ===
        settings_frame = ttk.LabelFrame(content_padding, text="Settings", style='Section.TLabelframe', padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 15))
        
        settings_row1 = ttk.Frame(settings_frame)
        settings_row1.pack(fill=tk.X, pady=(0, 10))
        
        # Number of jobs
        ttk.Label(settings_row1, text="Number of Jobs:").pack(side=tk.LEFT)
        self.jobs_var = tk.StringVar(value="12")
        self.jobs_combo = ttk.Combobox(settings_row1, textvariable=self.jobs_var, 
                                   values=["1", "3", "6", "12"], width=5, state='readonly')
        self.jobs_combo.pack(side=tk.LEFT, padx=(5, 20))
        self.input_widgets.append(self.jobs_combo)
        
        # Whisper model
        ttk.Label(settings_row1, text="Whisper Model:").pack(side=tk.LEFT)
        self.whisper_var = tk.StringVar(value=Config.WHISPER_MODEL)
        self.whisper_combo = ttk.Combobox(settings_row1, textvariable=self.whisper_var,
                                      values=["tiny", "base", "small", "medium", "large-v3"],
                                      width=10, state='readonly')
        self.whisper_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.input_widgets.append(self.whisper_combo)
        
        settings_row2 = ttk.Frame(settings_frame)
        settings_row2.pack(fill=tk.X)
        
        # Output directory
        ttk.Label(settings_row2, text="Output Directory:").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=str(SCRIPT_DIR / "jobs"))
        self.output_entry = ttk.Entry(settings_row2, textvariable=self.output_var, width=40)
        self.output_entry.pack(side=tk.LEFT, padx=(5, 5))
        self.input_widgets.append(self.output_entry)
        
        self.browse_btn = ttk.Button(settings_row2, text="Browse...", command=self._browse_output)
        self.browse_btn.pack(side=tk.LEFT)
        self.input_widgets.append(self.browse_btn)
        
        # Job folder warning
        self.job_warning_frame = ttk.Frame(settings_frame)
        self.job_warning_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.job_warning_label = ttk.Label(self.job_warning_frame, text="", style='Warning.TLabel')
        self.job_warning_label.pack(side=tk.LEFT)
        
        self.delete_jobs_btn = ttk.Button(self.job_warning_frame, text="Delete Existing Jobs", 
                                           command=self._delete_existing_jobs)
        self.delete_jobs_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.delete_jobs_btn.pack_forget()  # Hidden by default
        
        # Check for existing jobs on startup and when output changes
        self.output_var.trace_add('write', lambda *args: self._check_existing_jobs())
        self._check_existing_jobs()
        
        # === PROGRESS ===
        progress_frame = ttk.LabelFrame(content_padding, text="Progress", style='Section.TLabelframe', padding="10")
        progress_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                             maximum=100, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        # Status label
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.status_var, style='Status.TLabel').pack(anchor=tk.W)
        
        # Log text area (fixed height)
        log_frame = ttk.Frame(progress_frame)
        log_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.log_text = tk.Text(log_frame, height=8, font=('Consolas', 9), 
                                 bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
        self.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        # Separator before buttons
        ttk.Separator(outer_frame, orient='horizontal').pack(fill=tk.X, padx=20)
        
        # === BUTTONS (Fixed at bottom) ===
        button_frame = ttk.Frame(outer_frame, padding="20 15 20 15")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.generate_btn = ttk.Button(button_frame, text="🚀 Generate Jobs", 
                                        style='Generate.TButton', command=self._start_generation)
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.cancel_btn = ttk.Button(button_frame, text="Cancel", command=self._cancel_generation, state='disabled')
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.open_folder_btn = ttk.Button(button_frame, text="Open Jobs Folder", command=self._open_jobs_folder)
        self.open_folder_btn.pack(side=tk.LEFT)
        
        self.settings_btn = ttk.Button(button_frame, text="⚙ Settings", command=self._open_settings)
        self.settings_btn.pack(side=tk.RIGHT)
    
    def _check_existing_jobs(self):
        """Check if job folders already exist in output directory"""
        output_dir = Path(self.output_var.get())
        
        if not output_dir.exists():
            self.job_warning_label.config(text="")
            self.delete_jobs_btn.pack_forget()
            return
        
        # Look for job_XXX folders
        existing_jobs = list(output_dir.glob("job_*"))
        
        if existing_jobs:
            count = len(existing_jobs)
            self.job_warning_label.config(
                text=f"⚠️ {count} existing job folder(s) detected in output directory"
            )
            self.delete_jobs_btn.pack(side=tk.LEFT, padx=(10, 0))
        else:
            self.job_warning_label.config(text="")
            self.delete_jobs_btn.pack_forget()
    
    def _delete_existing_jobs(self):
        """Delete all existing job folders after confirmation"""
        if self.is_processing:
            messagebox.showwarning("Processing", "Cannot delete jobs while processing.")
            return
            
        output_dir = Path(self.output_var.get())
        existing_jobs = list(output_dir.glob("job_*"))
        
        if not existing_jobs:
            messagebox.showinfo("No Jobs", "No job folders found to delete.")
            return
        
        # Confirm deletion
        result = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete {len(existing_jobs)} job folder(s)?\n\n"
            f"This will permanently delete:\n"
            f"{chr(10).join(['  • ' + j.name for j in existing_jobs[:5]])}"
            f"{chr(10) + '  • ...' if len(existing_jobs) > 5 else ''}\n\n"
            "This action cannot be undone.",
            icon='warning'
        )
        
        if not result:
            return
        
        # Delete job folders
        deleted = 0
        errors = []
        
        for job_folder in existing_jobs:
            try:
                if job_folder.is_dir():
                    shutil.rmtree(job_folder)
                    deleted += 1
            except Exception as e:
                errors.append(f"{job_folder.name}: {e}")
        
        # Report results
        if errors:
            messagebox.showwarning(
                "Partial Deletion",
                f"Deleted {deleted} folder(s), but {len(errors)} failed:\n\n" +
                "\n".join(errors[:5])
            )
        else:
            messagebox.showinfo("Deleted", f"Successfully deleted {deleted} job folder(s).")
        
        # Refresh warning
        self._check_existing_jobs()
        
    def _load_settings(self):
        """Load saved settings from config file"""
        settings_path = SCRIPT_DIR / "gui_settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    self.output_var.set(settings.get('output_dir', str(SCRIPT_DIR / "jobs")))
                    self.whisper_var.set(settings.get('whisper_model', 'small'))
                    self.jobs_var.set(settings.get('num_jobs', '12'))
            except:
                pass
    
    def _save_settings(self):
        """Save current settings to config file"""
        settings_path = SCRIPT_DIR / "gui_settings.json"
        settings = {
            'output_dir': self.output_var.get(),
            'whisper_model': self.whisper_var.get(),
            'num_jobs': self.jobs_var.get()
        }
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=2)
    
    def _check_database(self, event=None):
        """Check if song title exists in database"""
        title = self.title_entry.get().strip()
        if len(title) < 3:
            self.db_match_label.config(text="")
            return
        
        cached = self.song_db.get_song(title)
        if cached:
            self.db_match_label.config(
                text=f"✓ Found in database! URL and timestamps will be loaded automatically.",
                foreground='#22c55e'
            )
            # Auto-fill fields
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, cached['youtube_url'])
            self.start_entry.delete(0, tk.END)
            self.start_entry.insert(0, cached['start_time'])
            self.end_entry.delete(0, tk.END)
            self.end_entry.insert(0, cached['end_time'])
        else:
            # Check for partial matches
            matches = self.song_db.search_songs(title)
            if matches:
                self.db_match_label.config(
                    text=f"Similar songs found: {', '.join([m[0][:30] for m in matches[:3]])}",
                    foreground='#f59e0b'
                )
            else:
                self.db_match_label.config(
                    text="New song - will be added to database after processing.",
                    foreground='#666666'
                )
    
    def _browse_output(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(initialdir=self.output_var.get())
        if directory:
            self.output_var.set(directory)
    
    def _open_jobs_folder(self):
        """Open the jobs folder in file explorer"""
        jobs_dir = Path(self.output_var.get())
        jobs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(jobs_dir))
    
    def _open_settings(self):
        """Open settings dialog"""
        if self.is_processing:
            messagebox.showwarning("Processing", "Cannot change settings while processing.")
            return
            
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("450x350")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        frame = ttk.Frame(settings_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="⚙ Settings", font=('Segoe UI', 14, 'bold')).pack(anchor=tk.W, pady=(0, 15))
        
        # Genius API Token
        ttk.Label(frame, text="Genius API Token:").pack(anchor=tk.W)
        genius_entry = ttk.Entry(frame, width=50)
        genius_entry.pack(fill=tk.X, pady=(2, 5))
        genius_entry.insert(0, Config.GENIUS_API_TOKEN or "")
        
        ttk.Label(frame, text="Get your token at: https://genius.com/api-clients",
                  foreground='#666666', font=('Segoe UI', 8)).pack(anchor=tk.W, pady=(0, 15))
        
        # FFmpeg info
        ttk.Label(frame, text="FFmpeg Status:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(10, 0))
        
        # Check FFmpeg
        try:
            import subprocess
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            ffmpeg_status = "✓ FFmpeg found" if result.returncode == 0 else "✗ FFmpeg not found"
            ffmpeg_color = '#22c55e' if result.returncode == 0 else '#ef4444'
        except:
            ffmpeg_status = "✗ FFmpeg not found in PATH"
            ffmpeg_color = '#ef4444'
        
        ttk.Label(frame, text=ffmpeg_status, foreground=ffmpeg_color).pack(anchor=tk.W)
        
        ttk.Label(frame, text="\nNote: Settings are saved to .env file",
                  foreground='#666666').pack(anchor=tk.W, pady=(20, 0))
        
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        def save_and_close():
            # Save to .env
            env_path = SCRIPT_DIR / ".env"
            with open(env_path, 'w') as f:
                f.write(f"GENIUS_API_TOKEN={genius_entry.get()}\n")
                f.write(f"WHISPER_MODEL={self.whisper_var.get()}\n")
            Config.GENIUS_API_TOKEN = genius_entry.get()
            settings_window.destroy()
            messagebox.showinfo("Settings", "Settings saved!")
        
        ttk.Button(btn_frame, text="Save", command=save_and_close).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Cancel", command=settings_window.destroy).pack(side=tk.LEFT, padx=(10, 0))
    
    def _log(self, message, level='info'):
        """Add message to log with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')
        
        # Update status
        self.status_var.set(message[:80])
    
    def _validate_inputs(self):
        """Validate all input fields"""
        errors = []
        
        if not self.title_entry.get().strip():
            errors.append("Song title is required")
        
        if not self.url_entry.get().strip():
            # Check if we have it cached
            cached = self.song_db.get_song(self.title_entry.get().strip())
            if not cached:
                errors.append("YouTube URL is required for new songs")
        
        # Validate timestamps
        start = self.start_entry.get().strip()
        end = self.end_entry.get().strip()
        
        try:
            start_parts = start.split(':')
            end_parts = end.split(':')
            if len(start_parts) != 2 or len(end_parts) != 2:
                raise ValueError()
            start_ms = int(start_parts[0]) * 60 + int(start_parts[1])
            end_ms = int(end_parts[0]) * 60 + int(end_parts[1])
            if start_ms >= end_ms:
                errors.append("End time must be after start time")
        except:
            errors.append("Invalid timestamp format (use MM:SS)")
        
        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors))
            return False
        return True
    
    def _lock_inputs(self, lock=True):
        """Lock or unlock all input widgets during processing"""
        state = 'disabled' if lock else 'normal'
        
        for widget in self.input_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state='disabled' if lock else 'readonly')
                else:
                    widget.configure(state=state)
            except:
                pass
        
        # Also lock settings and delete buttons
        self.settings_btn.configure(state=state)
        if hasattr(self, 'delete_jobs_btn'):
            self.delete_jobs_btn.configure(state=state)
    
    def _start_generation(self):
        """Start the job generation process"""
        if not self._validate_inputs():
            return
        
        # Check for existing jobs and offer to delete
        output_dir = Path(self.output_var.get())
        existing_jobs = list(output_dir.glob("job_*")) if output_dir.exists() else []
        
        if existing_jobs:
            result = messagebox.askyesnocancel(
                "Existing Jobs Detected",
                f"Found {len(existing_jobs)} existing job folder(s).\n\n"
                "• Yes = Delete existing jobs and continue\n"
                "• No = Keep existing jobs and continue (may cause conflicts)\n"
                "• Cancel = Abort generation",
                icon='warning'
            )
            
            if result is None:  # Cancel
                return
            elif result:  # Yes - delete
                for job_folder in existing_jobs:
                    try:
                        if job_folder.is_dir():
                            shutil.rmtree(job_folder)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete {job_folder.name}: {e}")
                        return
                self._check_existing_jobs()
        
        self._save_settings()
        
        self.is_processing = True
        self.cancel_requested = False
        
        # Lock all inputs
        self._lock_inputs(True)
        
        self.generate_btn.configure(state='disabled')
        self.cancel_btn.configure(state='normal')
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.progress_var.set(0)
        
        # Start processing in separate thread
        thread = threading.Thread(target=self._process_jobs, daemon=True)
        thread.start()
    
    def _cancel_generation(self):
        """Cancel the ongoing generation"""
        self.cancel_requested = True
        self._log("Cancellation requested...", 'warning')
    
    def _process_jobs(self):
        """Process all jobs (runs in separate thread)"""
        try:
            song_title = self.title_entry.get().strip()
            youtube_url = self.url_entry.get().strip()
            start_time = self.start_entry.get().strip()
            end_time = self.end_entry.get().strip()
            num_jobs = int(self.jobs_var.get())
            template = self.template_var.get()
            output_dir = Path(self.output_var.get())
            
            # Update Whisper model
            Config.WHISPER_MODEL = self.whisper_var.get()
            
            self._log(f"Starting {num_jobs} job(s) for: {song_title}")
            self._log(f"Template: {template.upper()}")
            
            # Check database cache
            cached = self.song_db.get_song(song_title)
            if cached:
                self._log("✓ Using cached data from database", 'success')
                youtube_url = cached['youtube_url']
                start_time = cached['start_time']
                end_time = cached['end_time']
            
            # Create base job folder
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Process single job (all jobs share the same source)
            job_folder = output_dir / "job_001"
            job_folder.mkdir(parents=True, exist_ok=True)
            
            # Determine steps based on template
            needs_image = template in ['aurora', 'onyx']
            total_steps = 6 if needs_image else 4
            current_step = 0
            
            def update_progress():
                nonlocal current_step
                current_step += 1
                progress = (current_step / total_steps) * 100
                self.root.after(0, lambda: self.progress_var.set(progress))
            
            # === STEP 1: Download Audio ===
            if self.cancel_requested:
                raise Exception("Cancelled by user")
            
            audio_path = job_folder / "audio_source.mp3"
            if not audio_path.exists():
                self._log("Downloading audio...")
                download_audio(youtube_url, str(job_folder))
                self._log("✓ Audio downloaded", 'success')
            else:
                self._log("✓ Audio already exists", 'success')
            update_progress()
            
            # === STEP 2: Trim Audio ===
            if self.cancel_requested:
                raise Exception("Cancelled by user")
            
            trimmed_path = job_folder / "audio_trimmed.wav"
            if not trimmed_path.exists():
                self._log(f"Trimming audio ({start_time} → {end_time})...")
                trim_audio(str(job_folder), start_time, end_time)
                self._log("✓ Audio trimmed", 'success')
            else:
                self._log("✓ Trimmed audio already exists", 'success')
            update_progress()
            
            # === STEP 3: Beat Detection ===
            if self.cancel_requested:
                raise Exception("Cancelled by user")
            
            beats_path = job_folder / "beats.json"
            if cached and cached.get('beats'):
                beats = cached['beats']
                with open(beats_path, 'w') as f:
                    json.dump(beats, f, indent=4)
                self._log("✓ Using cached beats", 'success')
            elif not beats_path.exists():
                self._log("Detecting beats...")
                beats = detect_beats(str(job_folder))
                with open(beats_path, 'w') as f:
                    json.dump(beats, f, indent=4)
                self._log(f"✓ Detected {len(beats)} beats", 'success')
            else:
                with open(beats_path, 'r') as f:
                    beats = json.load(f)
                self._log("✓ Beats already detected", 'success')
            update_progress()
            
            # === STEP 4: Transcription ===
            if self.cancel_requested:
                raise Exception("Cancelled by user")
            
            lyrics_path = job_folder / "lyrics.txt"
            if cached and cached.get('transcribed_lyrics'):
                with open(lyrics_path, 'w', encoding='utf-8') as f:
                    json.dump(cached['transcribed_lyrics'], f, indent=4, ensure_ascii=False)
                self._log(f"✓ Using cached lyrics ({len(cached['transcribed_lyrics'])} segments)", 'success')
            elif not lyrics_path.exists():
                self._log(f"Transcribing with Whisper ({Config.WHISPER_MODEL})...")
                transcribe_audio(str(job_folder), song_title)
                self._log("✓ Transcription complete", 'success')
            else:
                self._log("✓ Lyrics already transcribed", 'success')
            update_progress()
            
            # === STEP 5: Image (Aurora/Onyx only) ===
            image_path = job_folder / "cover.png"
            colors = ['#ffffff', '#000000']  # Default for Mono
            
            if needs_image:
                if self.cancel_requested:
                    raise Exception("Cancelled by user")
                
                if cached and cached.get('genius_image_url'):
                    if not image_path.exists():
                        self._log("Downloading cached image...")
                        download_image(str(job_folder), cached['genius_image_url'])
                    self._log("✓ Using cached image", 'success')
                elif not image_path.exists():
                    self._log("Fetching cover image from Genius...")
                    result = fetch_genius_image(song_title, str(job_folder))
                    if result:
                        self._log("✓ Cover image downloaded", 'success')
                    else:
                        self._log("⚠ Could not fetch image automatically", 'warning')
                else:
                    self._log("✓ Cover image already exists", 'success')
                update_progress()
                
                # === STEP 6: Color Extraction ===
                if self.cancel_requested:
                    raise Exception("Cancelled by user")
                
                if image_path.exists():
                    if cached and cached.get('colors'):
                        colors = cached['colors']
                        self._log(f"✓ Using cached colors: {', '.join(colors)}", 'success')
                    else:
                        self._log("Extracting colors...")
                        colors = extract_colors(str(job_folder))
                        self._log(f"✓ Extracted colors: {', '.join(colors)}", 'success')
                update_progress()
            else:
                self._log("ℹ Mono template - skipping image/color steps", 'info')
            
            # === SAVE JOB DATA ===
            with open(lyrics_path, 'r', encoding='utf-8') as f:
                lyrics_data = json.load(f)
            
            job_data = {
                "job_id": 1,
                "song_title": song_title,
                "youtube_url": youtube_url,
                "start_time": start_time,
                "end_time": end_time,
                "template": template,
                "audio_source": str(job_folder / "audio_source.mp3"),
                "audio_trimmed": str(job_folder / "audio_trimmed.wav"),
                "cover_image": str(image_path) if image_path.exists() else None,
                "colors": colors,
                "lyrics_file": str(lyrics_path),
                "beats": beats,
                "job_folder": str(job_folder),
                "created_at": datetime.now().isoformat()
            }
            
            with open(job_folder / "job_data.json", 'w') as f:
                json.dump(job_data, f, indent=4)
            
            # === DUPLICATE FOR REMAINING JOBS ===
            if num_jobs > 1:
                self._log(f"Creating {num_jobs - 1} additional job folders...")
                for i in range(2, num_jobs + 1):
                    dest_folder = output_dir / f"job_{i:03}"
                    dest_folder.mkdir(parents=True, exist_ok=True)
                    
                    for file in ['audio_trimmed.wav', 'lyrics.txt', 'beats.json']:
                        src = job_folder / file
                        if src.exists():
                            shutil.copy(src, dest_folder / file)
                    
                    if image_path.exists():
                        shutil.copy(image_path, dest_folder / "cover.png")
                    
                    job_data_copy = job_data.copy()
                    job_data_copy['job_id'] = i
                    job_data_copy['job_folder'] = str(dest_folder)
                    job_data_copy['audio_trimmed'] = str(dest_folder / "audio_trimmed.wav")
                    job_data_copy['cover_image'] = str(dest_folder / "cover.png") if image_path.exists() else None
                    job_data_copy['lyrics_file'] = str(dest_folder / "lyrics.txt")
                    
                    with open(dest_folder / "job_data.json", 'w') as f:
                        json.dump(job_data_copy, f, indent=4)
                
                self._log(f"✓ Created {num_jobs} job folders", 'success')
            
            # === SAVE TO DATABASE ===
            if not cached:
                self._log("Saving to database...")
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
                self._log("✓ Song saved to database for future use", 'success')
            else:
                self.song_db.mark_song_used(song_title)
            
            # === DONE ===
            self.progress_var.set(100)
            self._log("=" * 50)
            self._log(f"🎉 SUCCESS! {num_jobs} job(s) created!", 'success')
            self._log(f"📂 Output: {output_dir}")
            self._log("")
            self._log("Next steps:")
            self._log(f"1. Open After Effects")
            self._log(f"2. Open the {template.upper()} template .aep file")
            self._log("3. File → Scripts → Run Script File...")
            self._log("4. Select the JSX automation script")
            self._log("5. Choose the jobs folder when prompted")
            
            # Update stats
            stats = self.song_db.get_stats()
            self.root.after(0, lambda: self.stats_label.config(
                text=f"📊 Database: {stats['total_songs']} songs | {stats['cached_lyrics']} with lyrics"
            ))
            
            self.root.after(0, self._check_existing_jobs)
            
            self.root.after(0, lambda: messagebox.showinfo(
                "Complete!",
                f"Successfully created {num_jobs} job(s)!\n\n"
                f"Template: {template.upper()}\n"
                f"Output: {output_dir}\n\n"
                "Open After Effects and run the JSX script to continue."
            ))
            
        except Exception as e:
            self._log(f"❌ Error: {e}", 'error')
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self._lock_inputs(False))
            self.root.after(0, lambda: self.generate_btn.configure(state='normal'))
            self.root.after(0, lambda: self.cancel_btn.configure(state='disabled'))
            self.root.after(0, self._check_existing_jobs)


def main():
    """Main entry point"""
    root = tk.Tk()
    app = AppollovaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
