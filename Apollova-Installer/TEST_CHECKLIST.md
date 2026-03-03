# Apollova Overnight Test Checklist

Use this checklist while running Apollova overnight after the overhaul.
Check items off as you verify them. Any "ASSERT" or warning in logs = investigate.

---

## Phase 1: Setup.exe Tests

### 1.1 Fresh Install (GPU system)
- [ ] Run Setup.exe
- [ ] Verify "GPU detected: [GPU name]" appears in log
- [ ] Verify GPU torch installs WITHOUT `--no-deps` error
- [ ] Verify "CUDA available: True" + GPU name appears after install
- [ ] Verify all 14 packages pass verification (green checkmarks)
- [ ] Verify FFmpeg found
- [ ] Check `assets/logs/setup.log` — look for:
  - `NVIDIA GPU detected:` line
  - `CUDA:True:` line
  - No `FAILED` lines
  - `All packages verified` at end

### 1.2 Fresh Install (CPU-only system)
- [ ] Run Setup.exe without checking "GPU"
- [ ] Verify disk space check passes (needs 2 GB)
- [ ] Verify CPU torch installs correctly
- [ ] Verify all packages pass verification

### 1.3 Disk Space Check
- [ ] If < 4 GB free (GPU) or < 2 GB (CPU), verify fatal error appears
- [ ] Verify free space is logged: `Disk space: X.X GB free`

### 1.4 Concurrent Setup Protection
- [ ] Open Setup.exe twice simultaneously
- [ ] Verify "Another Setup appears to be running" warning on second instance
- [ ] Verify lockfile `assets/logs/setup.lock` is cleaned up after install completes

### 1.5 Pip Upgrade Verification
- [ ] Check setup.log for `pip --version` output after upgrade step
- [ ] Verify no "pip upgrade failed" warnings

---

## Phase 2: Apollova.exe Batch Job Tests

### 2.1 Aurora Batch (SmartPicker, 12 jobs)
- [ ] Select Aurora template, SmartPicker mode, 12 jobs
- [ ] Click Generate
- [ ] **Monitor log for:**
  - `[diag] Disk free: X.X GB` at start of each job
  - `Audio downloaded (X.X MB)` — file size shown
  - `Trimmed (X.X MB)` — file size shown
  - `Clip: X.Xs (expected Xs)` — duration sanity check
  - `Whisper device: [GPU/CPU]` — logged per job
  - `Transcribing... (Xm XXs elapsed)` — ticker every 15s during Whisper
  - `Transcribed (XXXs)` — total transcription time
  - `Job X complete (Xm XXs)` — per-job timing
- [ ] **Watch for ASSERT warnings:**
  - `ASSERT: lyrics.txt missing after transcription!`
  - `ASSERT: lyrics.txt suspiciously small`
  - `ASSERT: job_data missing fields`
  - `ASSERT: audio_trimmed path does not exist`
  - `LOW DISK: less than 1 GB free!`
- [ ] Verify batch summary at end shows:
  - Total time
  - Per job average
  - Succeeded/Failed counts
  - Device (GPU/CPU)
- [ ] Check `assets/logs/app.log` for detailed timing data

### 2.2 Mono Batch (SmartPicker, 12 jobs)
- [ ] Same as 2.1 but with Mono template
- [ ] Verify `mono_data.json` created in each job folder
- [ ] Watch for `ASSERT: mono_data.json missing` or `suspiciously small`

### 2.3 Onyx Batch (SmartPicker, 12 jobs)
- [ ] Same as 2.1 but with Onyx template
- [ ] Verify `onyx_data.json` created in each job folder

### 2.4 Resume Mode
- [ ] Start a 6-job batch, cancel after 3
- [ ] Check "Resume" and start again
- [ ] Verify it picks up from job 4 (not restart from 1)
- [ ] Verify completed jobs show "complete" status
- [ ] Verify failed jobs show "previously failed — skipping"

### 2.5 Error Handling
- [ ] Try a bad YouTube URL — verify actionable error message:
  `"Fix: Check the YouTube URL is correct and the video is public."`
- [ ] Disconnect internet mid-batch — verify graceful skip, not crash
- [ ] Try with no Genius API token — verify lyrics still work (Whisper fallback)

---

## Phase 3: JSX Injection Tests (After Effects)

### 3.1 Aurora JSX
- [ ] Open After Effects with Aurora template
- [ ] Run JSX injection on 12+ job batch
- [ ] **Verify NO alert() popups** during batch — all errors go to console
- [ ] Check `ExtendScript Toolkit` console for:
  - `$.writeln()` messages (not alert popups)
  - Job ID and song title logged for each job
  - `RENDER QUEUE CLEARED` at start
- [ ] Verify `error_log.txt` in job folder uses APPEND mode:
  - Run 2 batches — second batch errors should appear BELOW first
  - Each error should have a timestamp `[YYYY-MM-DD HH:MM:SS]`
- [ ] Check JSON validation: if a job_data.json is corrupt, verify:
  `"Skipping: missing job_id or song_title"` in console

### 3.2 Mono JSX
- [ ] Same batch test as 3.1 with Mono template
- [ ] Verify OUTPUT comp lookup uses `findOutputComp()` helper (no triple try/catch)
- [ ] Verify audio duration is cached from LYRIC FONT layer (not re-imported 12x)
  - Look for: `"Got audio duration from layer: Xs"` in console
  - Should NOT see: `"Importing audio file"` 12 times per job

### 3.3 Onyx JSX
- [ ] Same batch test as 3.1 with Onyx template
- [ ] Verify audio duration caching (same as Mono)
- [ ] Verify error log append mode

### 3.4 Missing Assets Test
- [ ] Delete a cover image from one job folder before JSX injection
- [ ] Verify Aurora JSX logs warning and continues (not crash/alert)
- [ ] Verify null guard: `if (!lyr.source) continue;` prevents crash

---

## Phase 4: Database Tests

### 4.1 Empty List Bug Fix
- [ ] Generate a job where colors = [] (e.g., no cover art found)
- [ ] Verify `update_colors_and_beats` stores `[]` (not NULL)
- [ ] Check songs.db: `SELECT colors FROM songs WHERE colors = '[]'`
- [ ] Generate a job where beats = [] (non-Aurora template)
- [ ] Verify beats stored as `[]` not NULL

---

## Phase 5: Log File Tests

### 5.1 RotatingFileHandler
- [ ] After long batch, check `assets/logs/app.log` size < 5 MB
- [ ] If > 5 MB worth of logging, verify `app.log.1` exists (rotation worked)
- [ ] Verify log encoding is UTF-8 (no mojibake on song titles with accents)

### 5.2 Performance Summary
- [ ] After batch completes, check `app.log` for performance table:
  ```
  ┌─────────────────────────────────────────────────┐
  │              PERFORMANCE SUMMARY                 │
  ```
- [ ] Verify timing data is reasonable (not 0s or negative)

---

## Phase 6: Overnight Monitoring

### What to check every hour:
1. **Apollova.exe** still running (not crashed/frozen)
2. **Disk space** not critically low
3. **Log file** growing (app is actively working)
4. **Job folders** being created with all expected files

### What to check in the morning:
1. **Batch summary** — how many succeeded vs failed
2. **app.log** — search for `ASSERT` or `ERROR` or `FATAL`
3. **Job folders** — spot-check 3 random jobs for completeness:
   - `job_data.json` exists and is valid JSON
   - `audio_trimmed.wav` exists and > 0 bytes
   - Lyrics file exists (lyrics.txt / mono_data.json / onyx_data.json)
   - `cover.png` exists (Aurora/Onyx only)
4. **setup.log** — if Setup was run, check for any FAILED packages
5. **Memory** — check Task Manager for Apollova memory usage (should be < 2 GB)

### Red Flags (investigate immediately):
- Any `ASSERT:` message in logs
- `LOW DISK` warning
- `FATAL` in log file
- Job folder with `job_data.json` but missing `audio_trimmed.wav`
- Whisper taking > 600s (10 min) for a single 15s clip
- Same song failing repeatedly

---

## Quick Commands

```bash
# Check for ASSERT warnings in app log
grep -i "ASSERT" assets/logs/app.log

# Check for errors in app log
grep -i "ERROR\|FATAL\|FAILED" assets/logs/app.log

# Count completed jobs
ls -d Apollova-Aurora/jobs/job_*/job_data.json 2>/dev/null | wc -l

# Check log file size
ls -lh assets/logs/app.log

# Check disk space
df -h .
```
