#!/usr/bin/env python3
"""
Smart Picker - Aurora Edition
Auto-select 12 songs and run them with Aurora processing
"""
import os
import sys
import shutil
from pathlib import Path

# Ensure this script can find local modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.smart_picker import SmartSongPicker
from scripts.song_database import SongDatabase
from scripts.config import Config
from main import process_single_job
from rich.console import Console

console = Console()

# Shared database path
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"


def check_existing_jobs():
    """Check if jobs folder already has completed jobs and offer to delete"""
    jobs_dir = os.path.join(os.path.dirname(__file__), Config.JOBS_DIR)
    
    if not os.path.exists(jobs_dir):
        return True
    
    existing_jobs = []
    for i in range(1, 13):
        job_folder = os.path.join(jobs_dir, f"job_{i:03}")
        job_data_path = os.path.join(job_folder, "job_data.json")
        if os.path.exists(job_data_path):
            existing_jobs.append(i)
    
    if not existing_jobs:
        return True
    
    console.print(f"[yellow]⚠️  Found {len(existing_jobs)} existing completed jobs[/yellow]")
    console.print(f"[dim]   Jobs: {', '.join(str(j) for j in existing_jobs)}[/dim]")
    
    response = input("\nDelete existing jobs and start fresh? (y/N): ").strip().lower()
    
    if response == 'y':
        for i in range(1, 13):
            job_folder = os.path.join(jobs_dir, f"job_{i:03}")
            if os.path.exists(job_folder):
                try:
                    shutil.rmtree(job_folder)
                    console.print(f"[dim]   Deleted job_{i:03}[/dim]")
                except Exception as e:
                    console.print(f"[red]   Failed to delete job_{i:03}: {e}[/red]")
        console.print("[green]✓ Cleared existing jobs[/green]\n")
        return True
    else:
        console.print("[yellow]Cancelled.[/yellow]")
        return False


def main():
    console.print("[bold cyan]🤖 Smart Song Picker - Apollova Aurora[/bold cyan]\n")
    
    # Check database exists
    if not SHARED_DB.exists():
        console.print(f"[red]❌ Database not found at: {SHARED_DB}[/red]")
        console.print("[yellow]Run main.py first to create the database.[/yellow]")
        return
    
    # Check for existing jobs first
    if not check_existing_jobs():
        return
    
    picker = SmartSongPicker(db_path=str(SHARED_DB))
    stats = picker.get_database_stats()
    
    if stats['total_songs'] == 0:
        console.print("[red]❌ Database is empty. Add songs first using main.py[/red]")
        return
    
    console.print(f"[dim]📊 Database: {SHARED_DB}[/dim]")
    console.print(f"[dim]   {stats['total_songs']} songs, {stats['unused_songs']} unused[/dim]\n")
    
    # Get 12 songs
    songs = picker.get_available_songs(num_songs=12)
    
    if len(songs) < 12:
        console.print(f"[yellow]⚠️  Only {len(songs)} songs available in database[/yellow]\n")
    
    console.print("[cyan]📋 Next 12 songs:[/cyan]")
    for i, song in enumerate(songs, 1):
        status = "unused" if song['use_count'] == 1 else f"{song['use_count']}x"
        console.print(f"  {i:2}. {song['song_title']:<45} ({status})")
    
    console.print()
    response = input("Run these Aurora jobs? (Y/n): ").strip().lower()
    if response == 'n':
        console.print("Cancelled.")
        return
    
    console.print()
    
    # Monkey-patch input to auto-provide song titles
    song_index = [0]
    import builtins
    original_input = builtins.input
    
    def smart_input(prompt):
        if "Song Title" in prompt:
            if song_index[0] >= len(songs):
                return original_input(prompt)
            song = songs[song_index[0]]
            song_index[0] += 1
            console.print(f"{prompt}[auto] {song['song_title']}")
            return song['song_title']
        else:
            return original_input(prompt)
    
    builtins.input = smart_input
    
    # Process jobs
    import time
    start = time.time()
    
    successful = 0
    num_jobs = min(len(songs), 12)
    
    for i in range(1, num_jobs + 1):
        try:
            if process_single_job(i):
                successful += 1
        except Exception as e:
            console.print(f"[red]Job {i} failed: {e}[/red]")
            import traceback
            traceback.print_exc()
    
    elapsed = time.time() - start
    
    # Restore original input
    builtins.input = original_input
    
    console.print(f"\n[bold cyan]━━━ Summary ━━━[/bold cyan]")
    console.print(f"Completed: {successful}/{num_jobs}")
    console.print(f"Time: {elapsed:.1f}s")
    
    if successful == num_jobs:
        console.print(f"\n[green]✅ All Aurora jobs ready![/green]")
        console.print("[cyan]Next step:[/cyan] Run the After Effects JSX script")
        console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_batch.jsx[/dim]\n")


if __name__ == "__main__":
    main()