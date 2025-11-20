# MV-AE-Project-Automation

A fully automated pipeline for creating professional 3D music video visuals ready for social media distribution. This project orchestrates audio extraction, image processing, lyrics transcription, and Adobe After Effects rendering into a seamless batch workflow.

##  Overview

MV-AE-Project-Automation is a two-phase system:

1. **Python Backend** (`main.py`) – Processes audio, images, and metadata
2. **After Effects Automation** (`MVAE-pt1.jsx`) – Renders final videos

Simply provide a song URL, cover image URL, timestamps, and song title, and the system handles the rest automatically.

##  Features

- **Audio Processing**
  - Downloads audio from YouTube/streaming links using `yt-dlp`
  - Trims audio to specified timestamps
  - Exports as WAV format for After Effects compatibility

- **Image Processing**
  - Downloads cover images from URLs
  - Extracts 4 dominant colors using ColorThief
  - Outputs colors in hex format for AE color grading

- **Lyrics Transcription**
  - Automatic speech-to-text using OpenAI Whisper
  - Word-level timing synchronization
  - Smart line wrapping (25-character limit per line)
  - Outputs JSON with precise lyric timing data

# MV-AE-Project-Automation

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A fully automated pipeline for creating 3D music-video visuals ready for social media. The project automates audio extraction, trimming, lyric transcription, color extraction from album art, and batch rendering via Adobe After Effects.

## Quick Snapshot

- Language: Python 3
- AE Scripting: Adobe After Effects ExtendScript (JSX)
- Jobs: Batch-style `jobs/job_001` → `jobs/job_012` by default

## Table of Contents

1. Overview
2. Features
3. Quick Start (Windows)
4. After Effects Setup Checklist
5. File Layout
6. Dependencies & Installation
7. Usage Examples
8. Troubleshooting
9. Configuration
10. Contributing & License

## 1 — Overview

The pipeline has two parts:

- `main.py` — Python command-line helper that downloads and trims audio, downloads cover art, extracts dominant colors, transcribes lyrics using OpenAI Whisper, and writes `job_data.json` files into `jobs/job_###` folders.
- `scripts/automateMV_batch.jsx` — After Effects script that imports job assets, wires them into templated comps, applies colors, populates lyrics, and queues renders.

## 2 — Features

- Audio download via `yt-dlp` and extraction to MP3/WAV
- Trim audio to timestamp ranges, export `audio_trimmed.wav`
- Cover image download and dominant color extraction (4 colors)
- Lyric transcription with Whisper and timestamped output
- AE JSX integration to auto-wire comps and push to render queue
- Job progress checking and resume-friendly behavior

## 3 — Quick Start (Windows)

Prerequisites

- Python 3.8 or later
- Adobe After Effects (with scripting enabled)
- ffmpeg (must be on PATH)

Install (Python deps):

```powershell
python -m pip install -r requirements.txt
```

Install `ffmpeg` on Windows (recommended):

1. Download a build from https://www.gyan.dev/ffmpeg/builds/ or https://ffmpeg.org/download.html
2. Unzip and copy the `bin\ffmpeg.exe` to a folder on your PATH or add the folder to PATH.
3. Verify:
```powershell
ffmpeg -version
```

Run the job generator:

```powershell
python main.py
```

Follow prompts for each job: audio URL, start/end timestamps (MM:SS), image URL, and song title.

After running `main.py`, each job folder will contain:

- `audio_source.mp3`
- `audio_trimmed.wav`
- `cover.png`
- `lyrics.txt` (JSON structured)
- `job_data.json`

## 4 — After Effects Setup Checklist

Before running the JSX script in AE, ensure your AE project (template) includes the following items and naming conventions:

- Folders: `Foreground`, `Background`, `OUTPUT1`..`OUTPUT12`
- Comps: `MAIN`, `OUTPUT 1`..`OUTPUT 12`, `LYRIC FONT 1`..`LYRIC FONT 12`, `Assets 1`..`Assets 12`, `BACKGROUND 1`..`BACKGROUND 12`
- Layers:
  - `BG GRADIENT` layer inside `BACKGROUND N` comps, with a 4-Color Gradient effect
  - Text layers named `LYRIC CURRENT`, `LYRIC PREVIOUS`, `LYRIC NEXT 1`, `LYRIC NEXT 2` inside `LYRIC FONT N` comps
  - An audio layer named `AUDIO` (or an AVLayer with audio enabled)

How to run the AE script:

1. Open your AE template project
2. File → Scripts → Run Script File... → select `scripts/automateMV_batch.jsx`
3. Pick the `jobs` folder when prompted
4. Verify imports and queued renders in AE's Render Queue

## 5 — File Layout

```
MV-AE-Project-Automation/
├─ main.py
├─ requirements.txt
├─ README.md
├─ scripts/
│  └─ automateMV_batch.jsx
├─ template/
│  └─ 3D Apple Music.aep
├─ jobs/
│  ├─ job_001/
│  │  ├─ audio_source.mp3
+│  │  ├─ audio_trimmed.wav
+│  │  ├─ cover.png
+│  │  ├─ lyrics.txt
+│  │  └─ job_data.json
│  └─ ...
└─ renders/
   └─ job_001.mp4
```

## 6 — Dependencies & Installation

Primary Python packages (listed in `requirements.txt`):

- `yt-dlp` — download audio
- `ffmpeg` — external binary for conversions
- `pydub` — audio trimming
- `requests`, `Pillow` — image downloading & handling
- `colorthief` — dominant color extraction
- `openai-whisper` (whisper) — transcription
- `matplotlib` — optional color visualization

Install all Python deps:

```powershell
python -m pip install -r requirements.txt
```

Notes:

- Whisper models can be large; choose `small` or `base` for faster processing, or `medium`/`large` for better accuracy.
- `ffmpeg` must be installed separately — see section 3.

## 7 — Usage Examples

Example run (single session):

```powershell
python main.py
# Follow prompts for jobs 1..12
```

Example `job_data.json` snippet:

```json
{
  "job_id": 1,
  "audio_source": "jobs/job_001/audio_source.mp3",
  "audio_trimmed": "jobs/job_001/audio_trimmed.wav",
  "cover_image": "jobs/job_001/cover.png",
  "colors": ["#ff5733", "#33ff57", "#3357ff", "#f0ff33"],
  "lyrics_file": "jobs/job_001/lyrics.txt",
  "song_title": "Artist - Song"
}
```

After the jobs exist, run the AE JSX script to import, wire comps, and queue renders.

## 8 — Troubleshooting

- Audio download fails: ensure the URL is valid, `yt-dlp` is up-to-date, and `ffmpeg` is installed.
- Whisper errors: verify model availability and sufficient disk space.
- AE script alerts about missing comps/layers: open the template AE project and confirm naming exactly matches the checklist in section 4.
- Colors not applied: ensure `BG GRADIENT` layer has a 4-Color Gradient effect available in AE.

## 9 — Configuration

Change the number of jobs by editing `main.py`:

```python
def batch_generate_jobs():
    base_jobs = 12  # change to desired job count
```

You can also adapt `main.py` to accept a CLI argument (PR welcome).

## 10 — Contributing & License

Contributions welcome. Suggested workflow:

1. Fork the repo
2. Create a feature branch
3. Open a pull request with a clear description

License: MIT (copy or add an appropriate `LICENSE` file if you want a different license).

---

**Last Updated:** November 2025
renders/job_002.mp4
... (up to job_012.mp4)
```

Each video includes:
- Synced lyrics with precise timing
- Color-graded visuals based on album art
- Professional H.264 encoding for social media

##  License

This project is for personal use. Modify and distribute as needed.

##  Support

For issues or improvements, refer to the JSX script's debug output (run with AE Debugger open) or check Python error messages in the terminal.

---

**Last Updated:** November 2025