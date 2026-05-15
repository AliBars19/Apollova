"""
Pipeline Common - Shared helpers for Aurora, Mono, and Onyx main.py files.

Eliminates triplication of:
  - check_job_progress() — job state detection from files
  - run_audio_pipeline() — download + trim with caching
  - run_batch() — Config.validate + loop + stats
"""
import os
import json
from pathlib import Path

from scripts.audio_processing import download_audio, trim_audio


def load_job_data(job_folder: str) -> dict:
    """Load job_data.json from a job folder, returning {} if missing/corrupt."""
    json_path = os.path.join(job_folder, "job_data.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def check_job_progress(job_folder: str, extra_stages: dict[str, str] | None = None) -> tuple[dict, dict]:
    """
    Check which pipeline stages are already complete for a job folder.

    Always checks: audio_downloaded, audio_trimmed, job_complete.
    extra_stages: mapping of stage_name -> filename to also check.
    Returns (stages_dict, job_data_dict).
    """
    stages = {
        "audio_downloaded": os.path.exists(os.path.join(job_folder, "audio_source.mp3")),
        "audio_trimmed": os.path.exists(os.path.join(job_folder, "audio_trimmed.wav")),
        "job_complete": os.path.exists(os.path.join(job_folder, "job_data.json")),
    }

    if extra_stages:
        for stage_name, filename in extra_stages.items():
            stages[stage_name] = os.path.exists(os.path.join(job_folder, filename))

    job_data = load_job_data(job_folder)
    return stages, job_data


def run_audio_pipeline(job_folder, job_id, cached_song, job_data, console, color="cyan"):
    """
    Download and trim audio, using database cache when available.
    Returns (audio_path, trimmed_path, audio_url, start_time, end_time) or None on failure.
    """
    # === Audio Download ===
    audio_path = os.path.join(job_folder, "audio_source.mp3")
    if not os.path.exists(audio_path):
        if cached_song:
            audio_url = cached_song["youtube_url"]
            console.print(f"[dim]Using cached URL[/dim]")
        else:
            audio_url = input(f"[Job {job_id}] Audio URL: ").strip()

        console.print(f"[{color}]Downloading audio...[/{color}]")
        try:
            audio_path = download_audio(audio_url, job_folder)
        except Exception as e:
            console.print(f"[red]Failed to download audio: {e}[/red]")
            return None
    else:
        console.print("✓ Audio already downloaded")
        audio_url = (cached_song["youtube_url"] if cached_song
                     else job_data.get("youtube_url", "unknown"))

    # === Audio Trimming ===
    trimmed_path = os.path.join(job_folder, "audio_trimmed.wav")
    if not os.path.exists(trimmed_path):
        if cached_song:
            start_time = cached_song["start_time"]
            end_time = cached_song["end_time"]
            console.print(f"[dim]Using cached timing: {start_time} → {end_time}[/dim]")
        else:
            start_time = input(f"[Job {job_id}] Start time (MM:SS or Enter for 00:00): ").strip()
            if not start_time:
                start_time = "00:00"
            if start_time == "00:00":
                end_time = "01:01"
                console.print(f"[dim]Auto-set end time to {end_time}[/dim]")
            else:
                end_time = input(f"[Job {job_id}] End time (MM:SS): ").strip()

        console.print(f"[{color}]Trimming audio...[/{color}]")
        try:
            trimmed_path = trim_audio(job_folder, start_time, end_time)
        except Exception as e:
            console.print(f"[red]Failed to trim audio: {e}[/red]")
            return None
    else:
        console.print("✓ Audio already trimmed")
        if cached_song:
            start_time = cached_song["start_time"]
            end_time = cached_song["end_time"]
        else:
            start_time = job_data.get("start_time", "00:00")
            end_time = job_data.get("end_time", "01:01")

    return audio_path, trimmed_path, audio_url, start_time, end_time


def run_batch(template_name, process_fn, console, song_db, banner, color="cyan"):
    """
    Shared batch loop: validate config, create jobs dir, run process_fn for each job.

    template_name: e.g. "Aurora", "Mono", "Onyx"
    process_fn: callable(job_id) -> bool
    """
    from scripts.config import Config

    console.print(f"\n[bold {color}]{banner}[/bold {color}]\n")
    Config.validate()

    jobs_dir = os.path.join(os.path.dirname(os.path.abspath(process_fn.__code__.co_filename)), Config.JOBS_DIR)
    os.makedirs(jobs_dir, exist_ok=True)

    stats = song_db.get_stats()
    if stats["total_songs"] > 0:
        console.print(f"[dim]📊 Database: {stats['total_songs']} songs, "
                      f"{stats.get('cached_lyrics', 0)} with cached lyrics[/dim]\n")

    for job_id in range(1, Config.TOTAL_JOBS + 1):
        success = process_fn(job_id)
        if not success:
            console.print(f"\n[yellow]⚠️  Job {job_id} had errors, continuing...[/yellow]")

    console.print(f"\n[bold green]✅ All {template_name} jobs processed![/bold green]")
    stats = song_db.get_stats()
    console.print(f"\n[{color}]📊 Database: {stats['total_songs']} songs, "
                  f"{stats.get('cached_lyrics', 0)} cached, {stats['total_uses']} total uses[/{color}]")
