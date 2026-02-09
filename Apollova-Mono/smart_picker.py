#!/usr/bin/env python3
"""
Smart Picker - Nova Edition
Auto-select 12 songs and run them with Nova processing
"""
import os
import sys
from pathlib import Path

# Ensure this script can find local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.smart_picker import SmartSongPicker
from scripts.song_database import SongDatabase
from main import process_single_job
from rich.console import Console

console = Console()

# Shared database path (one level up from Visuals-Nova)
# Structure: MV-AE-PROJECT/database/songs.db
#           MV-AE-PROJECT/Visuals-Nova/run_smart_picker_nova.py (this file)
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"


def main():
    console.print("[bold magenta]🤖 Smart Song Picker - Visuals Nova[/bold magenta]\n")
    
    # Check database exists
    if not SHARED_DB.exists():
        console.print(f"[red]❌ Database not found at: {SHARED_DB}[/red]")
        console.print("[yellow]Run main_nova.py first to create the database.[/yellow]")
        return
    
    picker = SmartSongPicker(db_path=str(SHARED_DB))
    stats = picker.get_database_stats()
    
    if stats['total_songs'] == 0:
        console.print("[red]❌ Database is empty. Add songs first using main_nova.py[/red]")
        return
    
    console.print(f"[dim]📊 Database: {SHARED_DB}[/dim]")
    console.print(f"[dim]   {stats['total_songs']} songs, {stats['unused_songs']} unused[/dim]\n")
    
    # Get 12 songs
    songs = picker.get_available_songs(num_songs=12)
    
    if len(songs) < 12:
        console.print(f"[yellow]⚠️  Only {len(songs)} songs available in database[/yellow]\n")
    
    console.print("[magenta]📋 Next 12 songs:[/magenta]")
    for i, song in enumerate(songs, 1):
        status = "unused" if song['use_count'] == 1 else f"{song['use_count']}x"
        console.print(f"  {i:2}. {song['song_title']:<45} ({status})")
    
    console.print()
    response = input("Run these Nova jobs? (Y/n): ").strip().lower()
    if response == 'n':
        console.print("Cancelled.")
        return
    
    console.print()
    
    # Monkey-patch the input function to auto-provide song titles
    song_index = [0]  # Use list to avoid closure issues
    
    # Handle both builtins module and __builtins__ dict
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
            # For any other prompts (shouldn't happen with cached songs)
            return original_input(prompt)
    
    # Replace input function
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
    
    console.print(f"\n[bold magenta]━━━ Summary ━━━[/bold magenta]")
    console.print(f"Completed: {successful}/{num_jobs}")
    console.print(f"Time: {elapsed:.1f}s")
    
    if successful == num_jobs:
        console.print(f"\n[green]✅ All Nova jobs ready![/green]")
        console.print("[magenta]Next step:[/magenta] Run the After Effects JSX script")
        console.print("[dim]File → Scripts → Run Script File... → scripts/JSX/automateMV_nova.jsx[/dim]\n")


if __name__ == "__main__":
    main()