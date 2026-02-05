#!/usr/bin/env python3
"""
Music Video Automation - Visuals Nova
Minimal text-only lyric videos with word-by-word reveal
"""
import os
import sys
import json
from pathlib import Path
from rich.console import Console

# Ensure scripts directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio
from scripts.lyric_processing import transcribe_audio_nova
from scripts.song_database import SongDatabase

console = Console()

# Initialize song database with shared path (one level up from Visuals-Nova)
# Structure: MV-AE-PROJECT/database/songs.db
#           MV-AE-PROJECT/Visuals-Nova/main_nova.py (this file)
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"
song_db = SongDatabase(db_path=str(SHARED_DB))


def check_job_progress(job_folder):
    """Check which stages are already complete for a job"""
    stages = {
        "audio_downloaded": os.path.exists(os.path.join(job_folder, "audio_source.mp3")),
        "audio_trimmed": os.path.exists(os.path.join(job_folder, "audio_trimmed.wav")),
        "nova_data_generated": os.path.exists(os.path.join(job_folder, "nova_data.json")),
        "job_complete": os.path.exists(os.path.join(job_folder, "job_data.json"))
    }
    
    # Load existing job data if available
    job_data = {}
    json_path = os.path.join(job_folder, "job_data.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                job_data = json.load(f)
        except:
            pass
    
    return stages, job_data


def process_single_job(job_id):
    """Process a single job for Nova (minimal text-only style)"""
    # Jobs folder is local to this project
    job_folder = os.path.join(os.path.dirname(__file__), "jobs", f"job_{job_id:03}")
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold magenta]━━━ Nova Job {job_id:03} ━━━[/bold magenta]")
    
    stages, job_data = check_job_progress(job_folder)
    
    # === Check if job is already complete ===
    if stages["job_complete"] and all([
        stages["audio_downloaded"],
        stages["audio_trimmed"],
        stages["nova_data_generated"]
    ]):
        song_title = job_data.get("song_title", "Unknown")
        console.print(f"[green]✓ Job {job_id:03} already complete: {song_title}[/green]")
        return True
    
    # === Get Song Title FIRST ===
    song_title = job_data.get("song_title")
    if not song_title:
        song_title = input(f"[Job {job_id}] Song Title (Artist - Song): ").strip()
    else:
        console.print(f"[dim]Song: {song_title}[/dim]")
    
    # === Check Database for Cached Parameters ===
    cached_song = song_db.get_song(song_title)
    
    if cached_song:
        console.print(f"[green]✓ Found '{song_title}' in database! Loading cached parameters...[/green]")
        
        # Use cached parameters
        audio_url = cached_song["youtube_url"]
        start_time = cached_song["start_time"]
        end_time = cached_song["end_time"]
        cached_lyrics = cached_song["transcribed_lyrics"]
        
        console.print(f"[dim]  URL: {audio_url}[/dim]")
        console.print(f"[dim]  Time: {start_time} → {end_time}[/dim]")
        if cached_lyrics:
            console.print(f"[dim]  Cached lyrics: {len(cached_lyrics)} segments ⚡[/dim]")
    else:
        console.print(f"[yellow]'{song_title}' not in database. Creating new entry...[/yellow]")
        cached_lyrics = None
    
    # === Audio Download ===
    if not stages["audio_downloaded"]:
        if cached_song:
            audio_url = cached_song["youtube_url"]
            console.print(f"[dim]Using cached URL[/dim]")
        else:
            audio_url = input(f"[Job {job_id}] Audio URL: ").strip()
        
        console.print("[magenta]Downloading audio...[/magenta]")
        try:
            audio_path = download_audio(audio_url, job_folder)
        except Exception as e:
            console.print(f"[red]Failed to download audio: {e}[/red]")
            return False
    else:
        audio_path = os.path.join(job_folder, "audio_source.mp3")
        console.print("✓ Audio already downloaded")
        if cached_song:
            audio_url = cached_song["youtube_url"]
        elif "youtube_url" in job_data:
            audio_url = job_data.get("youtube_url", "unknown")
        else:
            audio_url = "unknown"
    
    # === Audio Trimming ===
    if not stages["audio_trimmed"]:
        if cached_song:
            start_time = cached_song["start_time"]
            end_time = cached_song["end_time"]
            console.print(f"[dim]Using cached timing: {start_time} → {end_time}[/dim]")
        else:
            start_time = input(f"[Job {job_id}] Start time (MM:SS or press Enter for 00:00): ").strip()
            if not start_time:
                start_time = "00:00"
            
            if start_time == "00:00":
                end_time = "01:01"
                console.print(f"[dim]Auto-set end time to {end_time}[/dim]")
            else:
                end_time = input(f"[Job {job_id}] End time (MM:SS): ").strip()
        
        console.print("[magenta]Trimming audio...[/magenta]")
        try:
            trimmed_path = trim_audio(job_folder, start_time, end_time)
        except Exception as e:
            console.print(f"[red]Failed to trim audio: {e}[/red]")
            return False
    else:
        trimmed_path = os.path.join(job_folder, "audio_trimmed.wav")
        console.print("✓ Audio already trimmed")
        if cached_song:
            start_time = cached_song["start_time"]
            end_time = cached_song["end_time"]
        else:
            start_time = job_data.get("start_time", "00:00")
            end_time = job_data.get("end_time", "01:01")
    
    # === Nova Transcription (Word-Level Timestamps) ===
    nova_data_path = os.path.join(job_folder, "nova_data.json")
    
    if not stages["nova_data_generated"]:
        console.print("[magenta]Transcribing with word-level timestamps...[/magenta]")
        try:
            nova_data = transcribe_audio_nova(job_folder, song_title)
            
            # Save nova_data.json
            with open(nova_data_path, "w", encoding="utf-8") as f:
                json.dump(nova_data, f, indent=4, ensure_ascii=False)
            
            transcribed_lyrics = nova_data.get("markers", [])
            console.print(f"[green]✓ Nova data generated: {len(transcribed_lyrics)} markers[/green]")
            
        except Exception as e:
            console.print(f"[red]Failed to generate Nova data: {e}[/red]")
            import traceback
            traceback.print_exc()
            return False
    else:
        with open(nova_data_path, "r", encoding="utf-8") as f:
            nova_data = json.load(f)
        transcribed_lyrics = nova_data.get("markers", [])
        console.print(f"✓ Nova data already generated ({len(transcribed_lyrics)} markers)")
    
    # === Save to Database ===
    if not cached_song:
        console.print(f"[magenta]💾 Saving '{song_title}' to database...[/magenta]")
        song_db.add_song(
            song_title=song_title,
            youtube_url=audio_url,
            start_time=start_time,
            end_time=end_time,
            genius_image_url=None,  # Nova doesn't use images
            transcribed_lyrics=transcribed_lyrics,
            colors=None,  # Nova doesn't use colors from images
            beats=None    # Nova doesn't use beat detection
        )
        console.print("[green]✓ Song saved to database for future use[/green]")
    else:
        song_db.mark_song_used(song_title)
        console.print(f"[green]✓ Marked '{song_title}' as used in database[/green]")
        
        # Update lyrics if we generated new ones
        if transcribed_lyrics:
            song_db.update_lyrics(song_title, transcribed_lyrics)
    
    # === Save Job Data ===
    job_data = {
        "job_id": job_id,
        "audio_source": audio_path.replace("\\", "/"),
        "audio_trimmed": trimmed_path.replace("\\", "/"),
        "nova_data": nova_data_path.replace("\\", "/"),
        "job_folder": job_folder.replace("\\", "/"),
        "song_title": song_title,
        "youtube_url": audio_url,
        "start_time": start_time,
        "end_time": end_time,
        "marker_count": len(transcribed_lyrics)
    }
    
    json_path = os.path.join(job_folder, "job_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4)
    
    console.print(f"[green]✓ Nova Job {job_id:03} complete[/green]")
    return True


def batch_generate_jobs():
    """Generate all Nova jobs with database caching"""
    console.print("\n[bold magenta]🎬 Music Video Automation - Visuals Nova[/bold magenta]")
    console.print("[dim]Minimal text-only lyric videos[/dim]\n")
    
    # Validate config
    Config.validate()
    
    # Create jobs directory (local to this project)
    jobs_dir = os.path.join(os.path.dirname(__file__), Config.JOBS_DIR)
    os.makedirs(jobs_dir, exist_ok=True)
    
    # Show database stats
    stats = song_db.get_stats()
    console.print(f"[dim]📊 Database: {SHARED_DB}[/dim]")
    if stats["total_songs"] > 0:
        console.print(f"[dim]   {stats['total_songs']} songs, "
                     f"{stats['cached_lyrics']} with cached lyrics[/dim]\n")
    
    # Process each job
    total_jobs = Config.TOTAL_JOBS
    
    for job_id in range(1, total_jobs + 1):
        success = process_single_job(job_id)
        
        if not success:
            console.print(f"\n[yellow]⚠️  Job {job_id} had errors, continuing...[/yellow]")
    
    console.print("\n[bold green]✅ All Nova jobs processed![/bold green]")
    
    # Show updated stats
    stats = song_db.get_stats()
    console.print(f"\n[magenta]📊 Database now has:[/magenta]")
    console.print(f"   {stats['total_songs']} songs")
    console.print(f"   {stats['cached_lyrics']} with cached lyrics")
    console.print(f"   {stats['total_uses']} total uses")
    
    console.print("\n[magenta]Next step:[/magenta] Run the After Effects JSX script")
    console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_nova.jsx[/dim]\n")


if __name__ == "__main__":
    try:
        batch_generate_jobs()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Fatal error: {e}[/red]")
        raise