#!/usr/bin/env python3
"""
Apollova Aurora - Music Video Automation
Full visual effects with cover art, gradients, beat-synced lighting
"""
import os
import sys
import json
from pathlib import Path
from rich.console import Console

# Add parent directory so we can import from shared scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import Config
from scripts.audio_processing import detect_beats
from scripts.image_processing import download_image, extract_colors
from scripts.lyric_processing import transcribe_audio
from scripts.genius_processing import fetch_genius_image
from scripts.song_database import SongDatabase
from scripts.pipeline_common import check_job_progress, run_audio_pipeline, run_batch

console = Console()

# Shared database
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"
song_db = SongDatabase(db_path=str(SHARED_DB))


_AURORA_STAGES = {
    "lyrics_transcribed": "lyrics.txt",
    "image_downloaded": "cover.png",
    "beats_generated": "beats.json",
}


def process_single_job(job_id):
    """Process a single Aurora job with database caching"""
    job_folder = os.path.join(os.path.dirname(__file__), "jobs", f"job_{job_id:03}")
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold cyan]━━━ Aurora Job {job_id:03} ━━━[/bold cyan]")
    
    stages, job_data = check_job_progress(job_folder, _AURORA_STAGES)
    
    # Check if already complete
    if stages["job_complete"] and all([
        stages["audio_downloaded"], stages["audio_trimmed"],
        stages["lyrics_transcribed"], stages["image_downloaded"],
        stages["beats_generated"]
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
    cached_image_url = None
    cached_lyrics = None
    cached_colors = None
    cached_beats = None
    
    if cached_song:
        console.print(f"[green]✓ Found '{song_title}' in database! Loading cached parameters...[/green]")
        audio_url = cached_song["youtube_url"]
        start_time = cached_song["start_time"]
        end_time = cached_song["end_time"]
        cached_image_url = cached_song["genius_image_url"]
        cached_lyrics = cached_song["transcribed_lyrics"]
        cached_colors = cached_song["colors"]
        cached_beats = cached_song["beats"]
        
        console.print(f"[dim]  URL: {audio_url}[/dim]")
        console.print(f"[dim]  Time: {start_time} → {end_time}[/dim]")
        if cached_lyrics:
            console.print(f"[dim]  Cached lyrics: {len(cached_lyrics)} segments ⚡[/dim]")
    else:
        console.print(f"[yellow]'{song_title}' not in database. Creating new entry...[/yellow]")
    
    # === Audio Download + Trim ===
    audio_result = run_audio_pipeline(job_folder, job_id, cached_song, job_data, console, color="cyan")
    if audio_result is None:
        return False
    audio_path, trimmed_path, audio_url, start_time, end_time = audio_result
    
    # === Beat Detection ===
    beats_path = os.path.join(job_folder, "beats.json")
    if cached_beats:
        console.print("[green]✓ Using cached beat data[/green]")
        beats = cached_beats
        with open(beats_path, "w", encoding="utf-8") as f:
            json.dump(beats, f, indent=4)
    elif not stages["beats_generated"]:
        console.print("[cyan]Detecting beats...[/cyan]")
        beats = detect_beats(job_folder)
        with open(beats_path, "w", encoding="utf-8") as f:
            json.dump(beats, f, indent=4)
    else:
        with open(beats_path, "r", encoding="utf-8") as f:
            beats = json.load(f)
        console.print("✓ Beats already detected")
    
    # === Lyrics Transcription (Aurora column) ===
    transcribed_lyrics = None
    if cached_lyrics:
        console.print(f"[green]✓ Using cached transcription ({len(cached_lyrics)} segments) ⚡[/green]")
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "w", encoding="utf-8") as f:
            json.dump(cached_lyrics, f, indent=4, ensure_ascii=False)
        transcribed_lyrics = cached_lyrics
    elif not stages["lyrics_transcribed"]:
        console.print("[cyan]Transcribing lyrics (this will be cached)...[/cyan]")
        try:
            lyrics_path = transcribe_audio(job_folder, song_title)
            with open(lyrics_path, "r", encoding="utf-8") as f:
                transcribed_lyrics = json.load(f)
        except Exception as e:
            console.print(f"[red]Failed to transcribe: {e}[/red]")
            return False
    else:
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "r", encoding="utf-8") as f:
            transcribed_lyrics = json.load(f)
        console.print(f"✓ Lyrics already transcribed ({len(transcribed_lyrics)} segments)")
    
    # === Image Download ===
    genius_image_url = cached_image_url or "unknown"
    if cached_image_url and not stages["image_downloaded"]:
        console.print("[green]✓ Using cached image URL[/green]")
        console.print("[cyan]Downloading image...[/cyan]")
        try:
            image_path = download_image(job_folder, cached_image_url)
        except Exception as e:
            console.print(f"[yellow]Cached image failed: {e}[/yellow]")
            cached_image_url = None
    
    if not cached_image_url and not stages["image_downloaded"]:
        console.print("[cyan]Fetching cover image from Genius...[/cyan]")
        try:
            image_path = fetch_genius_image(song_title, job_folder)
            if image_path:
                genius_image_url = "fetched_from_genius"
            else:
                image_url = input(f"[Job {job_id}] Enter Cover Image URL manually: ").strip()
                console.print("[cyan]Downloading image...[/cyan]")
                try:
                    image_path = download_image(job_folder, image_url)
                    genius_image_url = image_url
                except Exception as e2:
                    console.print(f"[red]Failed to download image: {e2}[/red]")
                    return False
        except Exception as e:
            console.print(f"[yellow]Auto-fetch failed: {e}[/yellow]")
            image_url = input(f"[Job {job_id}] Enter Cover Image URL manually: ").strip()
            console.print("[cyan]Downloading image...[/cyan]")
            try:
                image_path = download_image(job_folder, image_url)
                genius_image_url = image_url
            except Exception as e2:
                console.print(f"[red]Failed to download image: {e2}[/red]")
                return False
    elif stages["image_downloaded"]:
        image_path = os.path.join(job_folder, "cover.png")
        console.print("✓ Image already downloaded")
    
    # === Color Extraction ===
    if cached_colors:
        console.print(f"[green]✓ Using cached colors: {', '.join(cached_colors)}[/green]")
        colors = cached_colors
    else:
        console.print("[cyan]Extracting colors...[/cyan]")
        colors = extract_colors(job_folder)
    
    # === Save to Database (Aurora manages transcribed_lyrics column) ===
    if not cached_song:
        console.print(f"[cyan]💾 Saving '{song_title}' to database...[/cyan]")
        song_db.add_song(
            song_title=song_title,
            youtube_url=audio_url,
            start_time=start_time,
            end_time=end_time,
            genius_image_url=genius_image_url,
            transcribed_lyrics=transcribed_lyrics,
            colors=colors,
            beats=beats
        )
        console.print("[green]✓ Song saved to database[/green]")
    else:
        song_db.mark_song_used(song_title)
        console.print(f"[green]✓ Marked '{song_title}' as used[/green]")
        
        # Update any newly generated data
        song_db.update_colors_and_beats(song_title, colors, beats)
        if transcribed_lyrics and not cached_lyrics:
            song_db.update_lyrics(song_title, transcribed_lyrics)
    
    # === Save Job Data ===
    job_data = {
        "job_id": job_id,
        "audio_source": os.path.abspath(audio_path).replace("\\", "/"),
        "audio_trimmed": os.path.abspath(trimmed_path).replace("\\", "/"),
        "cover_image": os.path.abspath(image_path).replace("\\", "/"),
        "colors": colors,
        "lyrics_file": os.path.abspath(lyrics_path).replace("\\", "/"),
        "beats": beats,
        "job_folder": os.path.abspath(job_folder).replace("\\", "/"),
        "song_title": song_title,
        "youtube_url": audio_url,
        "start_time": start_time,
        "end_time": end_time
    }
    
    json_path = os.path.join(job_folder, "job_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4)
    
    console.print(f"[green]✓ Aurora Job {job_id:03} complete[/green]")
    return True


def batch_generate_jobs():
    """Generate all Aurora jobs"""
    run_batch("Aurora", process_single_job, console, song_db,
              "🎬 Apollova Aurora - Music Video Automation", color="cyan")
    console.print("\n[cyan]Next:[/cyan] Run the After Effects JSX script")
    console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_batch.jsx[/dim]\n")


if __name__ == "__main__":
    try:
        batch_generate_jobs()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Fatal error: {e}[/red]")
        raise