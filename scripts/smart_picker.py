"""
Smart Song Picker - Intelligent song selection from database
Shared across Aurora, Mono, and Onyx templates

Priority system:
  1. Never-used songs first (use_count = 1)
  2. Least used songs (lowest use_count)
  3. Oldest last_used timestamp
  4. Random tiebreaker
"""
import sqlite3
import random
from datetime import datetime
from itertools import groupby


class SmartSongPicker:
    """Intelligently picks songs from database based on usage patterns"""

    def __init__(self, db_path="database/songs.db"):
        self.db_path = db_path

    def get_available_songs(self, num_songs=12, shuffle=False):
        """
        Get songs prioritized by:
        1. Never used songs first (use_count = 1)
        2. Then by least use_count
        3. Then by oldest last_used
        4. Random tiebreaker

        If shuffle=True, fetches a larger pool from each use_count tier
        and randomly selects from within each tier. This gives a fresh
        selection each call while still respecting the fair-rotation order.

        Returns list of dicts with song info
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM songs")
        total_songs = cursor.fetchone()[0]

        if total_songs == 0:
            conn.close()
            return []

        cursor.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1")
        unused_count = cursor.fetchone()[0]

        if unused_count >= num_songs:
            cursor.execute("""
                SELECT id, song_title, youtube_url, start_time, end_time, use_count
                FROM songs
                WHERE use_count = 1
                ORDER BY RANDOM()
                LIMIT ?
            """, (num_songs,))
            rows = cursor.fetchall()
        elif shuffle:
            cursor.execute("""
                SELECT id, song_title, youtube_url, start_time, end_time, use_count
                FROM songs
                ORDER BY
                    CASE WHEN use_count = 1 THEN 0 ELSE 1 END,
                    use_count ASC
            """)
            all_rows = cursor.fetchall()
            grouped = []
            for _key, group in groupby(all_rows, key=lambda r: r[5]):
                tier = list(group)
                random.shuffle(tier)
                grouped.extend(tier)
            rows = grouped[:num_songs]
        else:
            cursor.execute("""
                SELECT id, song_title, youtube_url, start_time, end_time, use_count
                FROM songs
                ORDER BY
                    CASE WHEN use_count = 1 THEN 0 ELSE 1 END,
                    use_count ASC,
                    last_used ASC,
                    RANDOM()
                LIMIT ?
            """, (num_songs,))
            rows = cursor.fetchall()

        conn.close()

        return [{
            "id": row[0],
            "song_title": row[1],
            "youtube_url": row[2],
            "start_time": row[3],
            "end_time": row[4],
            "use_count": row[5]
        } for row in rows]
    
    def pick_song(self):
        """Pick a single song intelligently"""
        songs = self.get_available_songs(num_songs=1)
        return songs[0] if songs else None
    
    def get_database_stats(self):
        """Get statistics about song usage"""
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
        """Update song usage when used"""
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
        """Check if all songs have been used (full rotation complete)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1")
        unused_count = cursor.fetchone()[0]

        conn.close()

        return unused_count == 0

    def reset_all_use_counts(self):
        """Reset all songs to unused (use_count = 1, last_used = NULL)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE songs SET use_count = 1, last_used = NULL")
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected

    def get_song_ranking_preview(self, num_songs=20):
        """Preview which songs would be picked next"""
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
