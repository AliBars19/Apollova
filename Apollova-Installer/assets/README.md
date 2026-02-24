# Apollova Installer

## Quick Start

1. **Run Setup.exe** to install required Python packages
2. Choose options:
   - GPU Acceleration (optional, +~1.5 GB, requires NVIDIA GPU with CUDA)
   - Desktop shortcut (optional)
3. Click **Install** and wait for completion
4. Launch Apollova via **Apollova.bat** or the desktop shortcut

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10 or higher (Setup will offer to install if missing)
- Adobe After Effects (for rendering)
- NVIDIA GPU with CUDA support (optional, for faster transcription)

## Folder Structure

```
Apollova/
├── Setup.exe              # Run once to install dependencies
├── Apollova.bat           # Launch the app (created by setup)
├── Uninstall.bat          # Remove installed packages (created by setup)
├── assets/                # Application code
├── templates/             # Place your .aep template files here
├── database/              # Song database (auto-created)
├── whisper_models/        # Whisper models (auto-downloaded on first use)
├── Apollova-Aurora/jobs/  # Aurora job output
├── Apollova-Mono/jobs/    # Mono job output
└── Apollova-Onyx/jobs/    # Onyx job output
```

## Whisper Models

Downloaded automatically the first time you generate a job:
- tiny   ~75 MB   (fastest, less accurate)
- base   ~140 MB  (balanced)
- small  ~460 MB  (recommended)
- medium ~1.5 GB  (more accurate)
- large  ~3 GB    (most accurate)

## Uninstalling

Double-click **Uninstall.bat** to remove Python packages.
Then delete the Apollova folder manually.

## Troubleshooting

**App doesn't launch after setup**
- Make sure you're double-clicking Apollova.bat (not Setup.exe again)
- Ensure Python 3.10+ is installed and in PATH

**GPU acceleration not working**
- Ensure you have an NVIDIA GPU
- Update GPU drivers to latest
- Re-run Setup.exe with GPU option checked

**After Effects not found**
- Open the app, go to Settings tab, and set the path manually

**Genius lyrics not loading**
- Add your Genius API token in the Settings tab
