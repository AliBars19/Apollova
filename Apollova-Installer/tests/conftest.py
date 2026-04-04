"""
Shared pytest fixtures and path configuration for the Apollova-Installer test suite.
"""
import sys
import os
import sqlite3
import json

import pytest

# Add installer root so 'assets.scripts' is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Add assets/ so 'scripts' can be imported directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "assets"))

# DB path — installer ships its own copy
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "songs.db")


@pytest.fixture
def db_songs_with_onyx():
    """Load all songs with onyx_lyrics from the real DB."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, song_title, onyx_lyrics FROM songs WHERE onyx_lyrics IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()
    return [(row_id, title, json.loads(lyrics)) for row_id, title, lyrics in rows]


@pytest.fixture
def db_songs_with_mono():
    """Load all songs with mono_lyrics from the real DB."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, song_title, mono_lyrics FROM songs WHERE mono_lyrics IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()
    return [(row_id, title, json.loads(lyrics)) for row_id, title, lyrics in rows]


@pytest.fixture
def sample_markers():
    """Minimal set of well-formed markers for unit tests."""
    return [
        {
            "time": 0.5,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "start": 0.5, "end": 0.9},
                {"word": "world", "start": 1.0, "end": 1.4},
            ],
            "color": "white",
            "end_time": 1.4,
        },
        {
            "time": 2.0,
            "text": "This is lyrics",
            "words": [
                {"word": "This", "start": 2.0, "end": 2.3},
                {"word": "is", "start": 2.4, "end": 2.6},
                {"word": "lyrics", "start": 2.7, "end": 3.1},
            ],
            "color": "black",
            "end_time": 3.1,
        },
    ]


@pytest.fixture
def clustered_markers():
    """Markers with Genius alignment bunching (words at same timestamp)."""
    return [
        {
            "time": 5.376,
            "text": "they all over me",
            "words": [
                {"word": "they", "start": 5.376, "end": 5.376, "probability": 0.0},
                {"word": "all", "start": 5.376, "end": 5.376, "probability": 0.0},
                {"word": "over", "start": 5.376, "end": 5.376, "probability": 0.0},
                {"word": "me", "start": 5.376, "end": 5.396, "probability": 0.085},
            ],
            "color": "white",
            "end_time": 5.396,
        },
    ]
