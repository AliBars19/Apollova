import os
import sys
from scripts.smart_picker import SmartSongPicker
from scripts.song_database import SongDatabase

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import process_single_job
from rich.console import Console

console = Console()

def main():
    console.print("[bold cyan]🤖 Smart Song Picker[/bold cyan]\n")
    
    picker = SmartSongPicker()
    stats = picker.get_database_stats()
    
    if stats['total_songs'] == 0:
        console.print("[red]❌ Database is empty. Add songs first.[/red]")
        return
    
    console.print(f"[dim]📊 {stats['total_songs']} songs, {stats['unused_songs']} unused[/dim]\n")
    
    # Get 12 songs
    songs = picker.get_available_songs(num_songs=12)
    
    console.print("[cyan]📋 Next 12 songs:[/cyan]")
    for i, song in enumerate(songs, 1):
        status = "unused" if song['use_count'] == 1 else f"{song['use_count']}x"
        console.print(f"  {i:2}. {song['song_title']:<45} ({status})")
    
    console.print()
    response = input("Run these 12 jobs? (Y/n): ").strip().lower()
    if response == 'n':
        console.print("Cancelled.")
        return
    
    console.print()
    
    # Monkey-patch the input function to auto-provide song titles
    song_index = [0]  # Use list to avoid closure issues
    
    original_input = __builtins__.input
    
    def smart_input(prompt):
        if "Song Title" in prompt:
            song = songs[song_index[0]]
            song_index[0] += 1
            console.print(f"{prompt}{song['song_title']}")
            return song['song_title']
        else:
            # For any other prompts (shouldn't happen with cached songs)
            return original_input(prompt)
    
    # Replace input function
    __builtins__.input = smart_input
    
    # Process 12 jobs
    import time
    start = time.time()
    
    successful = 0
    for i in range(1, 13):
        try:
            if process_single_job(i):
                successful += 1
        except Exception as e:
            console.print(f"[red]Job {i} failed: {e}[/red]")
    
    elapsed = time.time() - start
    
    # Restore original input
    __builtins__.input = original_input
    
    console.print(f"\n[bold cyan]━━━ Summary ━━━[/bold cyan]")
    console.print(f"Completed: {successful}/12")
    console.print(f"Time: {elapsed:.1f}s\n")

if __name__ == "__main__":
    main()