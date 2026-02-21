# 🎬 **APOLLOVA** — Professional Lyric Video Generator for TikTok

**Production-grade system for generating, processing, and uploading AI-powered lyric videos directly to the Apollova platform.**

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [System Architecture](#system-architecture)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Complete Setup Guide](#complete-setup-guide)
- [The Three Templates](#the-three-templates)
- [Core Components](#core-components)
- [Workflow](#workflow)
- [Configuration](#configuration)
- [Usage](#usage)
- [Development](#development)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## 🎯 Overview

**Apollova** is an end-to-end system for creating professional lyric videos optimized for TikTok. Given a YouTube URL, the system:

1. 📥 **Downloads** audio from YouTube
2. 🎚️ **Transcribes** lyrics using OpenAI Whisper
3. 🔍 **Aligns** lyrics to audio using intelligent matching
4. 🎨 **Generates** visual effects (Aurora, Mono, or Onyx templates)
5. 📤 **Uploads** to Apollova platform with auto-scheduling
6. 📊 **Tracks** video status and performance

Perfect for content creators, music channels, and DSPs who need batch lyric video generation at scale.

---

## ✨ Features

### 🎬 Video Generation
- **Three Professional Templates:**
  - **Aurora** — Full visual effects with gradients, spectrum visualization, beat-sync overlay
  - **Mono** — Minimal, high-contrast black/white alternating text design
  - **Onyx** — Hybrid approach with word-by-word lyrics + spinning vinyl disc

- **AI-Powered Transcription** using OpenAI Whisper
  - Multi-pass transcription for accuracy
  - Word-level timing precision
  - Support for ~100 languages
  - Configurable model sizes (tiny → large-v3)

- **Intelligent Lyric Alignment**
  - Fuzzy string matching with token sorting
  - Handles misspellings, abbreviations, spoken artifacts
  - Secondary: Genius.com API for fallback lyrics

- **Automatic Color Extraction**
  - Palette analysis from cover art
  - Context-aware color blending
  - Consistent branding across videos

- **Beat Detection**
  - Librosa-powered tempo & beat tracking (Aurora only)
  - Real-time visual synchronization

### 📂 Production Pipeline
- **Job-based Processing** — 12 independent render jobs per template
- **Batch Generation** — Process multiple songs simultaneously
- **TikTok Format Native** — Vertical 9:16 aspect ratio, optimized audio
- **Database Caching** — Instant reuse of processed songs

### 🚀 Deployment & Uploading
- **Real-Time Monitoring** via `render_watcher.py`
- **Auto-Upload** when After Effects render completes
- **Smart Scheduling** — 12 videos/day, 1-hour intervals
- **Crash Recovery** — SQLite state tracking
- **OAuth Support** — YouTube authentication for download reliability

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       USER INPUT LAYER                          │
│  ┌──────────────── Apollova GUI (installer) ──────────────┐   │
│  │  - Song selection (database search)                     │   │
│  │  - Template & settings selection                        │   │
│  │  - Job generation & batch processing                    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   PROCESSING LAYER (Scripts)                    │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│  │ Audio       │ │ Lyric        │ │ Image Processing     │   │
│  │ Processing  │ │ Processing   │ │ - Color extraction   │   │
│  │ - Download  │ │ - Transcribe │ │ - Palette generation │   │
│  │ - Trim      │ │ - Align      │ │ - Optimization       │   │
│  │ - Detect    │ │ - Genius API │ │                      │   │
│  │   beats     │ │ - Fallback   │ │                      │   │
│  └─────────────┘ └──────────────┘ └──────────────────────┘   │
│                                                                 │
│  ┌──────────────────────── Database ──────────────────────┐   │
│  │  SQLite: Songs, lyrics, colors, beats, timestamps      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  TEMPLATE RENDERING (After Effects)             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │  AURORA      │ │    MONO      │ │    ONYX      │           │
│  │  Full FX     │ │  Minimalist   │ │  Hybrid      │           │
│  │  Spectrum    │ │  Text-only    │ │  Word-by-wd  │           │
│  │  Gradients   │ │  B/W toggle   │ │  Vinyl disc  │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  RENDER MONITORING & UPLOAD                     │
│  ┌──────────────────── Render Watcher ────────────────────┐   │
│  │  - Watches: */jobs/renders/ folders                     │   │
│  │  - Detects completed .mp4 files                         │   │
│  │  - Uploads immediately                                  │   │
│  │  - Auto-schedules with 1hr intervals                    │   │
│  │  - Tracks state in SQLite (crash recovery)              │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   APOLLOVA CLOUD PLATFORM                       │
│  - Video storage & CDN                                          │
│  - Scheduling queue (12 videos/day/account)                     │
│  - TikTok analytics & posting                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
Apollova/
├── README.md (this file)
├── SECURITY_SCAN_SUMMARY.md          ← Security audit & checklist
├── SECURITY_AUDIT.md                 ← Detailed security findings
├── requirements.txt                  ← Python dependencies
├── .env.example                      ← Configuration template
├── .gitignore                        ← Git exclusion rules
│
├── Apollova-Installer/
│   ├── apollova_gui.py              ← Main GUI application
│   ├── gui_settings.json            ← User settings cache
│   ├── build.bat                    ← Build executable (Windows)
│   ├── requirements.txt             ← GUI dependencies
│   └── README.md                    ← Installer documentation
│
├── Apollova-Aurora/
│   ├── main.py                      ← Template execution
│   ├── apollova-aurora-injection.jsx ← After Effects script
│   ├── smart_picker.py              ← Effect selection
│   └── jobs/                        ← Processing workspace
│
├── Apollova-Mono/
│   ├── main.py                      ← Template execution
│   ├── apollova-mono-injection.jsx  ← After Effects script
│   ├── smart_picker.py              ← Effect selection
│   └── jobs/                        ← Processing workspace
│
├── Apollova-Onyx/
│   ├── main.py                      ← Template execution
│   ├── apollova-onyx-injection.jsx  ← After Effects script
│   ├── smart_picker.py              ← Effect selection
│   └── jobs/                        ← Processing workspace
│
├── scripts/
│   ├── config.py                    ← Shared configuration
│   ├── audio_processing.py          ← Download, trim, beat detect
│   ├── lyric_processing.py          ← Aurora-specific transcription
│   ├── lyric_processing_mono.py     ← Mono-specific transcription
│   ├── lyric_processing_onyx.py     ← Onyx-specific transcription
│   ├── lyric_alignment.py           ← Genius + fuzzy matching
│   ├── genius_processing.py         ← Genius.com API integration
│   ├── image_processing.py          ← Cover art color extraction
│   ├── db_manager.py                ← Database utilities
│   ├── song_database.py             ← SQLite ORM
│   ├── smart_picker.py              ← Random effect selection
│   └── __pycache__/                 ← Python cache (gitignored)
│
├── upload/
│   ├── render_watcher.py            ← Production upload service
│   ├── config.py                    ← Upload configuration
│   ├── notification.py              ← Desktop notifications
│   ├── upload_state.py              ← State management
│   ├── setup_task.ps1               ← Windows Task Scheduler setup
│   ├── start_watcher.vbs            ← VBS launcher
│   ├── test_render_watcher.py       ← Unit tests
│   ├── .env.example                 ← Upload config template
│   ├── logs/                        ← Activity logs (gitignored)
│   └── data/                        ← SQLite state (gitignored)
│
├── database/
│   ├── config.yaml                  ← Channel & Spotify settings
│   ├── song_database.py             ← Legacy utilities
│   ├── tiktok_sound_db.py           ← Sound DB utilities
│   ├── wipe_lyrics.py               ← Maintenance utility
│   ├── fix_image_urls.py            ← Genius URL updater
│   └── tiktok-sound.json            ← Sound metadata (gitignored)
│
├── AE-Templates/
│   ├── Apollova Aurora.aep          ← Aurora master template
│   ├── APOLLOVA HERO.aep            ← Hero template variant
│   ├── Apollova Mono.aep            ← Mono master template
│   ├── Apollova Onyx.aep            ← Onyx master template
│   ├── Adobe After Effects Auto-Save/ ← AE backups (gitignored)
│   └── */Logs/                      ← AE error logs (gitignored)
│
├── whisper_models/                  ← Cached models (gitignored)
│   └── large-v3.pt                  ← Downloaded on first run
│
└── [workspace]/
    └── jobs/
        ├── job_001/                 ← Individual job workspaces
        │   ├── input/
        │   ├── processing/
        │   └── renders/
        ├── job_002/
        └── ...
```

---

## 🚀 Quick Start

### Minimal Setup (5 minutes)

```bash
# 1. Install Python 3.10+
# 2. Install FFmpeg
# 3. Clone/download this repo

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create .env file
cp .env.example .env
# Edit .env with your API keys:
# - GENIUS_API_TOKEN (get from https://genius.com/api-clients)
# - GATE_PASSWORD (from Apollova admin panel)

# 6. Run the GUI
cd Apollova-Installer
python apollova_gui.py
```

**Then:**
- Select template (Aurora, Mono, or Onyx)
- Enter song title or YouTube URL
- Click "Generate Jobs"
- Wait for After Effects to render
- Render Watcher automatically uploads when done

---

## 📖 Complete Setup Guide

### Prerequisites

| Component | Version | Purpose | Get It |
|-----------|---------|---------|--------|
| Python | 3.10+ | Runtime | [python.org](https://python.org/downloads) |
| FFmpeg | Latest | Audio processing | `choco install ffmpeg` |
| Adobe After Effects | 2023+ | Template rendering | [adobe.com](https://adobe.com) |
| Git | Latest | Version control | [git-scm.com](https://git-scm.com) |

### Step 1: Clone & Install

```bash
# Clone repository
git clone https://github.com/macbookvisuals/Apollova.git
cd Apollova

# Create virtual environment (recommended)
python -m venv venv
source venv/Scripts/activate  # Windows
# or: source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit with your credentials
nano .env
# or use VSCode/editor of choice
```

**Required variables:**
```env
# Admin password for Apollova platform
GATE_PASSWORD=your_admin_password

# Genius.com API token (for lyrics fallback)
# Get from: https://genius.com/api-clients
GENIUS_API_TOKEN=your_genius_token

# Optional
WHISPER_MODEL=small              # tiny|base|small|medium|large-v3
TOTAL_JOBS=12                    # Concurrent AE scripts
MAX_CONCURRENT_DOWNLOADS=3       # YouTube parallel downloads
MAX_LINE_LENGTH=25               # Aurora: chars per line
```

### Step 3: Test Installation

```bash
# Verify Python packages
python -c "import torch; import librosa; import requests; print('✓ All imports OK')"

# Verify FFmpeg
ffmpeg -version | head -1

# Verify After Effects access (if installed)
# Skip if running on non-AE machine
```

### Step 4: Configure After Effects Templates (Optional)

If running on the same machine as After Effects:

```bash
# Open each AE template file:
# - AE-Templates/Apollova Aurora.aep
# - AE-Templates/Apollova Mono.aep
# - AE-Templates/Apollova Onyx.aep

# Verify the jsx scripts point to correct job folders:
# Edit > Preferences > Scripting & Expressions
# Ensure paths in apollova-*-injection.jsx match your setup
```

---

## 🎨 The Three Templates

### 🌅 **AURORA** — Full Visual Enhancement
**Best For:** Music channels, trending content, professional look

**Features:**
- Animated gradient backgrounds
- Real-time spectrum visualization
- Beat-sync'd pulsing effects
- Word-by-word highlight overlay
- Dynamic color palette from cover art
- 1080×1920 (9:16 for TikTok)

**Processing:**
```
Lyric Process: Multi-pass Whisper (4 aggressive passes)
               ↓ Genius API fallback
               ↓ Fuzzy string alignment
               ↓ Word-level timing

Output: Line-segmented lyrics with precise timing
```

**Typical Render Time:**
- 4-minute song: 45-90 seconds per job (12 jobs × ~15 min total)

---

### ⚫ **MONO** — Minimalist Text-Only
**Best For:** Indie artists, minimal aesthetic, text focus

**Features:**
- High-contrast black/white alternating
- Large, readable typography
- Word-by-word display
- Minimal motion/distraction
- TikTok-optimized text size
- 1080×1920

**Processing:**
```
Lyric Process: Multi-pass Whisper with word timestamps
               ↓ Genius.com integration
               ↓ Token-sort alignment
               ↓ Longer line segments (vs Aurora)

Output: Word-level markers for precise timing
```

**Advantages:**
- Fastest render times
- Maximum text readability
- Accessible (no complex animations)

---

### 🎛️ **ONYX** — Hybrid with Vinyl
**Best For:** Vinyl aesthetic, retro vibes, music-focused brands

**Features:**
- Word-by-word text animation (like Mono)
- Spinning vinyl disc overlay
- Album artwork display
- Retro color palette
- Music-focused visual metaphor
- 1080×1920

**Processing:**
```
Lyric Process: Same as Mono (word-level timestamps)
               ↓ Additional: Vinyl animation data
               ↓ Color processing for disc effect

Output: Word-level + vinyl rotation angles
```

**Unique Feature:**
- Automatic vinyl rotation synced to audio tempo

---

## ⚙️ Core Components

### 📥 **Audio Processing** (`scripts/audio_processing.py`)

Handles YouTube download, trimming, and beat detection.

```python
# Download from YouTube
audio_path = download_audio(
    url="https://youtube.com/watch?v=...",
    job_folder="./jobs/job_001",
    use_oauth=True  # OAuth for reliability
)

# Trim to specified range
trimmed = trim_audio(
    audio_path,
    start_time="0:15",  # MM:SS
    end_time="1:30"
)

# Detect beats (Aurora only)
beats = detect_beats(audio_path)
# Returns: [beat_time_1, beat_time_2, ...]
```

**Features:**
- pytubefix for OAuth-based YouTube downloads (more reliable)
- AAC→MP3 conversion via FFmpeg
- pydub for audio trimming
- librosa for beat detection
- Retry logic with exponential backoff

---

### 🎚️ **Lyric Processing** (`scripts/lyric_processing*.py`)

Three variants (Aurora, Mono, Onyx) with template-specific logic.

```python
# Core flow
1. DOWNLOAD AUDIO
2. TRANSCRIBE (Whisper)
3. ALIGN (Genius → Fuzzy Match)
4. FORMAT (Template-specific segments)

# Example: Aurora
lyrics = transcribe_with_whisper(
    audio_path,
    model="large-v3",
    attempt_genius=True
)
# Output: [{"line": "text", "start": 1.23, "end": 4.56}, ...]

# Example: Mono (word-level)
lyrics = transcribe_mono(audio_path)
# Output: [{"word": "text", "start": 1.23, "end": 1.45}, ...]
```

**Multi-Pass Transcription:**
- **Pass 1 (Strict):** Initial language detection
- **Pass 2 (Medium):** Relaxed prompting
- **Pass 3 (Loose):** Fallback with minimal constraints
- **Pass 4 (Nuclear):** Auto-detect language, no prompt

Each pass corrects previous errors and handles edge cases.

---

### 🎨 **Image Processing** (`scripts/image_processing.py`)

Extracts color palette from cover art for visual consistency.

```python
from colorthief import ColorThief

palette = extract_palette(image_path, num_colors=2)
# Returns: [(R,G,B), (R,G,B), ...] — dominant colors

# In Aurora:
# - Primary color for gradients
# - Secondary for accents

# In Onyx:
# - Vinyl disc coloring
# - Text highlights
```

---

### 🗄️ **Database** (`scripts/song_database.py`)

SQLite caching for instant reuse of processed songs.

```python
from scripts.song_database import SongDatabase

db = SongDatabase("./database/songs.db")

# Cache a song
db.add_song(
    title="Artist - Song Name",
    youtube_url="https://youtube.com/...",
    start_time="0:15",
    end_time="1:30",
    genius_image_url="https://...",
    transcribed_lyrics=lyrics_dict,
    colors=[(255,100,50), (100,50,255)]
)

# Retrieve cached
song = db.get_song("Artist - Song Name")
# → Instant reuse without re-processing!

# Search
matches = db.search_songs("partial title")
```

**Template-Specific Columns:**
| Column | Template | Purpose |
|--------|----------|---------|
| `transcribed_lyrics` | Aurora | Line segments |
| `mono_lyrics` | Mono | Word-level timing |
| `onyx_lyrics` | Onyx | Word-level + vinyl data |
| `colors` | All | Palette JSON |
| `beats` | Aurora | Beat timestamps |

---

### 📤 **Render Watcher** (`upload/render_watcher.py`)

Production service that monitors After Effects output and uploads automatically.

**What it does:**
1. Watches `*/jobs/renders/` folders
2. Detects when `.mp4` files appear (AE completed)
3. Immediately uploads to Apollova API
4. Auto-schedules in 1-hour intervals
5. Enforces 12 videos/day limit
6. Retries on failure (exponential backoff)
7. Tracks everything in SQLite

**Usage:**
```bash
# Watch mode (continuous, recommended)
python render_watcher.py

# One-time upload remaining videos
python render_watcher.py --upload-now

# Retry failed videos
python render_watcher.py --retry-failed

# Check status
python render_watcher.py --status

# Install as Windows Task (runs at login)
powershell -ExecutionPolicy ByPass -File setup_task.ps1
```

---

## 🔄 Workflow

### Typical User Journey

```
1. OPEN GUI
   └─ cd Apollova-Installer && python apollova_gui.py

2. SEARCH SONG
   ├─ Type "Artist - Song"
   └─ System checks local database
      ├─ FOUND → Load cached data, timestamps, lyrics
      └─ NOT FOUND → User enters YouTube URL

3. GENERATE JOBS
   ├─ Select template: Aurora / Mono / Onyx
   ├─ Verify timestamps: 0:15 – 3:45 (example)
   ├─ Click "Generate Jobs"
   └─ System creates: jobs/job_001..job_012

4. PROCESSING BEGINS (Parallel)
   ├─ Each job_XXX folder runs independently
   │  ├─ Download audio from YouTube
   │  ├─ Trim to specified range
   │  ├─ Transcribe with Whisper
   │  ├─ Align with Genius (fallback: fuzzy match)
   │  ├─ Extract colors from cover art
   │  └─ Cache to database for reuse
   └─ Total: 1-5 minutes (depending on song length & settings)

5. AFTER EFFECTS RENDERING
   ├─ GUI triggers: "Open in After Effects"
   ├─ AE loads: Apollova Aurora.aep (etc.)
   ├─ JSX injection script parses job data
   ├─ Template creates 12 video variations
   ├─ Each renders to: jobs/job_XXX/renders/video.mp4
   └─ Total: 5-15 minutes (12 parallel renders)

6. AUTO UPLOAD
   ├─ Render Watcher monitors renders/ folder
   ├─ When video appears, uploads immediately
   ├─ Auto-schedules on Apollova platform
   │  ├─ 12 videos/day limit
   │  ├─ 1-hour intervals
   │  └─ 11AM–11PM window
   └─ Desktop notification on success/failure

7. APOLLOVA PLATFORM
   ├─ Videos queued for posting
   ├─ TikTok posting in optimal slots
   ├─ Analytics tracking
   └─ Reuse suggestions for next batch
```

### Database Advantage

**First run:** 4-minute song takes 4-5 minutes to process  
**Reuse:** Same song processed again in 30 seconds (cache hit!)

---

## ⚙️ Configuration

### Environment Variables (`.env`)

```env
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CRITICAL (Required, keep SECRET)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GATE_PASSWORD=your_admin_password
# Your Apollova admin password for upload authentication

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API Credentials (Required for full functionality)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GENIUS_API_TOKEN=your_genius_api_token
# Get from: https://genius.com/api-clients
# Used as fallback if Whisper transcription is incomplete

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Processing Settings
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHISPER_MODEL=small
# Options: tiny (fastest, ~1s), base, small, medium, large-v3 (accurate, ~30s)
# Recommended: small (good balance)

WHISPER_CACHE_DIR=./whisper_models
# Where to store downloaded Whisper models (large files, ~3GB)

TOTAL_JOBS=12
# Number of parallel AE scripts (12 = most common)

MAX_CONCURRENT_DOWNLOADS=3
# YouTube downloads in parallel (higher = faster, more bandwidth)

MAX_LINE_LENGTH=25
# Aurora only: character limit before wrapping text

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Upload Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APOLLOVA_API_URL=https://macbookvisuals.com
# Apollova backend (change only if using custom instance)

APOLLOVA_ROOT=./
# Base directory (auto-detected; override if needed)
```

### GUI Settings (`Apollova-Installer/gui_settings.json`)

```json
{
  "output_dir": "C:\\path\\to\\jobs",
  "whisper_model": "small",
  "num_jobs": "12"
}
```

Automatically saved when you change settings in the GUI.

---

## 💻 Usage

### Option 1: GUI Application (Recommended for Users)

```bash
cd Apollova-Installer
python apollova_gui.py
```

**Features:**
- Database search with fuzzy matching
- Visual song info (cover art, dimensions)
- Batch timestamp setup
- Progress tracking
- One-click After Effects integration

---

### Option 2: Command Line (For Automation/Scripting)

```bash
# Process a single song
python scripts/audio_processing.py --url "https://youtube.com/..." \
                                   --output ./jobs/job_001 \
                                   --start 0:15 --end 3:45

# Transcribe
python scripts/lyric_processing.py --audio ./jobs/job_001/audio.wav \
                                   --output ./jobs/job_001/lyrics.json

# Manual upload
python upload/render_watcher.py --upload-now

# Check status
python upload/render_watcher.py --status
```

---

### Option 3: After Effects Integration

Inside After Effects:

```
File > Scripts > Startup Scripts
→ Copy apollova-aurora-injection.jsx to Scripts folder
→ Restart After Effects

Now renders will auto-export to: jobs/job_XXX/renders/video.mp4
```

---

## 🛠️ Development

### Project Dependencies

**Core:**
- `pytubefix` — YouTube download (OAuth-enabled)
- `pydub` — Audio processing
- `librosa` — Beat detection
- `stable-whisper` — Speech-to-text
- `requests` — HTTP API calls
- `watchdog` — File system monitoring

**Data:**
- `sqlite3` — Local caching
- `pillow` — Image processing
- `colorthief` — Color palette extraction

**Utilities:**
- `beautifulsoup4` — Web scraping (Genius.com)
- `rapidfuzz` — Fuzzy string matching
- `python-dotenv` — Environment variable loading
- `rich` — Terminal output formatting
- `plyer` — Desktop notifications (cross-platform)
- `win10toast` — Windows 10 notifications

### Adding a New Template

1. **Create folder:**
   ```bash
   mkdir Apollova-YourTemplate
   cd Apollova-YourTemplate
   ```

2. **Create main.py:**
   ```python
   # Copy from Apollova-Aurora/main.py as template
   # Modify for your specific needs
   ```

3. **Create After Effects template:**
   ```
   YourTemplate.aep
   yourtemplate-injection.jsx  (copy from aurora variant)
   ```

4. **Add lyric processor:**
   ```bash
   # Copy scripts/lyric_processing.py
   # Rename: scripts/lyric_processing_yourtemplate.py
   # Customize line/word segmentation
   ```

5. **Register in config:**
   ```python
   # scripts/config.py or upload/config.py
   folder_account_map = {
       "Apollova-YourTemplate": "your_account_name",
   }
   ```

---

### Running Tests

```bash
# Unit tests for render watcher
python -m pytest upload/test_render_watcher.py -v

# Test database operations
python -m pytest scripts/ -k "database" -v

# Integration test
python -m unittest discover -s tests/ -p "*_test.py"
```

---

## 🔐 Security

> **⚠️ Important:** Review [SECURITY_SCAN_SUMMARY.md](SECURITY_SCAN_SUMMARY.md) before making the repo public.

### Secrets Management

**DO:**
- ✅ Store all credentials in `.env` file
- ✅ Add `.env` to `.gitignore` (already done)
- ✅ Use `.env.example` as template for users
- ✅ Rotate GATE_PASSWORD regularly
- ✅ Use environment variables in code: `os.getenv("KEY")`

**DON'T:**
- ❌ Hardcode passwords in source
- ❌ Commit `.env` files
- ❌ Share credentials in issues/PRs
- ❌ Log sensitive data

### Credential Rotation

If credentials are ever exposed:

```bash
# 1. Change password on platform
# (Apollova admin panel)

# 2. Update local .env
nano .env
# GATE_PASSWORD=new_password

# 3. Commit your code (not .env!)
git add -A
git commit -m "Update configuration"
```

---

## 🐛 Troubleshooting

### "ModuleNotFoundError: No module named 'torch'"

```bash
# Install PyTorch (required for Whisper)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### "FFmpeg not found"

```bash
# Windows
choco install ffmpeg
# or download: https://ffmpeg.org/download.html

# macOS
brew install ffmpeg

# Linux
sudo apt-get install ffmpeg
```

### YouTube Download Fails

```bash
# Try with OAuth disabled (if your network blocks it)
python audio_processing.py --no-oauth

# Or update pytubefix
pip install --upgrade pytubefix
```

### Whisper Transcription Too Slow

```env
# Use smaller model (faster but less accurate)
WHISPER_MODEL=base  # instead of "small"
```

### Genius API Fails

```python
# Check token
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('GENIUS_API_TOKEN'))"

# Get new token: https://genius.com/api-clients
# Should start with: "XXXXXX_XXXXXX_..."
```

### Render Watcher Not Uploading

```bash
# Check authentication
python upload/render_watcher.py --status

# Verify GATE_PASSWORD is correct
cat upload/.env | grep GATE_PASSWORD

# Check logs
python upload/render_watcher.py --log

# Retry failed videos
python upload/render_watcher.py --retry-failed
```

### After Effects Script Errors

1. Open AE console: `Window > Scripting Debugger`
2. Check `apollova-aurora-injection.jsx` error messages
3. Verify job folder exists: `jobs/job_001/processing/`
4. Check file permissions (AE needs write access)

---

## 📊 Performance Tips

### Speed Optimization

| Task | Time | Optimization |
|------|------|--------------|
| Download (4min song) | 30–60s | Higher bandwidth, parallel downloads |
| Whisper transcription | 10–30s | Use `small` model instead of `medium` |
| Alignment | 5–10s | Use fuzzy matching (default) |
| Color extraction | 1–2s | Cached after first run |
| AE rendering (12 jobs) | 5–15min | Parallel renders (already parallelized) |
| **Total first run** | **~20min** | Cached reuse: **1–2min** |

### Database Caching

```python
# First song: ~20 min processing
db.add_song("Artist - Song", youtube_url, ...)

# Same song later: 30 seconds!
song = db.get_song("Artist - Song")
# Returns all cached data (lyrics, colors, beats)
```

### CPU/GPU Usage

- **Whisper:** Uses GPU if available (NVIDIA/CUDA)
- **Your AE renders:** CPU-bound (utilizes all cores)
- **Recommendation:** 
  - 8+ CPU cores
  - 8GB+ RAM
  - Optional: NVIDIA GPU for 2–3× Whisper speed

---

## 🤝 Contributing

Contributions welcome! Please:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing`
3. **Test** thoroughly: `python -m pytest`
4. **Commit** with clear messages: `git commit -m "Add feature: X"`
5. **Push** and open a PR

**Code Standards:**
- Python 3.10+
- Type hints where practical
- Docstrings for public functions
- 4-space indentation
- No hardcoded secrets

---

## 📝 License

[Your License Here]

---

## 📞 Support & Resources

- **Docs:** [See individual README files]
  - [Apollova-Installer/README.md](Apollova-Installer/README.md) — GUI setup
  - [upload/README.md](upload/) — Render Watcher deployment
  
- **Security:** [SECURITY_SCAN_SUMMARY.md](SECURITY_SCAN_SUMMARY.md) — Credentials & safety

- **Config:** [.env.example](.env.example) — Environment variables

- **Issues:** Report bugs with system info + error logs

---

## 🎯 Roadmap

- [ ] Web API for remote job submission
- [ ] Mobile app for queue management
- [ ] Advanced analytics dashboard
- [ ] Multi-language UI
- [ ] Custom template builder
- [ ] Batch scheduling UI
- [ ] TikTok direct integration
- [ ] Instagram Reels support

---

**Made with ❤️ for content creators**

*Last updated: February 2026*
