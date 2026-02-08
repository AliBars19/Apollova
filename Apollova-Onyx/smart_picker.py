#!/usr/bin/env python3
"""
Smart Picker for Onyx - Auto-select 12 songs and run them
"""
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.smart_picker import SmartSongPicker
from scripts.song_database import SongDatabase
from main_onyx import process_single_job
from rich.console import Console

console = Console()

# Shared database path
SHARED_DB = Path(__file__).parent.parent / "database" / "songs.db"


def main():
    console.print("[bold magenta]💿 Onyx Smart Song Picker[/bold magenta]\n")
    
    picker = SmartSongPicker(db_path=str(SHARED_DB))
    stats = picker.get_database_stats()
    
    if stats['total_songs'] == 0:
        console.print("[red]❌ Database is empty. Add songs first using main_onyx.py[/red]")
        return
    
    console.print(f"[dim]📊 {stats['total_songs']} songs, {stats['unused_songs']} unused[/dim]\n")
    
    # Get 12 songs
    songs = picker.get_available_songs(num_songs=12)
    
    if len(songs) < 12:
        console.print(f"[yellow]⚠ Only {len(songs)} songs available in database[/yellow]\n")
    
    console.print("[cyan]📋 Next songs to process:[/cyan]")
    for i, song in enumerate(songs, 1):
        status = "unused" if song['use_count'] == 1 else f"{song['use_count']}x"
        console.print(f"  {i:2}. {song['song_title']:<45} ({status})")
    
    console.print()
    response = input(f"Run these {len(songs)} Onyx jobs? (Y/n): ").strip().lower()
    if response == 'n':
        console.print("Cancelled.")
        return
    
    console.print()
    
    # Monkey-patch the input function to auto-provide song titles
    song_index = [0]
    original_input = __builtins__.input
    
    def smart_input(prompt):
        if "Song Title" in prompt:
            song = songs[song_index[0]]
            song_index[0] += 1
            console.print(f"{prompt}{song['song_title']}")
            return song['song_title']
        else:
            return original_input(prompt)
    
    __builtins__.input = smart_input
    
    # Process jobs
    import time
    start = time.time()
    
    successful = 0
    for i in range(1, len(songs) + 1):
        try:
            if process_single_job(i):
                successful += 1
        except Exception as e:
            console.print(f"[red]Job {i} failed: {e}[/red]")
    
    elapsed = time.time() - start
    
    # Restore original input
    __builtins__.input = original_input
    
    console.print(f"\n[bold magenta]━━━ Onyx Summary ━━━[/bold magenta]")
    console.print(f"Completed: {successful}/{len(songs)}")
    console.print(f"Time: {elapsed:.1f}s")
    console.print(f"\n[cyan]Next:[/cyan] Run automateMV_onyx.jsx in After Effects\n")


if __name__ == "__main__":
    main()
