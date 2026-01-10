import sys
from rich.console import Console
from rich.table import Table
from scripts.song_database import SongDatabase

console = Console()
db = SongDatabase()


def show_all_songs():
    songs = db.list_all_songs()
    
    if not songs:
        console.print("[yellow]Database is empty[/yellow]")
        return
    
    table = Table(title="Cached Songs")
    table.add_column("Song Title", style="cyan", no_wrap=False)
    table.add_column("Uses", justify="right", style="green")
    table.add_column("Last Used", style="dim")
    
    for title, use_count, last_used in songs:
        table.add_row(title, str(use_count), last_used)
    
    console.print(table)


def show_stats():
    stats = db.get_stats()
    
    console.print("\n[bold cyan] Database Statistics[/bold cyan]\n")
    console.print(f"  Total songs: [green]{stats['total_songs']}[/green]")
    console.print(f"  Songs with cached lyrics: [green]{stats['cached_lyrics']}[/green]")
    console.print(f"  Total uses: [green]{stats['total_uses']}[/green]")
    
    if stats['total_songs'] > 0:
        cache_percentage = (stats['cached_lyrics'] / stats['total_songs']) * 100
        console.print(f"  Lyrics cache rate: [green]{cache_percentage:.1f}%[/green]")


def search_song(query):
    results = db.search_songs(query)
    
    if not results:
        console.print(f"[yellow]No songs found matching '{query}'[/yellow]")
        return
    
    table = Table(title=f"Search Results: '{query}'")
    table.add_column("Song Title", style="cyan")
    table.add_column("YouTube URL", style="blue", no_wrap=False)
    table.add_column("Uses", justify="right")
    
    for title, url, use_count in results:
        # Truncate long URLs
        url_short = url[:50] + "..." if len(url) > 50 else url
        table.add_row(title, url_short, str(use_count))
    
    console.print(table)


def show_song_details(song_title):
    song = db.get_song(song_title)
    
    if not song:
        console.print(f"[red]Song '{song_title}' not found in database[/red]")
        return
    
    console.print(f"\n[bold cyan] {song_title}[/bold cyan]\n")
    console.print(f"  YouTube URL: [blue]{song['youtube_url']}[/blue]")
    console.print(f"  Timing: [green]{song['start_time']} → {song['end_time']}[/green]")
    
    if song['genius_image_url']:
        console.print(f"  Image URL: [blue]{song['genius_image_url'][:60]}...[/blue]")
    
    if song['transcribed_lyrics']:
        console.print(f"  Cached lyrics: [green]{len(song['transcribed_lyrics'])} segments ⚡[/green]")
    else:
        console.print(f"  Cached lyrics: [yellow]None[/yellow]")
    
    if song['colors']:
        colors_str = ", ".join(song['colors'])
        console.print(f"  Colors: {colors_str}")
    
    if song['beats']:
        console.print(f"  Beats: [green]{len(song['beats'])} detected[/green]")


def main():
    if len(sys.argv) < 2:
        console.print("\n[bold]Database Manager[/bold]\n")
        console.print("Usage:")
        console.print("  python db_manager.py list          - Show all songs")
        console.print("  python db_manager.py stats         - Show statistics")
        console.print("  python db_manager.py search QUERY  - Search for songs")
        console.print("  python db_manager.py show \"TITLE\"  - Show song details")
        console.print("\nExamples:")
        console.print("  python db_manager.py search drake")
        console.print("  python db_manager.py show \"Drake - God's Plan\"")
        return
    
    command = sys.argv[1].lower()
    
    if command == "list":
        show_all_songs()
    
    elif command == "stats":
        show_stats()
    
    elif command == "search":
        if len(sys.argv) < 3:
            console.print("[red]Please provide a search query[/red]")
            return
        query = " ".join(sys.argv[2:])
        search_song(query)
    
    elif command == "show":
        if len(sys.argv) < 3:
            console.print("[red]Please provide a song title[/red]")
            return
        song_title = " ".join(sys.argv[2:])
        show_song_details(song_title)
    
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print("Use: list, stats, search, or show")


if __name__ == "__main__":
    main()