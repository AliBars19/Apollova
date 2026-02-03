import sqlite3
import random
from datetime import datetime

class SmartSongPicker:
    """Intelligently picks songs from database based on usage patterns"""
    
    def __init__(self, db_path="database/songs.db"):
        self.db_path = db_path
    
    def get_available_songs(self, num_songs=12):
        """
        Get top songs that haven't been used yet, or least recently used if all have been used
        
        Returns list of dicts with song info, sorted by:
        1. Never used songs first
        2. Then by least use_count
        3. Then by oldest last_used
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # First check total songs in database
        cursor.execute("SELECT COUNT(*) FROM songs")
        total_songs = cursor.fetchone()[0]
        
        if total_songs == 0:
            conn.close()
            return []
        
        # Check if we have any unused songs
        cursor.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1")
        unused_count = cursor.fetchone()[0]
        
        if unused_count >= num_songs:
            # We have enough unused songs - prioritize these
            cursor.execute("""
                SELECT id, song_title, youtube_url, start_time, end_time, use_count
                FROM songs
                WHERE use_count = 1
                ORDER BY RANDOM()
                LIMIT ?
            """, (num_songs,))
        else:
            # Mix of unused and least used songs
            cursor.execute("""
                SELECT id, song_title, youtube_url, start_time, end_time, use_count
                FROM songs
                ORDER BY 
                    CASE WHEN use_count = 1 THEN 0 ELSE 1 END,  -- Unused first
                    use_count ASC,                               -- Then by least used
                    last_used ASC,                               -- Then by oldest
                    RANDOM()                                     -- Random tiebreaker
                LIMIT ?
            """, (num_songs,))
        
        rows = cursor.fetchall()
        conn.close()
        
        songs = []
        for row in rows:
            songs.append({
                "id": row[0],
                "song_title": row[1],
                "youtube_url": row[2],
                "start_time": row[3],
                "end_time": row[4],
                "use_count": row[5]
            })
        
        return songs
    
    def pick_song(self):
        """
        Pick a single song intelligently
        Returns dict with song info or None if no songs available
        """
        songs = self.get_available_songs(num_songs=1)
        return songs[0] if songs else None
    
    def get_database_stats(self):
        """Get statistics about song usage in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM songs")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1")
        unused = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(use_count), MAX(use_count), AVG(use_count) FROM songs")
        min_uses, max_uses, avg_uses = cursor.fetchone()
        
        conn.close()
        
        return {
            "total_songs": total,
            "unused_songs": unused,
            "min_uses": min_uses or 0,
            "max_uses": max_uses or 0,
            "avg_uses": round(avg_uses, 2) if avg_uses else 0
        }
    
    def mark_song_used(self, song_title):
        """Update song usage statistics when used"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE songs 
            SET last_used = CURRENT_TIMESTAMP,
                use_count = use_count + 1
            WHERE LOWER(song_title) = LOWER(?)
        """, (song_title,))
        
        conn.commit()
        conn.close()
    
    def check_all_songs_used_once(self):
        """
        Check if all songs have been used at least twice (meaning full rotation complete)
        Returns True if we can start reusing songs
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1")
        unused_count = cursor.fetchone()[0]
        
        conn.close()
        
        return unused_count == 0
    
    def get_song_ranking_preview(self, num_songs=20):
        """
        Show preview of which songs would be picked next
        Useful for debugging/testing
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT song_title, use_count, last_used
            FROM songs
            ORDER BY 
                CASE WHEN use_count = 1 THEN 0 ELSE 1 END,
                use_count ASC,
                last_used ASC
            LIMIT ?
        """, (num_songs,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [(row[0], row[1], row[2]) for row in rows]


def demo_smart_picker():
    """Demo/test the smart picker"""
    picker = SmartSongPicker()
    
    # Show stats
    stats = picker.get_database_stats()
    print("📊 Database Stats:")
    print(f"   Total songs: {stats['total_songs']}")
    print(f"   Unused songs: {stats['unused_songs']}")
    print(f"   Min uses: {stats['min_uses']}")
    print(f"   Max uses: {stats['max_uses']}")
    print(f"   Avg uses: {stats['avg_uses']}")
    print()
    
    # Show what would be picked
    print("🎵 Next 12 songs that would be picked:")
    songs = picker.get_available_songs(num_songs=12)
    for i, song in enumerate(songs, 1):
        print(f"   {i}. {song['song_title']} (used {song['use_count']} times)")
    print()
    
    # Pick one
    song = picker.pick_song()
    if song:
        print(f"✅ Smart pick selected: {song['song_title']}")
    else:
        print("❌ No songs available in database")


if __name__ == "__main__":
    demo_smart_picker()