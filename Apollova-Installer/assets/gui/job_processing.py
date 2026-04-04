"""Job processing — generation, single-song pipeline, cleanup."""

import io
import json
import os
import shutil
import sys
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QSystemTrayIcon

from assets.gui.constants import JOBS_DIRS
from assets.gui.helpers import _set_label_style  # noqa: F401 — used in delegating methods


def validate_inputs(app) -> bool:
    errors = []
    if app.use_smart_picker:
        picker = app.smart_picker
        stats = picker.get_database_stats()
        if stats['total_songs'] == 0:
            errors.append(
                "Database empty. Add songs via Manual Entry first.")
        else:
            songs = picker.get_available_songs(
                num_songs=int(app.jobs_combo.currentText()))
            if not songs:
                errors.append("No songs available in database.")
            else:
                bad = []
                for s in songs:
                    song_errors = app._validate_song_record(
                        s['youtube_url'], s['start_time'], s['end_time'])
                    if song_errors:
                        bad.append((s['song_title'], song_errors))
                if bad:
                    lines = [
                        f"{len(bad)} of the {len(songs)} selected song(s) "
                        f"have invalid data and cannot be processed:\n"]
                    for song_title, errs in bad:
                        lines.append(f"\u2022 {song_title}:")
                        for e in errs:
                            lines.append(f"    \u2013 {e}")
                    lines.append(
                        "\nFix these entries in your database "
                        "(Settings \u2192 Database Editor) before generating.")
                    errors.append("\n".join(lines))
    else:
        n = int(app.jobs_combo.currentText())
        if len(app._job_queue) < n:
            errors.append(
                f"Queue has {len(app._job_queue)} / {n} jobs. "
                "Add all jobs before generating.")
    if errors:
        QMessageBox.critical(app, "Validation Error", "\n\n".join(errors))
        return False
    return True


def lock_inputs(app, lock: bool) -> None:
    for w in [app.title_edit, app.url_edit, app.start_edit,
              app.end_edit, app.jobs_combo, app.whisper_combo,
              app.add_job_btn, app.reshuffle_btn, app.reset_uses_btn]:
        w.setEnabled(not lock)
    for btn in app.job_tpl_group.buttons():
        btn.setEnabled(not lock)
    app.remove_job_btn.setEnabled(False)
    app.clear_queue_btn.setEnabled(not lock and bool(app._job_queue))


def start_generation(app) -> None:
    if not app._validate_inputs():
        return
    t = app._job_template()
    d = JOBS_DIRS.get(t)
    existing = list(d.glob("job_*")) if d.exists() else []

    if app.use_smart_picker:
        songs = app._smart_songs
        if not songs:
            QMessageBox.warning(app, "No Songs",
                "No songs selected. Refresh or reshuffle first.")
            return
        sl = "\n".join(
            [f"  {i+1}. {s['song_title'][:40]}"
             for i, s in enumerate(songs[:12])])
        if len(songs) > 12:
            sl += f"\n  \u2026 and {len(songs)-12} more"
        reply = QMessageBox.question(
            app, "Smart Picker Confirmation",
            f"Generate {len(songs)} jobs for {t.upper()}?\n\n"
            f"Songs:\n{sl}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

    if existing:
        complete = [j for j in existing
                    if (j / "job_data.json").exists()]
        incomplete = [j for j in existing
                      if not (j / "job_data.json").exists()]
        detail = f"Found {len(existing)} existing job(s)"
        if complete:
            detail += f"\n  \u2022 {len(complete)} complete"
        if incomplete:
            detail += f"\n  \u2022 {len(incomplete)} incomplete / failed"

        dlg = QMessageBox(app)
        dlg.setWindowTitle("Existing Jobs")
        dlg.setText("Existing jobs detected")
        dlg.setInformativeText(
            detail + "\n\n"
            "Delete All  \u2014  wipe everything and start fresh\n"
            "Resume  \u2014  skip completed and failed jobs, "
            "continue from where left off\n"
            "Cancel  \u2014  do nothing"
        )
        delete_btn = dlg.addButton(
            "Delete All", QMessageBox.ButtonRole.DestructiveRole)
        resume_btn = dlg.addButton(
            "Resume", QMessageBox.ButtonRole.AcceptRole)
        dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dlg.setDefaultButton(resume_btn)
        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked == delete_btn:
            for j in existing:
                shutil.rmtree(j)
            app._resume_mode = False
            app._check_existing_jobs()
        elif clicked == resume_btn:
            app._resume_mode = True
        else:
            return

    app.is_processing = True
    app.cancel_requested = False
    app._lock_inputs(True)
    app.generate_btn.setEnabled(False)
    app.cancel_btn.setEnabled(True)
    app.log_text.clear()
    app.progress_bar.setValue(0)
    threading.Thread(target=process_jobs, args=(app,), daemon=True).start()


def cancel_generation(app) -> None:
    app.cancel_requested = True
    app.cancel_btn.setEnabled(False)
    app.signals.log.emit(
        "\u26a0 Cancelling \u2014 stopping current operation\u2026")


def run_step(app, job_number: int, step_name: str, fn, *args, **kwargs):
    """Run a processing step. On failure, logs the full traceback to file
    and re-raises with the step name prepended so the popup is useful."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        tb = traceback.format_exc()
        if app._log:
            app._log.error(
                f"[Job {job_number:03}] STEP FAILED \u2014 {step_name}\n"
                f"  {type(e).__name__}: {e}\n{tb}")
        raise RuntimeError(
            f"[{step_name}] {type(e).__name__}: {e}") from None


def process_jobs(app) -> None:
    from assets.apollova_gui import (
        Config, download_audio, trim_audio, detect_beats,
        download_image, extract_colors, transcribe_audio,
        transcribe_audio_mono, transcribe_audio_onyx,
        fetch_genius_image, fetch_genius_image_rotated,
    )
    try:
        batch_t0 = time.time()
        num = int(app.jobs_combo.currentText())
        t = app._job_template()
        outd = JOBS_DIRS.get(t)
        Config.WHISPER_MODEL = app.whisper_combo.currentText()
        Config.GENIUS_API_TOKEN = app.settings.get('genius_api_token', '')

        if app._log:
            mode = "SmartPicker" if app.use_smart_picker else "Manual"
            app._log.section(
                f"Job batch started \u2014 {num} job(s) | {t.upper()} | "
                f"{mode} | Whisper: {Config.WHISPER_MODEL}")
            try:
                disk = shutil.disk_usage(str(outd or "."))
                app._log.info(
                    f"System: disk_free={disk.free/(1024**3):.1f}GB  "
                    f"python={sys.version.split()[0]}  pid={os.getpid()}")
            except Exception:
                pass

        if app.use_smart_picker:
            songs = list(app._smart_songs)
            app.signals.log.emit(
                f"\U0001f916 Smart Picker: {len(songs)} songs | {t.upper()}")
            picker = app.smart_picker
            outd.mkdir(parents=True, exist_ok=True)

            start_idx = 1
            if app._resume_mode:
                all_existing = list(outd.glob("job_*"))
                done = [j for j in all_existing
                        if (j / "job_data.json").exists()]
                failed = [j for j in all_existing
                          if not (j / "job_data.json").exists()]
                nums = [
                    int(j.name.split("_")[1]) for j in all_existing
                    if j.name.startswith("job_")
                    and j.name.split("_")[1].isdigit()]
                start_idx = (max(nums) + 1) if nums else 1
                remaining = num - len(all_existing)
                if remaining <= 0:
                    app.signals.log.emit(
                        "All jobs already complete \u2014 nothing to do.")
                    app.signals.finished.emit()
                    return
                app.signals.log.emit(
                    f"  Resuming from job {start_idx} "
                    f"({len(done)} complete, {len(failed)} failed/skipped, "
                    f"{remaining} remaining)")
                songs = songs[:remaining]

            skipped = []
            for i, s in enumerate(songs):
                idx = start_idx + i
                if app.cancel_requested:
                    raise Exception("Cancelled by user")
                app.signals.log.emit(
                    f"\n{'='*40}\n\U0001f4c0 Job {idx}/{num}: "
                    f"{s['song_title'][:40]}")
                try:
                    process_single_song(
                        app, idx, s['song_title'], s['youtube_url'],
                        s['start_time'], s['end_time'], t, outd)
                    picker.mark_song_used(s['song_title'])
                except Exception as song_err:
                    if str(song_err) == "Cancelled by user":
                        raise
                    app.signals.log.emit(
                        f"  \u26a0 Skipping song \u2014 {song_err}")
                    skipped.append(s['song_title'])
                app.signals.progress.emit(idx / num * 100)
            completed = len(songs) - len(skipped)
            skip_note = (
                f"\n\u26a0 {len(skipped)} song(s) skipped: "
                + ", ".join(skipped)) if skipped else ""
            app.signals.log.emit(
                f"\n{'='*40}\n\U0001f389 Done! {completed}/{num} "
                f"job(s) created!{skip_note}\n\U0001f4c2 {outd}\n"
                "Next: Go to JSX Injection tab")
        else:
            total = len(app._job_queue)
            app.signals.log.emit(
                f"Starting {total} queued job(s) | {t.upper()}")
            outd.mkdir(parents=True, exist_ok=True)
            skipped = []
            for idx, job in enumerate(app._job_queue, 1):
                if app.cancel_requested:
                    raise Exception("Cancelled by user")
                if app._resume_mode and (outd / f"job_{idx:03}").exists():
                    job_folder_status = (
                        "complete"
                        if (outd / f"job_{idx:03}" / "job_data.json").exists()
                        else "previously failed \u2014 skipping"
                    )
                    app.signals.log.emit(
                        f"\n{'='*40}\n\u23ed Job {idx}/{total}: "
                        f"{job['title'][:40]} \u2014 {job_folder_status}")
                    app.signals.progress.emit(idx / total * 100)
                    continue
                app.signals.log.emit(
                    f"\n{'='*40}\n\U0001f4c0 Job {idx}/{total}: "
                    f"{job['title'][:40]}")
                try:
                    process_single_song(
                        app, idx, job['title'], job['url'],
                        job['start'], job['end'], t, outd)
                except Exception as song_err:
                    if str(song_err) == "Cancelled by user":
                        raise
                    app.signals.log.emit(
                        f"  \u26a0 Skipping song \u2014 {song_err}")
                    skipped.append(job['title'])
                app.signals.progress.emit(idx / total * 100)
                elapsed = time.time() - batch_t0
                avg_per_job = elapsed / idx
                remaining = avg_per_job * (total - idx)
                rem_min, rem_sec = divmod(int(remaining), 60)
                if idx < total:
                    app.signals.log.emit(
                        f"  \u23f1 ETA: ~{rem_min}m {rem_sec}s remaining "
                        f"({total - idx} jobs left)")
            completed = total - len(skipped)
            skip_note = (
                f"\n\u26a0 {len(skipped)} song(s) skipped: "
                + ", ".join(skipped)) if skipped else ""
            app.signals.log.emit(
                f"\n{'='*40}\n\U0001f389 Done! {completed}/{total} "
                f"job(s) created!{skip_note}\n\U0001f4c2 {outd}\n"
                "Next: Go to JSX Injection tab")

        # Batch completion summary
        batch_elapsed = time.time() - batch_t0
        batch_min, batch_sec = divmod(int(batch_elapsed), 60)
        device_str = "unknown"
        try:
            from scripts.whisper_common import get_device_info
            device_str = get_device_info()
        except Exception:
            pass
        completed_count = num - len(skipped)
        avg_time = batch_elapsed / max(completed_count, 1)
        avg_min, avg_sec = divmod(int(avg_time), 60)
        rule = "\u2500" * 40
        app.signals.log.emit(
            f"\n{rule}\n"
            f"BATCH SUMMARY\n"
            f"  Total time:  {batch_min}m {batch_sec:02d}s\n"
            f"  Per job avg: {avg_min}m {avg_sec:02d}s\n"
            f"  Succeeded:   {completed_count}\n"
            f"  Failed:      {len(skipped)}\n"
            f"  Device:      {device_str}\n"
            f"{rule}")
        if app._log:
            app._log.performance_summary(
                {"Batch total": batch_elapsed},
                total_time=batch_elapsed,
                device=device_str)

        # Free GPU memory
        try:
            from scripts.whisper_common import unload_model
            unload_model()
            app.signals.log.emit("  \u267b Whisper model unloaded")
        except Exception:
            pass

        app.signals.stats_refresh.emit()
        app.signals.finished.emit()
    except Exception as e:
        tb = traceback.format_exc()
        app.signals.log.emit(f"\u274c Error: {e}")
        app.signals.log.emit(f"\u2500\u2500\u2500 Traceback \u2500\u2500\u2500\n{tb}")
        if app._log:
            app._log.error(
                f"Job batch failed: {type(e).__name__}: {e}\n{tb}")
        app.signals.error.emit(str(e))


def on_generation_finished(app) -> None:
    app.is_processing = False
    app._resume_mode = False
    app._smart_songs = []
    app._job_queue.clear()
    app._rebuild_queue_list()
    app._update_queue_counter()
    app._lock_inputs(False)
    app._update_generate_btn_state()
    app.cancel_btn.setEnabled(False)
    app._check_existing_jobs()
    if app.use_smart_picker:
        app._refresh_smart_picker_stats()
    QMessageBox.information(app, "Complete!",
        f"Jobs created for {app._job_template().upper()}!\n\n"
        "Go to JSX Injection tab to inject into After Effects.")


def on_generation_error(app, msg: str) -> None:
    app.is_processing = False
    app._resume_mode = False
    app._smart_songs = []
    app._lock_inputs(False)
    app._update_generate_btn_state()
    app.cancel_btn.setEnabled(False)
    app._check_existing_jobs()

    fix = ""
    lower = msg.lower()
    if "cancelled" in lower:
        fix = ""
    elif any(k in lower for k in
             ("youtube", "yt_dlp", "pytubefix", "video")):
        fix = (
            "\n\nFix: Check the YouTube URL is correct and the video "
            "is public.\nIf YouTube is blocking downloads, try updating: "
            "pip install -U yt-dlp")
    elif any(k in lower for k in
             ("whisper", "transcri", "torch", "cuda")):
        fix = (
            "\n\nFix: Whisper transcription failed. Try:\n"
            "  1. Re-run Setup.exe to reinstall PyTorch\n"
            "  2. Try a smaller Whisper model (tiny/base)\n"
            "  3. Check that audio_trimmed.wav exists in the job folder")
    elif any(k in lower for k in ("genius", "lyrics", "api")):
        fix = (
            "\n\nFix: Genius API issue. Check your API token in Settings.\n"
            "Get a token at: https://genius.com/api-clients")
    elif any(k in lower for k in ("permission", "access", "denied")):
        fix = (
            "\n\nFix: Permission error. Try:\n"
            "  1. Run Apollova as Administrator\n"
            "  2. Check the install folder is not read-only")
    elif any(k in lower for k in ("no module", "import")):
        fix = (
            "\n\nFix: A required package is missing. "
            "Re-run Setup.exe to reinstall.")

    QMessageBox.critical(app, "Error", msg + fix)


def broadcast_progress(app, percent: float) -> None:
    """Forward progress updates to connected WebSocket clients."""
    if hasattr(app, '_ws_emit_progress') and app._ws_emit_progress:
        msg = (app.status_label.text()
               if hasattr(app, 'status_label') else "")
        app._ws_emit_progress(percent, msg)


def append_log(app, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    app.log_text.append(f"[{ts}] {msg}")
    app.status_label.setText(msg[:80])
    if app._log:
        if "\u274c" in msg or "error" in msg.lower() or "fail" in msg.lower():
            app._log.error(msg)
        elif "\u26a0" in msg or "warning" in msg.lower():
            app._log.warning(msg)
        else:
            app._log.info(msg)


def refresh_stats_label(app) -> None:
    s = app.song_db.get_stats()
    app.stats_label.setText(
        f"\U0001f4ca {s['total_songs']} songs | "
        f"{s['cached_lyrics']} with lyrics")


# ── Transcription progress ticker ─────────────────────────────────────────────

def run_with_ticker(app, fn, *args, **kwargs):
    """Run a long function with periodic log updates.
    Captures stdout/stderr to show pass-level progress and tqdm bars.
    Checks cancel_requested every second and force-kills the worker."""
    import ctypes
    result = [None]
    error = [None]
    done = threading.Event()
    last_pct = [None]
    last_pass = [""]
    signals = app.signals

    class _LogCapture:
        """Intercepts print() output from scripts, extracts progress."""
        def __init__(self, signals_ref, pct_ref, pass_ref):
            self._sig = signals_ref
            self._pct = pct_ref
            self._pass = pass_ref

        def write(self, s):
            if not s or not s.strip():
                return len(s) if s else 0
            line = s.strip()
            if "Transcribe:" in line and "%" in line:
                try:
                    pct = line.split("%")[0].split()[-1]
                    pct_val = int(float(pct))
                    if (self._pct[0] is None
                            or abs(pct_val - self._pct[0]) >= 10):
                        self._pct[0] = pct_val
                        pass_label = self._pass[0]
                        self._sig.log.emit(
                            f"    {pass_label} {pct_val}%")
                except (ValueError, IndexError):
                    pass
                return len(s)
            if line.startswith("Pass ") or line.startswith("  Pass "):
                self._pass[0] = line.strip()
                self._pct[0] = None
                self._sig.log.emit(f"    {line.strip()}")
                return len(s)
            if ("segments" in line
                    and ("\u2192" in line or "\u2713" in line
                         or "\u26a0" in line)):
                self._sig.log.emit(f"    {line.strip()}")
                return len(s)
            if "Loading" in line and ("GPU" in line or "CPU" in line):
                self._sig.log.emit(f"    {line.strip()}")
                return len(s)
            if "Reusing cached" in line:
                self._sig.log.emit(f"    {line.strip()}")
                return len(s)
            return len(s)

        def flush(self):
            pass

        def fileno(self):
            raise io.UnsupportedOperation("fileno")

    def _worker():
        capture = _LogCapture(signals, last_pct, last_pass)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = capture
        sys.stderr = capture
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as e:
            error[0] = e
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    elapsed = 0
    while not done.wait(timeout=1):
        elapsed += 1
        if app.cancel_requested:
            app.signals.log.emit("  Cancelling transcription\u2026")
            tid = t.ident
            if tid is not None:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_ulong(tid),
                    ctypes.py_object(SystemExit))
            done.wait(timeout=3)
            try:
                from scripts.whisper_common import unload_model
                unload_model()
            except Exception:
                pass
            raise Exception("Cancelled by user")
        if elapsed % 15 == 0 and last_pct[0] is None:
            m, s = divmod(elapsed, 60)
            app.signals.log.emit(
                f"    Transcribing... ({m}m {s:02d}s elapsed)")

    if error[0] is not None:
        raise error[0]
    return result[0]


# ── Single song processing ────────────────────────────────────────────────────

def process_single_song(app, job_number: int, song_title: str,
                        youtube_url: str, start_time: str,
                        end_time: str, template: str,
                        output_dir: Path, return_data: bool = False):
    from assets.apollova_gui import (
        Config, download_audio, trim_audio, detect_beats,
        download_image, extract_colors, transcribe_audio,
        transcribe_audio_mono, transcribe_audio_onyx,
        fetch_genius_image, fetch_genius_image_rotated,
    )

    job_t0 = time.time()
    job_folder = output_dir / f"job_{job_number:03}"
    job_folder.mkdir(parents=True, exist_ok=True)
    needs_image = template in ['aurora', 'onyx']
    cached = app.song_db.get_song(song_title)

    try:
        disk = shutil.disk_usage(str(output_dir))
        disk_free_gb = disk.free / (1024 ** 3)
        app.signals.log.emit(f"  [diag] Disk free: {disk_free_gb:.1f} GB")
        if disk_free_gb < 1.0:
            app.signals.log.emit(
                "  \u26a0 LOW DISK: less than 1 GB free!")
            if app._log:
                app._log.warning(
                    f"Low disk space at job {job_number}: "
                    f"{disk_free_gb:.1f} GB")
    except Exception:
        pass

    if cached:
        app.signals.log.emit("  \u2713 Using cached data")
        youtube_url = cached['youtube_url']
        start_time = cached['start_time']
        end_time = cached['end_time']

    def chk():
        if app.cancel_requested:
            raise Exception("Cancelled by user")

    # Audio download
    chk()
    audio_path = job_folder / "audio_source.mp3"
    if not audio_path.exists():
        app.signals.log.emit("  Downloading audio\u2026")
        app._run_step(
            job_number, "Audio download",
            download_audio, youtube_url, str(job_folder))
        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio download produced no file: {audio_path}")
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        app.signals.log.emit(
            f"  \u2713 Audio downloaded ({size_mb:.1f} MB)")
    else:
        app.signals.log.emit("  \u2713 Audio exists")

    # Trim
    chk()
    trimmed = job_folder / "audio_trimmed.wav"
    if not trimmed.exists():
        app.signals.log.emit(
            f"  Trimming ({start_time} \u2192 {end_time})\u2026")
        app._run_step(
            job_number, "Audio trim",
            trim_audio, str(job_folder), start_time, end_time)
        if not trimmed.exists():
            raise FileNotFoundError(
                f"Trim produced no file: {trimmed}")
        trim_mb = trimmed.stat().st_size / (1024 * 1024)
        app.signals.log.emit(f"  \u2713 Trimmed ({trim_mb:.1f} MB)")
    else:
        app.signals.log.emit("  \u2713 Trimmed audio exists")

    # Verify trimmed audio duration
    try:
        from pydub import AudioSegment as _AS
        actual_dur = len(_AS.from_file(str(trimmed))) / 1000.0
        s_parts = start_time.split(':')
        e_parts = end_time.split(':')
        expected_dur = (
            (int(e_parts[0]) * 60 + int(e_parts[1]))
            - (int(s_parts[0]) * 60 + int(s_parts[1])))
        app.signals.log.emit(
            f"  \U0001f4cf Clip: {actual_dur:.1f}s "
            f"(expected {expected_dur}s)")
        if actual_dur > expected_dur + 5:
            app.signals.log.emit(
                f"  \u26a0 audio_trimmed.wav too long "
                f"({actual_dur:.1f}s) \u2014 re-trimming")
            trimmed.unlink()
            app._run_step(
                job_number, "Audio re-trim",
                trim_audio, str(job_folder), start_time, end_time)
            actual_dur = len(_AS.from_file(str(trimmed))) / 1000.0
            app.signals.log.emit(
                f"  \u2713 Re-trimmed: {actual_dur:.1f}s")
    except Exception as dur_err:
        app.signals.log.emit(
            f"  \u26a0 Duration check failed: {dur_err}")

    # Delete audio_source.mp3
    source_mp3 = job_folder / "audio_source.mp3"
    if source_mp3.exists():
        try:
            source_mp3.unlink()
        except Exception:
            pass

    # Log Whisper device
    try:
        from scripts.whisper_common import get_device_info
        app.signals.log.emit(
            f"  \U0001f5a5 Whisper device: {get_device_info()}")
    except Exception:
        pass

    # Beats (Aurora only)
    beats = []
    if template == 'aurora':
        chk()
        beats_path = job_folder / "beats.json"
        if cached and cached.get('beats'):
            beats = cached['beats']
            with open(beats_path, 'w', encoding='utf-8') as f:
                json.dump(beats, f, indent=4)
            app.signals.log.emit("  \u2713 Cached beats")
        elif not beats_path.exists():
            app.signals.log.emit("  Detecting beats\u2026")
            beats = app._run_step(
                job_number, "Beat detection",
                detect_beats, str(job_folder))
            with open(beats_path, 'w', encoding='utf-8') as f:
                json.dump(beats, f, indent=4)
            app.signals.log.emit(f"  \u2713 {len(beats)} beats")
        else:
            with open(beats_path) as f:
                beats = json.load(f)
            app.signals.log.emit("  \u2713 Beats exist")

    # Transcribe (per-template)
    chk()
    lyrics_path = job_folder / "lyrics.txt"
    lyrics_was_transcribed = False
    if template == 'aurora':
        if cached and cached.get('transcribed_lyrics'):
            with open(lyrics_path, 'w', encoding='utf-8') as f:
                json.dump(
                    cached['transcribed_lyrics'], f,
                    indent=4, ensure_ascii=False)
            app.signals.log.emit(
                f"  \u2713 Cached lyrics "
                f"({len(cached['transcribed_lyrics'])} segs)")
        elif not lyrics_path.exists():
            app.signals.log.emit(
                f"  Transcribing ({Config.WHISPER_MODEL})\u2026")
            t0 = time.time()
            app._run_with_ticker(
                app._run_step, job_number,
                "Whisper transcription (Aurora)",
                transcribe_audio, str(job_folder), song_title)
            elapsed = time.time() - t0
            app.signals.log.emit(
                f"  \u2713 Transcribed ({elapsed:.0f}s)")
            lyrics_was_transcribed = True
            if not lyrics_path.exists():
                app.signals.log.emit(
                    "  \u26a0 ASSERT: lyrics.txt missing "
                    "after transcription!")
            elif lyrics_path.stat().st_size < 10:
                app.signals.log.emit(
                    f"  \u26a0 ASSERT: lyrics.txt suspiciously small "
                    f"({lyrics_path.stat().st_size} bytes)")
        else:
            app.signals.log.emit("  \u2713 Lyrics exist")
        lyrics_data = (lyrics_path.read_text()
                       if lyrics_path.exists() else "")

    elif template == 'mono':
        mono_path = job_folder / "mono_data.json"
        cached_mono = app.song_db.get_mono_lyrics(song_title)
        if cached_mono:
            with open(mono_path, 'w', encoding='utf-8') as f:
                json.dump(
                    cached_mono, f, indent=4, ensure_ascii=False)
            app.signals.log.emit("  \u2713 Cached mono lyrics")
        elif not mono_path.exists():
            app.signals.log.emit(
                f"  Transcribing mono ({Config.WHISPER_MODEL})\u2026")
            t0 = time.time()
            mono_result = app._run_with_ticker(
                app._run_step, job_number,
                "Whisper transcription (Mono)",
                transcribe_audio_mono, str(job_folder), song_title)
            elapsed = time.time() - t0
            if mono_result:
                with open(mono_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        mono_result, f, indent=4, ensure_ascii=False)
            app.signals.log.emit(
                f"  \u2713 Transcribed mono ({elapsed:.0f}s)")
            lyrics_was_transcribed = True
            if not mono_path.exists():
                app.signals.log.emit(
                    "  \u26a0 ASSERT: mono_data.json missing "
                    "after transcription!")
            elif mono_path.stat().st_size < 10:
                app.signals.log.emit(
                    f"  \u26a0 ASSERT: mono_data.json suspiciously "
                    f"small ({mono_path.stat().st_size} bytes)")
        else:
            app.signals.log.emit("  \u2713 Mono data exists")
        lyrics_data = (mono_path.read_text()
                       if mono_path.exists() else "{}")

    elif template == 'onyx':
        onyx_path = job_folder / "onyx_data.json"
        cached_onyx = app.song_db.get_onyx_lyrics(song_title)
        if cached_onyx:
            with open(onyx_path, 'w', encoding='utf-8') as f:
                json.dump(
                    cached_onyx, f, indent=4, ensure_ascii=False)
            app.signals.log.emit("  \u2713 Cached onyx lyrics")
        elif not onyx_path.exists():
            app.signals.log.emit(
                f"  Transcribing onyx ({Config.WHISPER_MODEL})\u2026")
            t0 = time.time()
            onyx_result = app._run_with_ticker(
                app._run_step, job_number,
                "Whisper transcription (Onyx)",
                transcribe_audio_onyx, str(job_folder), song_title)
            elapsed = time.time() - t0
            if onyx_result:
                with open(onyx_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        onyx_result, f, indent=4, ensure_ascii=False)
            app.signals.log.emit(
                f"  \u2713 Transcribed onyx ({elapsed:.0f}s)")
            lyrics_was_transcribed = True
            if not onyx_path.exists():
                app.signals.log.emit(
                    "  \u26a0 ASSERT: onyx_data.json missing "
                    "after transcription!")
            elif onyx_path.stat().st_size < 10:
                app.signals.log.emit(
                    f"  \u26a0 ASSERT: onyx_data.json suspiciously "
                    f"small ({onyx_path.stat().st_size} bytes)")
        else:
            app.signals.log.emit("  \u2713 Onyx data exists")
        lyrics_data = (onyx_path.read_text()
                       if onyx_path.exists() else "{}")

    else:
        lyrics_data = ""

    # Image / colors
    image_path = job_folder / "cover.png"
    colors = ['#ffffff', '#000000']
    rotation_enabled = app.settings.get('image_rotation', False)
    rotated_url = None
    if needs_image:
        chk()
        if rotation_enabled and Config.GENIUS_API_TOKEN:
            current_url = (cached.get('genius_image_url')
                           if cached else None)
            app.signals.log.emit("  Rotating cover image\u2026")
            if image_path.exists():
                image_path.unlink()
            _, rotated_url = app._run_step(
                job_number, "Image rotation",
                fetch_genius_image_rotated,
                song_title, str(job_folder), current_url)
            if image_path.exists():
                app.signals.log.emit("  \u2713 Rotated cover")
            else:
                app.signals.log.emit(
                    "  \u26a0 Rotation failed, using standard fetch")
                ok = app._run_step(
                    job_number, "Genius image fetch",
                    fetch_genius_image, song_title, str(job_folder))
                app.signals.log.emit(
                    "  \u2713 Cover" if ok else "  \u26a0 No cover")
        elif cached and cached.get('genius_image_url'):
            if not image_path.exists():
                app.signals.log.emit(
                    "  Downloading cached image\u2026")
                app._run_step(
                    job_number, "Image download",
                    download_image, str(job_folder),
                    cached['genius_image_url'])
            app.signals.log.emit("  \u2713 Cached image")
        elif not image_path.exists():
            app.signals.log.emit("  Fetching cover\u2026")
            ok = app._run_step(
                job_number, "Genius image fetch",
                fetch_genius_image, song_title, str(job_folder))
            app.signals.log.emit(
                "  \u2713 Cover" if ok else "  \u26a0 No cover")
        else:
            app.signals.log.emit("  \u2713 Cover exists")
        chk()
        if image_path.exists():
            if (cached and cached.get('colors')
                    and not rotation_enabled):
                colors = cached['colors']
                app.signals.log.emit("  \u2713 Cached colors")
            else:
                app.signals.log.emit("  Extracting colors\u2026")
                colors = app._run_step(
                    job_number, "Color extraction",
                    extract_colors, str(job_folder))
                app.signals.log.emit(
                    f"  \u2713 Colors: {', '.join(colors)}")

    data_file = {
        'aurora': job_folder / "lyrics.txt",
        'mono': job_folder / "mono_data.json",
        'onyx': job_folder / "onyx_data.json",
    }.get(template, job_folder / "lyrics.txt")

    job_data = {
        "job_id": job_number, "song_title": song_title,
        "youtube_url": youtube_url, "start_time": start_time,
        "end_time": end_time, "template": template,
        "audio_trimmed": str(job_folder / "audio_trimmed.wav"),
        "cover_image": (str(image_path) if image_path.exists()
                        else None),
        "colors": colors, "lyrics_file": str(data_file),
        "beats": beats, "created_at": datetime.now().isoformat(),
    }
    _missing = [
        k for k in ("job_id", "song_title", "audio_trimmed",
                     "lyrics_file")
        if not job_data.get(k)]
    if _missing:
        app.signals.log.emit(
            f"  \u26a0 ASSERT: job_data missing fields: {_missing}")
    if not Path(job_data["audio_trimmed"]).exists():
        app.signals.log.emit(
            "  \u26a0 ASSERT: audio_trimmed path in job_data "
            "does not exist!")

    with open(job_folder / "job_data.json", 'w', encoding='utf-8') as f:
        json.dump(job_data, f, indent=4)

    if not cached and not app.use_smart_picker:
        app.signals.log.emit("  Saving to database\u2026")
        app.song_db.add_song(
            song_title=song_title, youtube_url=youtube_url,
            start_time=start_time, end_time=end_time,
            genius_image_url=None, colors=colors, beats=beats)
    elif cached and not app.use_smart_picker:
        app.song_db.mark_song_used(song_title)
    if rotated_url:
        app.song_db.update_image_url(song_title, rotated_url)
        app.song_db.update_colors_and_beats(
            song_title, colors, None)
    if lyrics_was_transcribed:
        try:
            lyrics_parsed = (json.loads(lyrics_data)
                             if lyrics_data else None)
        except (json.JSONDecodeError, TypeError):
            lyrics_parsed = None
        if lyrics_parsed is not None:
            if template == 'aurora':
                app.song_db.update_lyrics(song_title, lyrics_parsed)
            elif template == 'mono':
                app.song_db.update_mono_lyrics(
                    song_title, lyrics_parsed)
            elif template == 'onyx':
                app.song_db.update_onyx_lyrics(
                    song_title, lyrics_parsed)
            if app.use_smart_picker:
                app.signals.log.emit(
                    "  \u2713 Lyrics cached to database")
        else:
            app.signals.log.emit(
                "  \u26a0 No lyrics data to cache")

    job_elapsed = time.time() - job_t0
    jm, js = divmod(int(job_elapsed), 60)
    app.signals.log.emit(
        f"  \u2713 Job {job_number} complete ({jm}m {js:02d}s)")
    if app._log:
        app._log.info(
            f"Job {job_number} [{song_title[:30]}] "
            f"finished in {job_elapsed:.1f}s")
    return (job_data, job_folder) if return_data else None


# ── Close / cleanup ───────────────────────────────────────────────────────────

def cleanup_and_quit(app) -> None:
    """Shared cleanup for both tray-quit and window-close."""
    app.cancel_requested = True
    app.batch_render_cancelled = True
    if app._tunnel_manager:
        try:
            app._tunnel_manager.stop()
        except Exception:
            pass
    try:
        from scripts.whisper_common import unload_model
        unload_model()
    except Exception:
        pass
    try:
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "Apollova"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    if app._log:
        app._log.session_end(
            "Apollova GUI", success=not app.is_processing)


def close_event(app, event) -> None:
    """Minimize to system tray instead of quitting."""
    if getattr(app, '_force_quit', False):
        app._cleanup_and_quit()
        event.accept()
        return

    if hasattr(app, 'tray_icon') and app.tray_icon.isVisible():
        app.hide()
        app.tray_icon.showMessage(
            "Apollova",
            "Running in the background. "
            "Right-click the tray icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )
        event.ignore()
    else:
        app._cleanup_and_quit()
        event.accept()
