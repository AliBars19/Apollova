#!/usr/bin/env python3
"""
Apollova Onyx - Music Video Automation
Hybrid template: Word-by-word lyrics + spinning disc with album art
"""
import os
import sys
import json
from pathlib import Path
from rich.console import Console

# Add parent directory so we can import from shared scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio
from scripts.image_processing import download_image, extract_colors
from scripts.lyric_processing_onyx import transcribe_audio_onyx
from scripts.genius_processing import fetch_genius_image
from scripts.song_database import SongDatabase

console = Console()

# Shared database
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"
song_db = SongDatabase(db_path=str(SHARED_DB))


def check_job_progress(job_folder):
    """Check which stages are already complete"""
    stages = {
        "audio_downloaded": os.path.exists(os.path.join(job_folder, "audio_source.mp3")),
        "audio_trimmed": os.path.exists(os.path.join(job_folder, "audio_trimmed.wav")),
        "onyx_data_created": os.path.exists(os.path.join(job_folder, "onyx_data.json")),
        "image_downloaded": os.path.exists(os.path.join(job_folder, "cover.png")),
        "job_complete": os.path.exists(os.path.join(job_folder, "job_data.json"))
    }
    
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
    """Process a single Onyx job"""
    job_folder = os.path.join(os.path.dirname(__file__), Config.JOBS_DIR, f"job_{job_id:03}")
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold magenta]━━━ Onyx Job {job_id:03} ━━━[/bold magenta]")
    
    stages, job_data = check_job_progress(job_folder)
    
    # Check if already complete
    if stages["job_complete"] and all([
        stages["audio_downloaded"], stages["audio_trimmed"],
        stages["onyx_data_created"], stages["image_downloaded"]
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
    cached_onyx_lyrics = None
    cached_image_url = None
    cached_colors = None
    
    if cached_song:
        console.print(f"[green]✓ Found '{song_title}' in database! Loading cached parameters...[/green]")
        audio_url = cached_song["youtube_url"]
        start_time = cached_song["start_time"]
        end_time = cached_song["end_time"]
        cached_image_url = cached_song["genius_image_url"]
        cached_colors = cached_song["colors"]
        cached_onyx_lyrics = song_db.get_onyx_lyrics(song_title)
        
        console.print(f"[dim]  URL: {audio_url}[/dim]")
        console.print(f"[dim]  Time: {start_time} → {end_time}[/dim]")
        if cached_onyx_lyrics:
            console.print(f"[dim]  Cached Onyx lyrics: {len(cached_onyx_lyrics.get('markers', []))} markers ⚡[/dim]")
    else:
        console.print(f"[yellow]'{song_title}' not in database. Creating new entry...[/yellow]")
    
    # === Audio Download ===
    if not stages["audio_downloaded"]:
        if cached_song:
            audio_url = cached_song["youtube_url"]
            console.print(f"[dim]Using cached URL[/dim]")
        else:
            audio_url = input(f"[Job {job_id}] Audio URL: ").strip()
        
        console.print("[cyan]Downloading audio...[/cyan]")
        try:
            audio_path = download_audio(audio_url, job_folder)
        except Exception as e:
            console.print(f"[red]Failed to download audio: {e}[/red]")
            return False
    else:
        audio_path = os.path.join(job_folder, "audio_source.mp3")
        console.print("✓ Audio already downloaded")
        audio_url = cached_song["youtube_url"] if cached_song else job_data.get("youtube_url", "unknown")
    
    # === Audio Trimming ===
    if not stages["audio_trimmed"]:
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
        
        console.print("[cyan]Trimming audio...[/cyan]")
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
    
    # === Image Download (Required for Onyx disc) ===
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
                image_path = download_image(job_folder, image_url)
                genius_image_url = image_url
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
    
    # === Onyx Transcription (Onyx manages onyx_lyrics column) ===
    onyx_data_path = os.path.join(job_folder, "onyx_data.json")
    
    if cached_onyx_lyrics:
        console.print(f"[green]✓ Using cached Onyx transcription ({len(cached_onyx_lyrics.get('markers', []))} markers) ⚡[/green]")
        onyx_data = cached_onyx_lyrics
        onyx_data["colors"] = colors
        onyx_data["cover_image"] = "cover.png"
        with open(onyx_data_path, "w", encoding="utf-8") as f:
            json.dump(onyx_data, f, indent=4, ensure_ascii=False)
    elif not stages["onyx_data_created"]:
        console.print("[cyan]Transcribing with word-level timestamps (Onyx)...[/cyan]")
        try:
            onyx_data = transcribe_audio_onyx(job_folder, song_title)
            onyx_data["colors"] = colors
            onyx_data["cover_image"] = "cover.png"
            with open(onyx_data_path, "w", encoding="utf-8") as f:
                json.dump(onyx_data, f, indent=4, ensure_ascii=False)
            console.print(f"[green]✓ Onyx data: {len(onyx_data.get('markers', []))} markers[/green]")
        except Exception as e:
            console.print(f"[red]Failed to generate Onyx data: {e}[/red]")
            import traceback
            traceback.print_exc()
            return False
    else:
        with open(onyx_data_path, "r", encoding="utf-8") as f:
            onyx_data = json.load(f)
        console.print(f"✓ Onyx data already generated ({len(onyx_data.get('markers', []))} markers)")
    
    # === Save to Database (Onyx manages onyx_lyrics column) ===
    if not cached_song:
        console.print(f"[cyan]💾 Saving '{song_title}' to database...[/cyan]")
        song_db.add_song(
            song_title=song_title,
            youtube_url=audio_url,
            start_time=start_time,
            end_time=end_time,
            genius_image_url=genius_image_url,
            transcribed_lyrics=None,  # Don't touch Aurora's column
            colors=colors,
            beats=None
        )
        song_db.update_onyx_lyrics(song_title, onyx_data)
        console.print("[green]✓ Song saved to database[/green]")
    else:
        song_db.mark_song_used(song_title)
        console.print(f"[green]✓ Marked '{song_title}' as used[/green]")
        
        song_db.update_colors_and_beats(song_title, colors, None)
        if not cached_onyx_lyrics:
            song_db.update_onyx_lyrics(song_title, onyx_data)
    
    # === Save Job Data ===
    job_data = {
        "job_id": job_id,
        "audio_source": os.path.abspath(audio_path).replace("\\", "/"),
        "audio_trimmed": os.path.abspath(trimmed_path).replace("\\", "/"),
        "cover_image": os.path.abspath(image_path).replace("\\", "/"),
        "colors": colors,
        "onyx_data": os.path.abspath(onyx_data_path).replace("\\", "/"),
        "job_folder": os.path.abspath(job_folder).replace("\\", "/"),
        "song_title": song_title,
        "youtube_url": audio_url,
        "start_time": start_time,
        "end_time": end_time,
        "marker_count": len(onyx_data.get("markers", []))
    }
    
    json_path = os.path.join(job_folder, "job_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4)
    
    console.print(f"[green]✓ Onyx Job {job_id:03} complete[/green]")
    return True


def batch_generate_jobs():
    """Generate all Onyx jobs"""
    console.print("\n[bold magenta]💿 Apollova Onyx - Hybrid Lyric Videos[/bold magenta]\n")
    Config.validate()
    
    jobs_dir = os.path.join(os.path.dirname(__file__), Config.JOBS_DIR)
    os.makedirs(jobs_dir, exist_ok=True)
    
    stats = song_db.get_stats()
    if stats["total_songs"] > 0:
        console.print(f"[dim]📊 Database: {stats['total_songs']} songs, "
                      f"{stats['cached_lyrics']} with cached lyrics[/dim]\n")
    
    for job_id in range(1, Config.TOTAL_JOBS + 1):
        success = process_single_job(job_id)
        if not success:
            console.print(f"\n[yellow]⚠️  Job {job_id} had errors, continuing...[/yellow]")
    
    console.print("\n[bold green]✅ All Onyx jobs processed![/bold green]")
    console.print("\n[cyan]Next:[/cyan] Run the After Effects JSX script")
    console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_onyx.jsx[/dim]\n")


if __name__ == "__main__":
    try:
        batch_generate_jobs()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Fatal error: {e}[/red]")
        raise