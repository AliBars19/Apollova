"""
Song Database - SQLite caching for song parameters and transcriptions
Shared across Aurora, Mono, and Onyx templates

Each template has its own lyrics column:
  - transcribed_lyrics  → Aurora (line-by-line segments)
  - mono_lyrics         → Mono (word-level markers)
  - onyx_lyrics         → Onyx (word-level markers + colors)
"""
import sqlite3
import json
import os
from pathlib import Path


class SongDatabase:
    """SQLite database for caching song parameters and transcriptions"""

    def __init__(self, db_path=None):
        if db_path is None:
            # Default: shared database one level up from scripts/
            db_path = str(Path(__file__).parent.parent / "database" / "songs.db")

        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()

    def init_database(self):
        """Create database tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
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
                    mono_lyrics TEXT,
                    onyx_lyrics TEXT,
                    colors TEXT,
                    beats TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    use_count INTEGER DEFAULT 1
                )
            """)

            # Add columns if they don't exist (for existing databases)
            _valid_new_columns = {"mono_lyrics", "onyx_lyrics"}
            for col in ["mono_lyrics", "onyx_lyrics"]:
                if col not in _valid_new_columns:
                    continue
                try:
                    cursor.execute(f"ALTER TABLE songs ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            conn.commit()

    # ========================================================================
    # CORE CRUD
    # ========================================================================

    def get_song(self, song_title):
        """Get song parameters from database (shared fields only)"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT youtube_url, start_time, end_time, genius_image_url,
                       transcribed_lyrics, colors, beats
                FROM songs
                WHERE LOWER(song_title) = LOWER(?)
            """, (song_title,))

            row = cursor.fetchone()

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
        finally:
            conn.close()

    def add_song(self, song_title, youtube_url, start_time, end_time,
                 genius_image_url=None, transcribed_lyrics=None, colors=None, beats=None):
        """Add new song or update existing (COALESCE preserves existing data)"""
        lyrics_json = json.dumps(transcribed_lyrics) if transcribed_lyrics is not None else None
        colors_json = json.dumps(colors) if colors is not None else None
        beats_json = json.dumps(beats) if beats is not None else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO songs (song_title, youtube_url, start_time, end_time,
                                 genius_image_url, transcribed_lyrics, colors, beats)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(song_title) DO UPDATE SET
                    youtube_url = excluded.youtube_url,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    genius_image_url = COALESCE(excluded.genius_image_url, genius_image_url),
                    transcribed_lyrics = COALESCE(excluded.transcribed_lyrics, transcribed_lyrics),
                    colors = COALESCE(excluded.colors, colors),
                    beats = COALESCE(excluded.beats, beats),
                    last_used = CURRENT_TIMESTAMP,
                    use_count = use_count + 1
            """, (song_title, youtube_url, start_time, end_time,
                  genius_image_url, lyrics_json, colors_json, beats_json))

            conn.commit()

    def mark_song_used(self, song_title):
        """Increment use_count and update last_used timestamp"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET last_used = CURRENT_TIMESTAMP,
                    use_count = use_count + 1
                WHERE LOWER(song_title) = LOWER(?)
            """, (song_title,))

            conn.commit()

    # ========================================================================
    # AURORA-SPECIFIC LYRICS
    # ========================================================================

    def update_lyrics(self, song_title, transcribed_lyrics):
        """Update Aurora transcribed_lyrics column"""
        lyrics_json = json.dumps(transcribed_lyrics) if transcribed_lyrics is not None else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET transcribed_lyrics = ?, last_used = CURRENT_TIMESTAMP
                WHERE LOWER(song_title) = LOWER(?)
            """, (lyrics_json, song_title))

            conn.commit()

    # ========================================================================
    # MONO-SPECIFIC LYRICS
    # ========================================================================

    def get_mono_lyrics(self, song_title):
        """Get Mono-format lyrics (word-level timestamps)"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT mono_lyrics FROM songs
                WHERE LOWER(song_title) = LOWER(?)
            """, (song_title,))

            row = cursor.fetchone()

            if not row or not row[0]:
                return None

            return json.loads(row[0])
        finally:
            conn.close()

    def update_mono_lyrics(self, song_title, mono_lyrics):
        """Update Mono-format lyrics"""
        lyrics_json = json.dumps(mono_lyrics) if mono_lyrics is not None else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET mono_lyrics = ?, last_used = CURRENT_TIMESTAMP
                WHERE LOWER(song_title) = LOWER(?)
            """, (lyrics_json, song_title))

            conn.commit()

    # ========================================================================
    # ONYX-SPECIFIC LYRICS
    # ========================================================================

    def get_onyx_lyrics(self, song_title):
        """Get Onyx-format lyrics (word-level timestamps + colors)"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT onyx_lyrics FROM songs
                WHERE LOWER(song_title) = LOWER(?)
            """, (song_title,))

            row = cursor.fetchone()

            if not row or not row[0]:
                return None

            return json.loads(row[0])
        finally:
            conn.close()

    def update_onyx_lyrics(self, song_title, onyx_lyrics):
        """Update Onyx-format lyrics"""
        lyrics_json = json.dumps(onyx_lyrics) if onyx_lyrics is not None else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET onyx_lyrics = ?, last_used = CURRENT_TIMESTAMP
                WHERE LOWER(song_title) = LOWER(?)
            """, (lyrics_json, song_title))

            conn.commit()

    # ========================================================================
    # SHARED FIELD UPDATES
    # ========================================================================

    def update_image_url(self, song_title, genius_image_url):
        """Update Genius image URL"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET genius_image_url = ?, last_used = CURRENT_TIMESTAMP
                WHERE LOWER(song_title) = LOWER(?)
            """, (genius_image_url, song_title))

            conn.commit()

    def update_colors_and_beats(self, song_title, colors, beats):
        """Update colors and beats"""
        colors_json = json.dumps(colors) if colors is not None else None
        beats_json = json.dumps(beats) if beats is not None else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE songs
                SET colors = ?, beats = ?, last_used = CURRENT_TIMESTAMP
                WHERE LOWER(song_title) = LOWER(?)
            """, (colors_json, beats_json, song_title))

            conn.commit()

    # ========================================================================
    # QUERIES
    # ========================================================================

    def list_all_songs(self):
        """Get list of all songs ordered by last used"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT song_title, use_count, last_used
                FROM songs
                ORDER BY last_used DESC
            """)

            return cursor.fetchall()
        finally:
            conn.close()

    def search_songs(self, query):
        """Search for songs by partial title match"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT song_title, youtube_url, use_count
                FROM songs
                WHERE LOWER(song_title) LIKE LOWER(?)
                ORDER BY use_count DESC, last_used DESC
                LIMIT 10
            """, (f"%{query}%",))

            return cursor.fetchall()
        finally:
            conn.close()

    def delete_song(self, song_title):
        """Delete a song from the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM songs
                WHERE LOWER(song_title) = LOWER(?)
            """, (song_title,))

            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def clear_all_lyrics(self):
        """Clear all cached lyrics (Aurora, Mono, Onyx) from every song"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE songs SET transcribed_lyrics = NULL, mono_lyrics = NULL, onyx_lyrics = NULL")
            affected = cursor.rowcount
            conn.commit()
            return affected

    def get_stats(self):
        """Get database statistics"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM songs")
            total_songs = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM songs WHERE transcribed_lyrics IS NOT NULL")
            cached_lyrics = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(use_count) FROM songs")
            total_uses = cursor.fetchone()[0] or 0

            return {
                "total_songs": total_songs,
                "cached_lyrics": cached_lyrics,
                "total_uses": total_uses
            }
        finally:
            conn.close()
