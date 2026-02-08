# Apollova Onyx 💿

**Hybrid lyric video template** - Word-by-word lyrics on the left, spinning disc with album art on the right.

Part of the **Apollova** product line:
- **Aurora** - Full visual effects (gradients, spectrum, beat-synced lighting)
- **Nova** - Minimal text-only (black/white flip, word-by-word)
- **Onyx** - Hybrid (word-by-word lyrics + spinning disc visual)

---

## Features

- 📝 **Word-by-word lyric reveal** (left side)
- 💿 **Spinning disc** with album art (right side)
- 🎨 **Color extraction** from album art
- 🔊 **Audio-synced** timing via Whisper AI
- 📚 **Genius lyrics** alignment
- 💾 **Database caching** for instant re-runs
- 🔄 **Smart song rotation** (fair usage tracking)

---

## Quick Start

### 1. Setup
```bash
pip install -r requirements.txt
```

### 2. Configure
Create `.env` file:
```
GENIUS_API_TOKEN=your_token_here
WHISPER_MODEL=small
TOTAL_JOBS=12
```

### 3. Run
```bash
# Manual mode (enter song details)
python main_onyx.py

# Auto mode (smart picker selects songs from database)
python run_smart_picker_onyx.py
```

### 4. After Effects
1. Open `template/Visuals-Onyx.aep`
2. File → Scripts → Run Script File...
3. Select `scripts/JSX/automateMV_onyx.jsx`
4. Choose the `jobs` folder
5. Render!

---

## Job Output Structure

Each job folder contains:
```
jobs/job_001/
├── audio_source.mp3      # Downloaded audio
├── audio_trimmed.wav     # Trimmed clip
├── cover.png             # Album art (for disc)
├── genius_lyrics.txt     # Reference lyrics
├── onyx_data.json        # Word-level markers + colors
└── job_data.json         # Job metadata
```

### onyx_data.json Format
```json
{
    "markers": [
        {
            "time": 0.0,
            "text": "I need you the most",
            "words": [
                {"word": "I", "start": 0.0, "end": 0.2},
                {"word": "need", "start": 0.2, "end": 0.48}
            ],
            "color": "white",
            "end_time": 1.3
        }
    ],
    "colors": ["#ff5733", "#33ff57"],
    "cover_image": "cover.png",
    "total_markers": 1
}
```

---

## Database

Onyx uses a **shared database** with Aurora and Nova:
```
../database/songs.db
```

Each template has its own lyrics column:
- `transcribed_lyrics` - Aurora (line-by-line)
- `nova_lyrics` - Nova (word-by-word)
- `onyx_lyrics` - Onyx (word-by-word + colors)

This prevents templates from overwriting each other's cached data.

---

## Requirements

- Python 3.11+
- FFmpeg
- After Effects 2024+

### Python Packages
- `pytubefix` - YouTube download
- `pydub` - Audio processing
- `stable-whisper` - Transcription
- `rapidfuzz` - Lyrics alignment
- `colorthief` - Color extraction
- `rich` - Console output
- `python-dotenv` - Config

---

## Project Status

- ✅ Python pipeline complete
- ✅ Database integration
- ✅ Word-level transcription
- ⏳ After Effects template design
- ⏳ JSX automation script

---

## License

MIT License - Use freely for personal and commercial projects.

---

*Apollova - Professional lyric videos, automated.*
