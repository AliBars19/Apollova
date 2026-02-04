#!/usr/bin/env python3
"""
Visuals NOVA - Automated word-by-word lyric video generation
Minimal aesthetic with color flip per line
"""
import os
import json
from pathlib import Path
from rich.console import Console

from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio
from scripts.lyric_processing import transcribe_audio_nova, convert_nova_markers_to_ae_format
from scripts.song_database import SongDatabase

console = Console()

# Initialize song database with shared path
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"
song_db = SongDatabase(db_path=str(SHARED_DB))


def process_nova_job(job_id):
    """Process a single NOVA job"""
    job_folder = f"jobs/job_{job_id:03}"
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold cyan]━━━ NOVA Job {job_id:03} ━━━[/bold cyan]")
    
    # Check if already complete
    json_path = os.path.join(job_folder, "nova_data.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            job_data = json.load(f)
        song_title = job_data.get("song_title", "Unknown")
        console.print(f"[green]✓ Job {job_id:03} already complete: {song_title}[/green]")
        return True
    
    # Get song info
    song_title = input(f"[Job {job_id}] Song Title (Artist - Song): ").strip()
    
    # Check database
    cached_song = song_db.get_song(song_title)
    
    if cached_song:
        console.print(f"[green]✅ Found '{song_title}' in database[/green]")
        youtube_url = cached_song['youtube_url']
        start_time = cached_song['start_time']
        end_time = cached_song['end_time']
        console.print(f"[dim]✓ Using cached URL and timestamps[/dim]")
    else:
        console.print(f"[yellow]❌ '{song_title}' not in database. Creating new entry...[/yellow]")
        youtube_url = input(f"[Job {job_id}] Audio URL: ").strip()
        start_time = input(f"[Job {job_id}] Start time (MM:SS): ").strip()
        end_time = input(f"[Job {job_id}] End time (MM:SS): ").strip()
    
    # Download audio
    if not os.path.exists(os.path.join(job_folder, "audio_source.mp3")):
        console.print(f"[Job {job_id}] Downloading audio...")
        audio_path = download_audio(youtube_url, job_folder)
        if not audio_path:
            console.print(f"[red]❌ Audio download failed[/red]")
            return False
    else:
        console.print("[dim]✓ Audio already downloaded[/dim]")
    
    # Trim audio
    if not os.path.exists(os.path.join(job_folder, "audio_trimmed.wav")):
        console.print(f"[Job {job_id}] Trimming audio...")
        trimmed_path = trim_audio(job_folder, start_time, end_time)
        if not trimmed_path:
            console.print(f"[red]❌ Audio trimming failed[/red]")
            return False
    else:
        console.print("[dim]✓ Audio already trimmed[/dim]")
    
    # Transcribe with word-level timestamps
    console.print(f"[Job {job_id}] Transcribing with word-level timing...")
    markers_path = transcribe_audio_nova(job_folder, song_title)
    
    if not markers_path:
        console.print(f"[red]❌ Transcription failed[/red]")
        return False
    
    # Load markers
    with open(markers_path, "r", encoding="utf-8") as f:
        nova_markers = json.load(f)
    
    # Convert to AE format
    ae_markers = convert_nova_markers_to_ae_format(nova_markers)
    
    # Save job data
    job_data = {
        "job_id": job_id,
        "song_title": song_title,
        "youtube_url": youtube_url,
        "start_time": start_time,
        "end_time": end_time,
        "markers": ae_markers,
        "total_markers": len(ae_markers)
    }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2, ensure_ascii=False)
    
    # Update database
    if cached_song:
        song_db.mark_song_used(song_title)
        console.print(f"[green]✓ Marked '{song_title}' as used[/green]")
    else:
        song_db.add_song(
            song_title=song_title,
            youtube_url=youtube_url,
            start_time=start_time,
            end_time=end_time
        )
        console.print(f"[green]✓ Added '{song_title}' to database[/green]")
    
    console.print(f"[green]✓ NOVA Job {job_id:03} complete ({len(ae_markers)} markers)[/green]")
    return True


def main():
    console.print("[bold cyan]🎵 Visuals NOVA - Word-by-Word Automation[/bold cyan]\n")
    
    # Always 12 jobs
    num_jobs = 12
    
    import time
    start = time.time()
    
    successful = 0
    for i in range(1, num_jobs + 1):
        if process_nova_job(i):
            successful += 1
    
    elapsed = time.time() - start
    
    console.print(f"\n[bold cyan]━━━ Summary ━━━[/bold cyan]")
    console.print(f"Completed: {successful}/{num_jobs}")
    console.print(f"Time: {elapsed:.1f}s")
    console.print()
    console.print("[cyan]Next:[/cyan] Run the NOVA JSX script in After Effects")


if __name__ == "__main__":
    main()