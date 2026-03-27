#!/usr/bin/env python3
"""
Apollova Mono - Music Video Automation
Minimal text-only lyric videos with word-by-word reveal
"""
import os
import sys
import json
import traceback
from pathlib import Path
from rich.console import Console

# Add parent directory so we can import from shared scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import Config
from scripts.lyric_processing_mono import transcribe_audio_mono
from scripts.song_database import SongDatabase
from scripts.pipeline_common import check_job_progress, run_audio_pipeline, run_batch

console = Console()

# Shared database
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"
song_db = SongDatabase(db_path=str(SHARED_DB))

# Mono uses longer lines (no image overlay)
Config.set_max_line_length(40)


_MONO_STAGES = {
    "mono_data_generated": "mono_data.json",
}


def process_single_job(job_id):
    """Process a single Mono job"""
    job_folder = os.path.join(os.path.dirname(__file__), "jobs", f"job_{job_id:03}")
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold magenta]━━━ Mono Job {job_id:03} ━━━[/bold magenta]")
    
    stages, job_data = check_job_progress(job_folder, _MONO_STAGES)
    
    # Check if already complete
    if stages["job_complete"] and all([
        stages["audio_downloaded"], stages["audio_trimmed"],
        stages["mono_data_generated"]
    ]):
        song_title = job_data.get("song_title", "Unknown")
        console.print(f"[green]✓ Job {job_id:03} already complete: {song_title}[/green]")
        return True
    
    # === Get Song Title ===
    song_title = job_data.get("song_title")
    if not song_title:
        song_title = input(f"[Job {job_id}] Song Title (Artist - Song): ").strip()
    else:
        console.print(f"[dim]Song: {song_title}[/dim]")
    
    # === Check Database Cache ===
    cached_song = song_db.get_song(song_title)
    cached_mono_lyrics = song_db.get_mono_lyrics(song_title)
    
    if cached_song:
        console.print(f"[green]✓ Found '{song_title}' in database! Loading cached parameters...[/green]")
        audio_url = cached_song["youtube_url"]
        start_time = cached_song["start_time"]
        end_time = cached_song["end_time"]
        
        console.print(f"[dim]  URL: {audio_url}[/dim]")
        console.print(f"[dim]  Time: {start_time} → {end_time}[/dim]")
        if cached_mono_lyrics:
            console.print(f"[dim]  Cached Mono lyrics: {len(cached_mono_lyrics)} markers ⚡[/dim]")
    else:
        console.print(f"[yellow]'{song_title}' not in database. Creating new entry...[/yellow]")
    
    # === Audio Download + Trim ===
    audio_result = run_audio_pipeline(job_folder, job_id, cached_song, job_data, console, color="magenta")
    if audio_result is None:
        return False
    audio_path, trimmed_path, audio_url, start_time, end_time = audio_result
    
    # === Mono Transcription (Mono manages mono_lyrics column) ===
    mono_data_path = os.path.join(job_folder, "mono_data.json")
    transcribed_lyrics = None
    
    if cached_mono_lyrics:
        console.print(f"[green]✓ Using cached Mono lyrics ({len(cached_mono_lyrics)} markers) ⚡[/green]")
        mono_data = {"markers": cached_mono_lyrics, "total_markers": len(cached_mono_lyrics)}
        with open(mono_data_path, "w", encoding="utf-8") as f:
            json.dump(mono_data, f, indent=4, ensure_ascii=False)
        transcribed_lyrics = cached_mono_lyrics
    elif not stages["mono_data_generated"]:
        console.print("[magenta]Transcribing with word-level timestamps...[/magenta]")
        try:
            mono_data = transcribe_audio_mono(job_folder, song_title)
            with open(mono_data_path, "w", encoding="utf-8") as f:
                json.dump(mono_data, f, indent=4, ensure_ascii=False)
            transcribed_lyrics = mono_data.get("markers", [])
            console.print(f"[green]✓ Mono data generated: {len(transcribed_lyrics)} markers[/green]")
        except Exception as e:
            console.print(f"[red]Failed to generate Mono data: {e}[/red]")
            traceback.print_exc()
            return False
    else:
        with open(mono_data_path, "r", encoding="utf-8") as f:
            mono_data = json.load(f)
        transcribed_lyrics = mono_data.get("markers", [])
        console.print(f"✓ Mono data already generated ({len(transcribed_lyrics)} markers)")
    
    # === Save to Database (Mono manages mono_lyrics column) ===
    if not cached_song:
        console.print(f"[magenta]💾 Saving '{song_title}' to database...[/magenta]")
        song_db.add_song(
            song_title=song_title,
            youtube_url=audio_url,
            start_time=start_time,
            end_time=end_time,
            genius_image_url=None,
            transcribed_lyrics=None,  # Don't touch Aurora's column
            colors=None,
            beats=None
        )
        if transcribed_lyrics:
            song_db.update_mono_lyrics(song_title, transcribed_lyrics)
        console.print("[green]✓ Song saved to database[/green]")
    else:
        song_db.mark_song_used(song_title)
        console.print(f"[green]✓ Marked '{song_title}' as used[/green]")
        
        if transcribed_lyrics and not cached_mono_lyrics:
            song_db.update_mono_lyrics(song_title, transcribed_lyrics)
    
    # === Save Job Data ===
    job_data = {
        "job_id": job_id,
        "audio_source": os.path.abspath(audio_path).replace("\\", "/"),
        "audio_trimmed": os.path.abspath(trimmed_path).replace("\\", "/"),
        "mono_data": os.path.abspath(mono_data_path).replace("\\", "/"),
        "job_folder": os.path.abspath(job_folder).replace("\\", "/"),
        "song_title": song_title,
        "youtube_url": audio_url,
        "start_time": start_time,
        "end_time": end_time,
        "marker_count": len(transcribed_lyrics) if transcribed_lyrics else 0
    }
    
    json_path = os.path.join(job_folder, "job_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4)
    
    console.print(f"[green]✓ Mono Job {job_id:03} complete[/green]")
    return True


def batch_generate_jobs():
    """Generate all Mono jobs"""
    run_batch("Mono", process_single_job, console, song_db,
              "🎵 Apollova Mono - Minimal Lyric Videos", color="magenta")
    console.print("\n[magenta]Next:[/magenta] Run the After Effects JSX script")
    console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_mono.jsx[/dim]\n")


if __name__ == "__main__":
    try:
        batch_generate_jobs()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Fatal error: {e}[/red]")
        raise