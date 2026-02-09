# MV-AE-Project-Automation

Comprehensive automation pipeline to produce short, shareable music-video visuals using Python for data processing and Adobe After Effects for rendering. The project automates audio download and trimming, lyric transcription with timings, color extraction from cover art, beat detection, job packing into JSON, and fully automated AE project wiring and batch rendering.

For busy creators and small studios: generate 12 templated music-video jobs, import them into After Effects, and queue MP4 exports with minimal manual work.

**Scope:** audio processing, lyric timing, image color extraction, AE ExtendScript automation, TikTok/Spotify integration for song selection, and batch render queuing.

--

**Quick links**

- Project entry: [main.py](main.py)
- AE automation script: [scripts/JSX/MVAE-pt1.jsx](scripts/JSX/MVAE-pt1.jsx)
- Job templates: [jobs/](jobs/)
- AE templates: [template/](template/)

--

## Table of Contents

1. [Getting Started](#getting-started)
2. [How It Works (High-Level)](#how-it-works-high-level)
3. [After Effects Template Requirements](#after-effects-template-requirements)
4. [File Layout & Job Spec](#file-layout--job-spec)
5. [Install & Dependencies (Windows)](#install--dependencies-windows)
6. [Usage Examples](#usage-examples)
7. [Configuration & Tuning](#configuration--tuning)
8. [Troubleshooting & Tips](#troubleshooting--tips)
9. [Developer Notes & Contributing](#developer-notes--contributing)
10. [License](#license)


## Getting Started

1. Install dependencies (see the Installation section).
2. Run `python main.py` and follow the prompts to create job folders and `job_data.json` files.
3. Open the After Effects template in `template/` and run the JSX automation script: `File → Scripts → Run Script File... → scripts/JSX/MVAE-pt1.jsx` and choose the top-level `jobs/` folder.
4. Inspect the render queue in AE and render MP4 outputs.


## How It Works (High-Level)

- Python side (`main.py` + `scripts/`): downloads audio, trims, extracts beats, transcribes lyrics, downloads cover art, extracts colors, and writes `job_data.json` per job folder.
- Database tools (`database/`): optional automation to pick songs, track cooldowns, and enrich metadata via Spotify.
- After Effects side (`scripts/JSX/MVAE-pt1.jsx`): imports job assets, duplicates `MAIN` comp, wires layers and text, applies colors and beat-sync keyframes, and queues the final `OUTPUT N` compositions for rendering.


## After Effects Template Requirements

This project assumes a carefully prepared AE template. If your template doesn't match the checklist below, the JSX script will either skip jobs or print helpful log messages.

- Top-level project folders (exact names): `Foreground`, `Background`, `OUTPUT1` … `OUTPUT12`.
- A composition named `MAIN` that serves as the template to duplicate per job.
- Comps named `OUTPUT 1` … `OUTPUT 12`, `LYRIC FONT 1` … `LYRIC FONT 12`, `Assets 1` … `Assets 12`, and `BACKGROUND 1` … `BACKGROUND 12`.

Required layers/properties (exact names used by JSX):

- In each `LYRIC FONT N` comp:
  - Text layers: `LYRIC PREVIOUS`, `LYRIC CURRENT`, `LYRIC NEXT 1`, `LYRIC NEXT 2` (these layers receive arrays of lyrics via expressions).
  - An audio layer named `AUDIO` (or any AVLayer with audio; the script will rename the first audio-enabled AVLayer to `AUDIO` if needed).

- In each `Assets N` comp:
  - Topmost text layer for the song title (the script sets its `Source Text`).
  - One or more placeholder image layers that are clearly album-art targets (layer names or source names containing `cover`, `album`, or `art`). These will be retargeted to the footage item named `COVER`.

- In each `BACKGROUND N` comp:
  - A layer named `Gradient` with the `4-Color Gradient` effect (the script sets `Color 1–4`).

- In each `OUTPUT N` comp:
  - A light layer named `Spot Light 2` with an intensity property (the script adds beat-synced keyframes to this intensity).

Notes:

- Layer/effect/property names are case-sensitive in the JSX script. If you change names, update the JSX accordingly.
- The JSX script attempts safe fallbacks and emits `$.writeln(...)` log lines for diagnostic troubleshooting.


## File Layout & Job Spec

Repository layout (important files):

- `main.py` — interactive job generator and orchestrator.
- `requirements.txt` — Python deps.
- `scripts/` — audio/image/lyric processing and `JSX/` AE scripts.
- `database/` — optional song picker and TikTok DB.
- `jobs/job_XXX/` — per-job working folders with `job_data.json`.
- `template/` — After Effects project templates.

Job JSON (`job_data.json`) minimal example:

```json
{
  "job_id": 1,
  "audio_source": "jobs/job_001/audio_source.mp3",
  "audio_trimmed": "jobs/job_001/audio_trimmed.wav",
  "cover_image": "jobs/job_001/cover.png",
  "colors": ["#0f172a", "#ef4444"],
  "lyrics_file": "jobs/job_001/lyrics.txt",
  "beats": [0.5, 1.23, 1.92],
  "job_folder": "jobs/job_001",
  "song_title": "Artist - Song"
}
```

Lyric JSON (array of timed lines produced by `scripts/lyric_processing.py`):

```json
[
  {"t": 0.5, "lyric_current": "Never gonna give you up"},
  {"t": 3.2, "lyric_current": "Never gonna let you down"}
]
```


## Install & Dependencies (Windows)

1. Install Python 3.8+ and add it to PATH.
2. Install required pip packages:

```powershell
python -m pip install -r requirements.txt
```

3. Install ffmpeg and ensure `ffmpeg` is available on PATH.

Optional (for Spotify/DB features): configure `database/config.yaml` with API credentials.

Common packages used (check `requirements.txt` for exact pins): `yt-dlp`, `pydub`, `librosa`, `colorthief`, `Pillow`, `whisper` or `openai-whisper`, `spotipy`, `pyyaml`, `requests`.


## Usage Examples

Generate jobs interactively:

```powershell
python main.py
```

After creating jobs, open After Effects, load your AE template project, and run the JSX script:

1. File → Scripts → Run Script File...
2. Select `scripts/JSX/MVAE-pt1.jsx`
3. When prompted, select the root `jobs/` folder

The script duplicates `MAIN` into `MV_JOB_###`, relinks footage named `AUDIO` and `COVER`, pushes lyrics arrays into lyric layers, sets audio markers, applies colors, applies beat-sync keyframes, and queues `OUTPUT N` comps to the render queue.

Render queue output path: each job's MP4 is written to `<job root>/renders/` with a sanitized filename.


## Configuration & Tuning

- `scripts/config.py`: project-wide constants like `TOTAL_JOBS`.
- `database/config.yaml`: TikTok channels, cooldown days, Spotify credentials.
- `scripts/lyric_processing.py`: Whisper model selection and line-wrapping limits.

Performance tips:

- Use a smaller Whisper model for faster transcription if accuracy tradeoff is acceptable.
- Pre-generate audio trims and beats to avoid re-processing during AE import.


## Troubleshooting & Tips

- If JSX reports a missing comp or layer, open AE and verify exact names listed in the AE Template Requirements section.
- If audio durations appear wrong, confirm the AE project framerate matches the expected frameRate (the script uses comp.frameRate for frame timing).
- If `ffmpeg` commands fail, run `ffmpeg -version` to ensure PATH and permissions are correct.
- For slow transcription, consider running `scripts/lyric_processing.py` directly and checking the generated `lyrics.txt` per job.

Common quick fixes:

- Update `yt-dlp`: `python -m pip install -U yt-dlp`
- Reinstall or add `ffmpeg` to PATH.
- Re-run `main.py` with `--verbose` (if implemented) to see step-by-step processing.


## Developer Notes & Contributing

- The AE JSX script is located at [scripts/JSX/MVAE-pt1.jsx](scripts/JSX/MVAE-pt1.jsx). Modify it only if you change template names or want custom wiring.
- Keep Python modules small and testable; prefer unit-testing audio/image transforms.
- When changing layer or comp names in AE, mirror them in the JSX script to avoid breakage.

Contributions: open issues or pull requests describing the feature or bug. Include example job folders for reproducible tests.


## License

This repository does not include a license by default. Add a `LICENSE` file if you intend to open-source the project and specify terms.

--

If you'd like, I can:

- add an example `job_data.json` into `jobs/job_001` for a quick trial,
- or run a short checklist script to validate your AE template names against the JSX expectations.


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