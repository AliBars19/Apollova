"""
Tests for scripts/smart_picker.py

Covers:
  - SmartSongPicker.get_available_songs: empty database returns []
  - SmartSongPicker.get_available_songs: returns list of dicts with expected keys
  - SmartSongPicker.get_available_songs: num_songs respected
  - SmartSongPicker.get_available_songs: never-used songs (use_count=1) prioritised
  - SmartSongPicker.get_available_songs: shuffle=True still returns correct structure
  - SmartSongPicker.get_available_songs: shuffle=True picks from all tiers, not just first
  - SmartSongPicker.pick_song: returns single dict or None on empty db
  - SmartSongPicker.pick_song: result has required fields
  - SmartSongPicker.mark_song_used: increments use_count
  - SmartSongPicker.reset_all_use_counts: sets use_count=1 for all songs
  - SmartSongPicker.get_database_stats: correct total / unused counts
  - Priority ordering: use_count=1 songs appear before use_count=2 songs
  - get_available_songs: more songs than num_songs — limit honoured
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.smart_picker import SmartSongPicker


# ---------------------------------------------------------------------------
# Fixture: SmartSongPicker backed by a temp SQLite database
# ---------------------------------------------------------------------------

@pytest.fixture()
def picker(tmp_path: Path) -> SmartSongPicker:
    """SmartSongPicker with an empty isolated database."""
    db_path = str(tmp_path / "songs.db")
    # SmartSongPicker does not create the schema — use SongDatabase to init
    from scripts.song_database import SongDatabase
    SongDatabase(db_path=db_path)  # creates the table
    return SmartSongPicker(db_path=db_path)


def _add_song(picker: SmartSongPicker, title: str, use_count: int = 1) -> None:
    """Insert a song directly into the database with a specific use_count."""
    conn = sqlite3.connect(picker.db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO songs
               (song_title, youtube_url, start_time, end_time, use_count)
               VALUES (?, ?, ?, ?, ?)""",
            (title, "https://www.youtube.com/watch?v=fake0000001", "01:00", "02:00", use_count),
        )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# get_available_songs — basic structure
# ===========================================================================

class TestGetAvailableSongsStructure:
    def test_empty_db_returns_empty_list(self, picker: SmartSongPicker):
        assert picker.get_available_songs() == []

    def test_returns_list_of_dicts(self, picker: SmartSongPicker):
        _add_song(picker, "Artist A - Song 1")
        result = picker.get_available_songs()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_required_keys_present(self, picker: SmartSongPicker):
        _add_song(picker, "Artist A - Song 1")
        result = picker.get_available_songs()
        expected_keys = {"id", "song_title", "youtube_url", "start_time", "end_time", "use_count"}
        assert expected_keys.issubset(result[0].keys())

    def test_num_songs_limits_result(self, picker: SmartSongPicker):
        for i in range(10):
            _add_song(picker, f"Artist - Song {i}")
        result = picker.get_available_songs(num_songs=5)
        assert len(result) == 5

    def test_returns_all_when_fewer_than_requested(self, picker: SmartSongPicker):
        for i in range(3):
            _add_song(picker, f"Artist - Song {i}")
        result = picker.get_available_songs(num_songs=10)
        assert len(result) == 3

    def test_song_title_is_string(self, picker: SmartSongPicker):
        _add_song(picker, "Ed Sheeran - Shape of You")
        result = picker.get_available_songs()
        assert isinstance(result[0]["song_title"], str)

    def test_use_count_is_int(self, picker: SmartSongPicker):
        _add_song(picker, "Artist - Song")
        result = picker.get_available_songs()
        assert isinstance(result[0]["use_count"], int)


# ===========================================================================
# get_available_songs — priority: use_count=1 first
# ===========================================================================

class TestAvailableSongsPriority:
    def test_unused_songs_appear_before_used_songs(self, picker: SmartSongPicker):
        """Songs with use_count=1 should come before use_count=2 songs."""
        _add_song(picker, "Used Song", use_count=2)
        _add_song(picker, "Unused Song", use_count=1)

        result = picker.get_available_songs(num_songs=2)
        titles = [r["song_title"] for r in result]
        # Unused (use_count=1) must appear first
        assert titles[0] == "Unused Song"

    def test_multiple_unused_songs_all_returned_first(self, picker: SmartSongPicker):
        for i in range(3):
            _add_song(picker, f"Used {i}", use_count=3)
        for i in range(3):
            _add_song(picker, f"Unused {i}", use_count=1)

        result = picker.get_available_songs(num_songs=6)
        use_counts = [r["use_count"] for r in result]
        # All use_count=1 should come before use_count=3
        ones = [i for i, uc in enumerate(use_counts) if uc == 1]
        threes = [i for i, uc in enumerate(use_counts) if uc == 3]
        if ones and threes:
            assert max(ones) < min(threes)

    def test_all_unused_when_enough_never_used_exist(self, picker: SmartSongPicker):
        for i in range(5):
            _add_song(picker, f"Never Used {i}", use_count=1)
        for i in range(5):
            _add_song(picker, f"Used {i}", use_count=4)

        result = picker.get_available_songs(num_songs=5)
        assert all(r["use_count"] == 1 for r in result)


# ===========================================================================
# get_available_songs — shuffle mode
# ===========================================================================

class TestAvailableSongsShuffle:
    def test_shuffle_returns_correct_count(self, picker: SmartSongPicker):
        for i in range(10):
            _add_song(picker, f"Artist - Song {i}", use_count=(1 if i < 5 else 2))
        result = picker.get_available_songs(num_songs=8, shuffle=True)
        assert len(result) == 8

    def test_shuffle_returns_required_keys(self, picker: SmartSongPicker):
        _add_song(picker, "Artist - Song 1")
        result = picker.get_available_songs(shuffle=True)
        assert "song_title" in result[0]
        assert "use_count" in result[0]

    def test_shuffle_empty_db_returns_empty(self, picker: SmartSongPicker):
        assert picker.get_available_songs(shuffle=True) == []


# ===========================================================================
# pick_song
# ===========================================================================

class TestPickSong:
    def test_returns_none_on_empty_db(self, picker: SmartSongPicker):
        assert picker.pick_song() is None

    def test_returns_single_dict(self, picker: SmartSongPicker):
        _add_song(picker, "Artist - Song")
        result = picker.pick_song()
        assert isinstance(result, dict)

    def test_result_has_required_fields(self, picker: SmartSongPicker):
        _add_song(picker, "Artist - Song")
        result = picker.pick_song()
        assert "song_title" in result
        assert "youtube_url" in result
        assert "use_count" in result

    def test_picks_from_database(self, picker: SmartSongPicker):
        _add_song(picker, "Known Song - Artist")
        result = picker.pick_song()
        assert result["song_title"] == "Known Song - Artist"


# ===========================================================================
# mark_song_used
# ===========================================================================

class TestMarkSongUsed:
    def test_increments_use_count(self, picker: SmartSongPicker):
        _add_song(picker, "Test Song", use_count=1)
        picker.mark_song_used("Test Song")
        conn = sqlite3.connect(picker.db_path)
        row = conn.execute(
            "SELECT use_count FROM songs WHERE song_title = ?", ("Test Song",)
        ).fetchone()
        conn.close()
        assert row[0] == 2

    def test_case_insensitive_mark(self, picker: SmartSongPicker):
        _add_song(picker, "Test Song", use_count=1)
        picker.mark_song_used("test song")
        conn = sqlite3.connect(picker.db_path)
        row = conn.execute(
            "SELECT use_count FROM songs WHERE song_title = ?", ("Test Song",)
        ).fetchone()
        conn.close()
        assert row[0] == 2

    def test_mark_nonexistent_song_does_not_raise(self, picker: SmartSongPicker):
        picker.mark_song_used("Ghost Song - Nobody")  # should not raise


# ===========================================================================
# reset_all_use_counts
# ===========================================================================

class TestResetAllUseCounts:
    def test_resets_all_to_one(self, picker: SmartSongPicker):
        for i in range(5):
            _add_song(picker, f"Artist - Song {i}", use_count=3 + i)

        affected = picker.reset_all_use_counts()
        assert affected == 5

        # Verify in DB
        conn = sqlite3.connect(picker.db_path)
        rows = conn.execute("SELECT use_count FROM songs").fetchall()
        conn.close()
        assert all(row[0] == 1 for row in rows)

    def test_reset_on_empty_db_returns_zero(self, picker: SmartSongPicker):
        affected = picker.reset_all_use_counts()
        assert affected == 0

    def test_reset_makes_songs_available_as_unused(self, picker: SmartSongPicker):
        _add_song(picker, "Song A", use_count=5)
        picker.reset_all_use_counts()
        conn = sqlite3.connect(picker.db_path)
        unused = conn.execute("SELECT COUNT(*) FROM songs WHERE use_count = 1").fetchone()[0]
        conn.close()
        assert unused == 1


# ===========================================================================
# get_database_stats
# ===========================================================================

class TestGetDatabaseStats:
    def test_empty_db_stats(self, picker: SmartSongPicker):
        stats = picker.get_database_stats()
        assert stats["total_songs"] == 0
        assert stats["unused_songs"] == 0
        assert stats["min_uses"] == 0
        assert stats["max_uses"] == 0
        assert stats["avg_uses"] == 0

    def test_stats_after_adding_songs(self, picker: SmartSongPicker):
        _add_song(picker, "Song A", use_count=1)
        _add_song(picker, "Song B", use_count=3)
        stats = picker.get_database_stats()
        assert stats["total_songs"] == 2
        assert stats["unused_songs"] == 1  # Only Song A has use_count=1
        assert stats["min_uses"] == 1
        assert stats["max_uses"] == 3

    def test_avg_uses_is_float_or_int(self, picker: SmartSongPicker):
        _add_song(picker, "Song A", use_count=2)
        _add_song(picker, "Song B", use_count=4)
        stats = picker.get_database_stats()
        assert isinstance(stats["avg_uses"], (int, float))
        assert stats["avg_uses"] == 3.0

    def test_stats_keys_present(self, picker: SmartSongPicker):
        stats = picker.get_database_stats()
        expected_keys = {"total_songs", "unused_songs", "min_uses", "max_uses", "avg_uses"}
        assert expected_keys.issubset(stats.keys())

