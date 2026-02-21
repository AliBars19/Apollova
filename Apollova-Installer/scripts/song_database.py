"""Song database for caching parameters and lyrics"""
import sqlite3
import json
import os
from datetime import datetime


class SongDatabase:
    """SQLite database for caching song parameters and transcriptions"""
    
    def __init__(self, db_path="database/songs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_title TEXT UNIQUE NOT NULL,
                youtube_url TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                genius_image_url TEXT,
                transcribed_lyrics TEXT,
                colors TEXT,
                beats TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                use_count INTEGER DEFAULT 1
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_song(self, song_title):
        """Get song parameters from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT youtube_url, start_time, end_time, genius_image_url, 
                   transcribed_lyrics, colors, beats
            FROM songs 
            WHERE LOWER(song_title) = LOWER(?)
        """, (song_title,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            "youtube_url": row[0],
            "start_time": row[1],
            "end_time": row[2],
            "genius_image_url": row[3],
            "transcribed_lyrics": json.loads(row[4]) if row[4] else None,
            "colors": json.loads(row[5]) if row[5] else None,
            "beats": json.loads(row[6]) if row[6] else None
        }
    
    def add_song(self, song_title, youtube_url, start_time, end_time, 
                 genius_image_url=None, transcribed_lyrics=None, colors=None, beats=None):
        """Add new song to database or update if exists"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        lyrics_json = json.dumps(transcribed_lyrics) if transcribed_lyrics else None
        colors_json = json.dumps(colors) if colors else None
        beats_json = json.dumps(beats) if beats else None
        
        cursor.execute("""
            INSERT INTO songs (song_title, youtube_url, start_time, end_time, 
                             genius_image_url, transcribed_lyrics, colors, beats)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(song_title) DO UPDATE SET
                youtube_url = excluded.youtube_url,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                genius_image_url = excluded.genius_image_url,
                transcribed_lyrics = excluded.transcribed_lyrics,
                colors = excluded.colors,
                beats = excluded.beats,
                last_used = CURRENT_TIMESTAMP,
                use_count = use_count + 1
        """, (song_title, youtube_url, start_time, end_time, 
              genius_image_url, lyrics_json, colors_json, beats_json))
        
        conn.commit()
        conn.close()
    
    def mark_song_used(self, song_title):
        """Mark a song as used"""
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
    
    def search_songs(self, query):
        """Search for songs by partial title match"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT song_title, youtube_url, use_count
            FROM songs 
            WHERE LOWER(song_title) LIKE LOWER(?)
            ORDER BY use_count DESC, last_used DESC
            LIMIT 10
        """, (f"%{query}%",))
        
        songs = cursor.fetchall()
        conn.close()
        
        return songs
    
    def get_stats(self):
        """Get database statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM songs")
        total_songs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM songs WHERE transcribed_lyrics IS NOT NULL")
        cached_lyrics = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(use_count) FROM songs")
        total_uses = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_songs": total_songs,
            "cached_lyrics": cached_lyrics,
            "total_uses": total_uses
        }
