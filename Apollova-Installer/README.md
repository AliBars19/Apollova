# Apollova - Lyric Video Job Generator

A GUI application for generating After Effects job folders for lyric videos.

## Features

- 🎬 **Template Selection**: Choose between Aurora (full visual), Mono (minimal), or Onyx (hybrid)
- 🗄️ **Database Caching**: Songs are cached for instant reuse
- 🎵 **YouTube Download**: Automatic audio download with OAuth support
- 📝 **Whisper Transcription**: AI-powered lyrics with word-level timing
- 🎨 **Color Extraction**: Automatic palette extraction from cover art
- 🥁 **Beat Detection**: Librosa-powered beat tracking

## Installation

### Prerequisites

1. **Python 3.10+** - [Download](https://python.org/downloads)
2. **FFmpeg** - Required for audio processing
   - Windows: `choco install ffmpeg` or [download manually](https://ffmpeg.org/download.html)
   - Add to PATH

### Setup

```bash
# Clone or extract the package
cd apollova_gui

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env and add your Genius API token

# Run the application
python apollova_gui.py
```

## Building Standalone Executable

```bash
# Install PyInstaller
pip install pyinstaller

# Run build script (Windows)
build.bat
```

The executable will be created in `dist/Apollova/Apollova.exe`

## Usage

1. **Launch the application**
2. **Select template** (Aurora, Mono, or Onyx)
3. **Enter song details**:
   - Song Title (format: "Artist - Song Name")
   - YouTube URL
   - Start/End timestamps (MM:SS)
4. **Click "Generate Jobs"**
5. **Wait for processing** (download, transcription, etc.)
6. **Open After Effects** and run the JSX automation script
7. **Select the jobs folder** when prompted
8. **Render!**

## File Structure

```
apollova_gui/
├── apollova_gui.py      # Main GUI application
├── scripts/
│   ├── audio_processing.py
│   ├── image_processing.py
│   ├── lyric_processing.py
│   ├── genius_processing.py
│   ├── song_database.py
│   └── config.py
├── database/
│   └── songs.db         # SQLite cache (auto-created)
├── jobs/                # Output folder (auto-created)
├── whisper_models/      # Cached Whisper models
├── requirements.txt
├── build.bat            # PyInstaller build script
├── .env.example
└── README.md
```

## Configuration

Edit `.env` file:

```env
# Genius API Token (for accurate lyrics)
GENIUS_API_TOKEN=your_token_here

# Whisper Model (tiny/base/small/medium/large-v3)
WHISPER_MODEL=small
```

## Database

Songs are automatically cached in `database/songs.db`:
- YouTube URL
- Timestamps
- Transcribed lyrics
- Beat data
- Color palette

Cached songs process instantly on reuse.

## Troubleshooting

### "FFmpeg not found"
Ensure FFmpeg is installed and in your PATH:
```bash
ffmpeg -version
```

### YouTube download fails
- The app uses OAuth authentication
- On first run, follow the browser prompt to authorize
- Token is cached for future use

### Whisper model download slow
- First run downloads the model (~500MB for "small")
- Models are cached in `whisper_models/`
- Use "tiny" or "base" for faster downloads (less accurate)

### Empty transcription
- Try a different Whisper model
- Ensure audio quality is good
- Check if audio is actually music (not silence)

## License

For use with Apollova templates only.

## Support

Contact: [your-email]
Website: https://apollova.co.uk
