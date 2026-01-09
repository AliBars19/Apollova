# MV-AE-Project-Automation

A fully automated pipeline for creating professional 3D music-video visuals ready for social media distribution. The project integrates audio processing, lyric transcription, color extraction, beat detection, and batch rendering via Adobe After Effects, with optional integration for TikTok sound databases and Spotify API for enhanced song selection.

## Quick Snapshot

- **Language:** Python 3
- **AE Scripting:** Adobe After Effects ExtendScript (JSX)
- **Batch Mode:** `jobs/job_001` → `jobs/job_012` by default
- **Output:** H.264 MP4 files with synced lyrics, beat-synced effects, and color-graded visuals
- **Integrations:** TikTok sound database, Spotify API, Genius lyrics and images

## Table of Contents

1. [Overview](#1--overview)
2. [Features](#2--features)
3. [Architecture](#3--architecture)
4. [Quick Start (Windows)](#4--quick-start-windows)
5. [After Effects Setup Checklist](#5--after-effects-setup-checklist)
6. [File Layout](#6--file-layout)
7. [Dependencies & Installation](#7--dependencies--installation)
8. [Usage Examples](#8--usage-examples)
9. [Database and Song Selection](#9--database-and-song-selection)
10. [Configuration](#10--configuration)
11. [Troubleshooting](#11--troubleshooting)
12. [Contributing & License](#12--contributing--license)

## 1 — Overview

The MV-AE-Project-Automation is a comprehensive tool for automating the creation of music videos. It combines Python scripting for data processing and Adobe After Effects for visual rendering.

### Main Components

- **`main.py`** — Python command-line tool that:
  - Downloads audio from YouTube or streaming URLs
  - Trims audio to specified timestamps
  - Downloads cover images (auto-fetch from Genius or manual)
  - Extracts dominant colors from cover art
  - Transcribes lyrics using OpenAI Whisper with word-level timing
  - Detects beats for synchronization
  - Generates `job_data.json` with all metadata

- **`scripts/JSX/MVAE-pt1.jsx`** — After Effects ExtendScript that:
  - Imports job assets into AE project
  - Wires audio, cover images, and lyrics into templated compositions
  - Applies extracted colors to gradient effects and backgrounds
  - Populates text layers with synchronized lyrics
  - Syncs spotlight effects with beat detection
  - Automatically queues all jobs for rendering

- **Database Module** (`database/`):
  - Manages a TikTok sound database for song selection
  - Implements cooldowns to avoid reusing recent tracks
  - Supports genre-based filtering
  - Integrates with Spotify API for additional metadata

## 2 — Features

✅ **Audio Processing**
- Download from YouTube/streaming links using `yt-dlp`
- Trim to custom timestamps (MM:SS format)
- Beat detection using Librosa
- Export as WAV for After Effects compatibility

✅ **Image Processing**
- Auto-fetch cover images from Genius API
- Manual URL input as fallback
- Extract 4 dominant colors using ColorThief
- Output colors in hex format for AE color grading

✅ **Lyric Transcription**
- Automatic speech-to-text using OpenAI Whisper
- Word-level timing synchronization
- Smart line wrapping (25-character limit per line)
- JSON output with precise timing data
- Fallback to Genius lyrics if available

✅ **After Effects Integration**
- Batch imports all job assets
- Auto-wires comps with audio, cover art, and lyrics
- Applies extracted colors to gradient effects and backgrounds
- Beat-sync spotlight intensity for dynamic visuals
- Generates render queue automatically
- Exports to H.264 MP4 format

✅ **Job Management**
- Resume interrupted jobs seamlessly
- Cache intermediate results
- JSON-based metadata for transparency and debugging
- Support for 12 jobs by default (configurable)

✅ **Database Integration**
- TikTok sound database with genre filtering
- Cooldown system (30 days default) to prevent reuse
- Spotify API integration for track metadata
- Automated song picking with `song_picker.py`

## 3 — Architecture

The project follows a modular architecture:

- **Core Processing** (`scripts/`): Audio, image, lyric, and genius processing modules
- **Database** (`database/`): Song selection and metadata management
- **Jobs** (`jobs/`): Per-job data storage and caching
- **Template** (`template/`): AE project templates
- **Renders** (`renders/`): Output directory for rendered videos

Workflow:
1. Song selection (manual or automated via database)
2. Audio download and trimming
3. Image fetching and color extraction
4. Lyric transcription and beat detection
5. Metadata compilation into `job_data.json`
6. AE script imports and wires assets
7. Rendering to MP4

## 4 — Quick Start (Windows)

### Prerequisites

- Python 3.8 or later
- Adobe After Effects (with scripting enabled)
- `ffmpeg` (must be on system PATH)
- Optional: Spotify API credentials for enhanced features

### Installation

**Step 1: Install Python Dependencies**

```powershell
python -m pip install -r requirements.txt
```

**Step 2: Install ffmpeg**

1. Download from [gyan.dev ffmpeg builds](https://www.gyan.dev/ffmpeg/builds/) (recommended for Windows)
2. Unzip and add to PATH:
   ```powershell
   $env:Path += ";C:\path\to\ffmpeg\bin"
   ```
3. Verify:
   ```powershell
   ffmpeg -version
   ```

**Step 3: Configure Database (Optional)**

Edit `database/config.yaml` with your Spotify credentials and TikTok channels.

**Step 4: Run Job Generator**

```powershell
python main.py
```

Follow prompts for each job (1–12):
- Audio URL
- Start/End times
- Song title (or auto-fetch)

**Step 5: Open AE and Run Script**

1. Open `template/3D Apple Music.aep`
2. `File` → `Scripts` → `Run Script File...` → `scripts/JSX/MVAE-pt1.jsx`
3. Select `jobs` folder when prompted
4. Review Render Queue and render

## 5 — After Effects Setup Checklist

Your AE template must include:

### Project Folder Structure

- `Foreground` (folder)
- `Background` (folder)
- `OUTPUT1` through `OUTPUT12` (folders)

### Required Compositions

- `MAIN` — Template duplicated per job
- `OUTPUT 1` through `OUTPUT 12` — Final comps
- `LYRIC FONT 1` through `LYRIC FONT 12` — Lyric displays
- `Assets 1` through `Assets 12` — Album art/metadata
- `BACKGROUND 1` through `BACKGROUND 12` — Gradients

### Required Layers & Effects

**In `BACKGROUND N`:**
- `COLOUR 1` and `COLOUR 2` solid layers
- `BG GRADIENT` with 4-Color Gradient effect

**In `LYRIC FONT N`:**
- Text layers: `LYRIC PREVIOUS`, `LYRIC CURRENT`, `LYRIC NEXT 1`, `LYRIC NEXT 2`
- Audio layer named `AUDIO`

**In `Assets N`:**
- Text layer for song title
- Layers for album art (retargeted to `COVER`)

**In `OUTPUT N`:**
- `Spot Light 2` with Intensity property for beat sync

## 6 — File Layout

```
MV-AE-Project-Automation/
├── main.py                          # Main job generator
├── requirements.txt                 # Python dependencies
├── spotify_api_data.txt             # Spotify API cache
├── README.md                        # This file
├── scripts/
│   ├── __init__.py
│   ├── audio_processing.py          # Audio download/trim/beat detection
│   ├── config.py                    # Configuration management
│   ├── genius_processing.py         # Genius API integration
│   ├── image_processing.py          # Image download/color extraction
│   ├── lyric_processing.py          # Whisper transcription
│   ├── __pycache__/
│   └── JSX/
│       ├── MVAE-pt1.jsx             # AE automation script
│       └── MVAE-pt2.jsx             # Additional AE utilities
├── database/
│   ├── config.yaml                  # DB config and API keys
│   ├── song_picker.py               # Automated song selection
│   ├── tiktok_sound_db.py           # TikTok DB management
│   └── tiktok-sound.json            # TikTok sound database
├── jobs/
│   ├── job_001/
│   │   ├── audio_source.mp3         # Downloaded audio
│   │   ├── audio_trimmed.wav        # Trimmed WAV
│   │   ├── cover.png                # Album art
│   │   ├── lyrics.txt               # Transcribed lyrics (JSON)
│   │   ├── job_data.json            # Metadata
│   │   ├── beats.json               # Beat timestamps
│   │   └── genius_lyrics.txt        # Genius reference
│   └── ... (job_002 through job_012)
├── renders/                         # Output MP4s
├── template/
│   ├── 3D Apple Music.aep           # AE template
│   └── ... (logs and backups)
└── whisper_models/                  # Cached Whisper models
    └── medium.pt
```

## 7 — Dependencies & Installation

### Python Packages

| Package | Purpose |
|---------|---------|
| `yt-dlp` | Audio download from streaming services |
| `ffmpeg` | Audio conversion (external) |
| `pydub` | Audio trimming |
| `requests` | HTTP requests for images |
| `Pillow` | Image processing |
| `colorthief` | Color extraction |
| `openai-whisper` | Speech-to-text |
| `librosa` | Beat detection |
| `rich` | Console output formatting |
| `pyyaml` | Config parsing |
| `spotipy` | Spotify API (optional) |

Install all:
```powershell
python -m pip install -r requirements.txt
```

### Whisper Models

- Auto-downloaded on first use
- Cached in `whisper_models/`
- `medium` model recommended for balance

## 8 — Usage Examples

### Manual Job Generation

```powershell
python main.py
```

Prompts for each job:
- Audio URL: https://youtube.com/watch?v=...
- Start time: 00:15
- End time: 01:45
- Song title: Artist - Song

### Automated Song Selection

```powershell
python database/song_picker.py
```

Select genre, gets random eligible track from TikTok DB.

### Example `job_data.json`

```json
{
  "job_id": 1,
  "audio_source": "jobs/job_001/audio_source.mp3",
  "audio_trimmed": "jobs/job_001/audio_trimmed.wav",
  "cover_image": "jobs/job_001/cover.png",
  "colors": ["#ff5733", "#33ff57", "#3357ff", "#f0ff33"],
  "lyrics_file": "jobs/job_001/lyrics.txt",
  "beats": [0.5, 1.2, 2.1, ...],
  "job_folder": "jobs/job_001",
  "song_title": "Artist - Song"
}
```

### Example `lyrics.txt`

```json
[
  {"t": 0.5, "lyric_current": "Never gonna give you up"},
  {"t": 3.2, "lyric_current": "Never gonna let you down"}
]
```

## 9 — Database and Song Selection

### TikTok Sound Database

- Stores tracks from specified TikTok channels
- Genre classification
- Cooldown tracking (30 days default)

### Spotify Integration

- Fetch track metadata
- Requires client ID/secret in `config.yaml`

### Using Song Picker

1. Run `python database/song_picker.py`
2. Select genre
3. Gets random unused track
4. Updates DB with usage timestamp

### Managing the Database

- Edit `database/config.yaml` for channels/genres
- `tiktok-sound.json` contains track data
- Manual editing supported

## 10 — Configuration

### Adjust Job Count

In `scripts/config.py`:
```python
TOTAL_JOBS = 12  # Change as needed
```

### Whisper Model

In `scripts/lyric_processing.py`:
```python
model = whisper.load_model("medium")  # tiny/base/small/medium/large
```

### Database Settings

In `database/config.yaml`:
- Add TikTok channels
- Set Spotify credentials
- Customize genres

### Lyric Wrapping

In `scripts/lyric_processing.py`:
```python
def chunk_text(s, limit=25):  # Adjust limit
```

## 11 — Troubleshooting

### Common Issues

**Audio Download Fails**
- Check URL validity
- Update yt-dlp: `pip install --upgrade yt-dlp`

**FFmpeg Errors**
- Ensure PATH includes ffmpeg
- Reinstall from gyan.dev

**Whisper Slow/Fails**
- Use smaller model
- Check disk space (>1GB for models)

**AE Script Errors**
- Verify template structure matches checklist
- Use Script Debugger for logs

**Colors/Lyrics Not Applying**
- Check layer names match exactly
- Ensure effects exist on layers

**Renders Missing**
- Verify `job_data.json` created
- Check file paths in JSON

### Logs and Debugging

- AE: Use Script Debugger
- Python: Rich console output
- Check `jobs/job_XXX/` for intermediate files

## 12 — Contributing & License

### Contributing

1. Fork repo
2. Create feature branch
3. Make changes
4. Test thoroughly
5. Open PR

**Areas for Improvement:**
- GUI for job config
- More audio sources
- Enhanced AE templates
- Performance optimizations

### License

MIT License — see LICENSE file.

---

**Last Updated:** January 2026  
**Maintainer:** [@AliBars19](https://github.com/AliBars19)

For support, open an issue or refer to troubleshooting.