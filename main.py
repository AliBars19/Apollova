import os
import json
from rich.console import Console

from scripts.config import Config
from scripts.audio_processing import download_audio, trim_audio, detect_beats
from scripts.image_processing import download_image, extract_colors
from scripts.lyric_processing import transcribe_audio

console = Console()


def check_job_progress(job_folder):
    stages = {
        "audio_downloaded": os.path.exists(os.path.join(job_folder, "audio_source.mp3")),
        "audio_trimmed": os.path.exists(os.path.join(job_folder, "audio_trimmed.wav")),
        "lyrics_transcribed": os.path.exists(os.path.join(job_folder, "lyrics.txt")),
        "image_downloaded": os.path.exists(os.path.join(job_folder, "cover.png")),
        "beats_generated": os.path.exists(os.path.join(job_folder, "beats.json")),
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
    job_folder = f"jobs/job_{job_id:03}"
    os.makedirs(job_folder, exist_ok=True)
    
    console.print(f"\n[bold cyan]━━━ Job {job_id:03} ━━━[/bold cyan]")
    
    stages, job_data = check_job_progress(job_folder)
    
    # Get or reuse song title
    song_title = job_data.get("song_title")
    
    # === Audio Download ===
    if not stages["audio_downloaded"]:
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
    
    # === Song Title ===
    if not song_title:
        song_title = input(f"[Job {job_id}] Song Title (Artist - Song): ").strip()
    
    # === Audio Trimming ===
    if not stages["audio_trimmed"]:
        start_time = input(f"[Job {job_id}] Start time (MM:SS or press Enter for 00:00): ").strip()
        if not start_time:
            start_time = "00:00"
        
        # Auto-calculate end time if start is 00:00
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
    
    # === Beat Detection ===
    beats_path = os.path.join(job_folder, "beats.json")
    if not stages["beats_generated"]:
        console.print("[cyan]Detecting beats...[/cyan]")
        beats = detect_beats(job_folder)
        with open(beats_path, "w", encoding="utf-8") as f:
            json.dump(beats, f, indent=4)
    else:
        with open(beats_path, "r", encoding="utf-8") as f:
            beats = json.load(f)
        console.print("✓ Beats already detected")
    
    # === Lyrics Transcription ===
    if not stages["lyrics_transcribed"]:
        console.print("[cyan]Transcribing lyrics...[/cyan]")
        try:
            lyrics_path = transcribe_audio(job_folder, song_title)
        except Exception as e:
            console.print(f"[yellow]Warning: Transcription failed: {e}[/yellow]")
            # Create empty lyrics as fallback
            lyrics_path = os.path.join(job_folder, "lyrics.txt")
            with open(lyrics_path, "w", encoding="utf-8") as f:
                json.dump([], f)
    else:
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        console.print("✓ Lyrics already transcribed")
    
    # === Image Download (Auto-fetch from Genius) ===
    if not stages["image_downloaded"]:
        console.print("[cyan]Fetching cover image from Genius...[/cyan]")
        try:
            # Import here to avoid circular dependency
            from scripts.genius_processing import fetch_genius_image
            
            image_path = fetch_genius_image(song_title, job_folder)
            
            if not image_path:
                # Fallback to manual input
                console.print("[yellow]Couldn't auto-fetch image from Genius[/yellow]")
                image_url = input(f"[Job {job_id}] Enter Cover Image URL manually: ").strip()
                console.print("[cyan]Downloading image...[/cyan]")
                image_path = download_image(job_folder, image_url)
                
        except Exception as e:
            console.print(f"[yellow]Auto-fetch failed: {e}[/yellow]")
            image_url = input(f"[Job {job_id}] Enter Cover Image URL manually: ").strip()
            console.print("[cyan]Downloading image...[/cyan]")
            try:
                image_path = download_image(job_folder, image_url)
            except Exception as e2:
                console.print(f"[red]Failed to download image: {e2}[/red]")
                return False
    else:
        image_path = os.path.join(job_folder, "cover.png")
        console.print(" Image already downloaded")
    
    # === Color Extraction ===
    console.print("[cyan]Extracting colors...[/cyan]")
    colors = extract_colors(job_folder)
    
    # === Save Job Data ===
    job_data = {
        "job_id": job_id,
        "audio_source": audio_path.replace("\\", "/"),
        "audio_trimmed": trimmed_path.replace("\\", "/"),
        "cover_image": image_path.replace("\\", "/"),
        "colors": colors,
        "lyrics_file": lyrics_path.replace("\\", "/"),
        "beats": beats,
        "job_folder": job_folder.replace("\\", "/"),
        "song_title": song_title
    }
    
    json_path = os.path.join(job_folder, "job_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4)
    
    console.print(f"[green] Job {job_id:03} complete[/green]")
    return True


def batch_generate_jobs():
    console.print("\n[bold cyan] Music Video Automation[/bold cyan]\n")
    
    # Validate config
    Config.validate()
    
    # Create jobs directory
    os.makedirs(Config.JOBS_DIR, exist_ok=True)
    
    # Process each job
    total_jobs = Config.TOTAL_JOBS
    
    for job_id in range(1, total_jobs + 1):
        success = process_single_job(job_id)
        
        if not success:
            console.print(f"\n[yellow]  Job {job_id} had errors, continuing...[/yellow]")
    
    console.print("\n[bold green] All jobs processed![/bold green]")
    console.print("\n[cyan]Next step:[/cyan] Run the After Effects JSX script")
    console.print("[dim]File → Scripts → Run Script File... → scripts/automateMV_batch.jsx[/dim]\n")


if __name__ == "__main__":
    try:
        batch_generate_jobs()
    except KeyboardInterrupt:
        console.print("\n[yellow]  Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red] Fatal error: {e}[/red]")
        raise