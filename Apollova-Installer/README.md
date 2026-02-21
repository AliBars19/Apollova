# Apollova - Lyric Video Generator

Professional GUI application for generating After Effects lyric video jobs.

## Features

- **Three Templates**: Aurora (full visual), Mono (minimal), Onyx (hybrid vinyl)
- **Database Caching**: Songs cached for instant reuse
- **Auto AE Detection**: Finds After Effects installation automatically
- **JSX Injection**: One-click injection into After Effects
- **Bundled Scripts**: JSX files embedded in executable

## Directory Structure

```
Apollova/
├── Apollova.exe                    # Main application
├── templates/
│   ├── Apollova-Aurora.aep         # Place your templates here
│   ├── Apollova-Mono.aep
│   └── Apollova-Onyx.aep
├── Apollova-Aurora/
│   └── jobs/                       # Aurora job output
├── Apollova-Mono/
│   └── jobs/                       # Mono job output
├── Apollova-Onyx/
│   └── jobs/                       # Onyx job output
├── database/
│   └── songs.db                    # Song cache
└── whisper_models/                 # AI model cache
```

## Installation

### Prerequisites
- Windows 10/11
- Adobe After Effects 2020+
- FFmpeg (in PATH)
- Python 3.10+ (for development only)

### Setup
1. Extract the Apollova folder
2. Place your .aep template files in `templates/`
3. Run `Apollova.exe`
4. Go to Settings tab and verify After Effects path
5. (Optional) Add Genius API token for accurate lyrics

## Usage

### Tab 1: Job Creation
1. Select template (Aurora/Mono/Onyx)
2. Enter song title (format: "Artist - Song")
3. Enter YouTube URL
4. Set start/end timestamps (MM:SS)
5. Choose number of jobs
6. Click "Generate Jobs"

### Tab 2: JSX Injection
1. Select the template to inject
2. Verify all status checks are green
3. Click "Launch After Effects & Inject"
4. Wait for AE to open and process
5. Review comps and add to render queue

### Tab 3: Settings
- After Effects path (auto-detected or manual)
- Genius API token (for lyrics)
- FFmpeg status

## Building from Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run directly
python apollova_gui.py

# Build executable
build.bat
```

## Troubleshooting

### "After Effects not found"
- Go to Settings tab
- Click "Auto-Detect" or "Browse" to locate AfterFX.exe
- Typical path: `C:\Program Files\Adobe\Adobe After Effects 2024\Support Files\AfterFX.exe`

### "No jobs found"
- Create jobs first in Job Creation tab
- Jobs are stored per-template (Aurora/Mono/Onyx have separate folders)

### "Template not found"
- Place your .aep files in the `templates/` folder
- File names must match exactly:
  - Apollova-Aurora.aep
  - Apollova-Mono.aep
  - Apollova-Onyx.aep

### JSX Injection Fails
1. JSX prompts to select jobs folder manually
2. If still failing, contact support at apollova.co.uk

## Support

Website: https://apollova.co.uk
