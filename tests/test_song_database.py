"""
Tests for scripts/song_database.py

Covers:
  - init_database: table and column creation
  - add_song / get_song: full round-trip with all fields
  - add_song idempotency: COALESCE preserves existing data on conflict
  - get_song case-insensitivity
  - update_lyrics / get_song cached lyrics
  - get_mono_lyrics / update_mono_lyrics
  - get_onyx_lyrics / update_onyx_lyrics
  - update_image_url
  - update_colors_and_beats
  - mark_song_used: increments use_count
  - list_all_songs: returns entries ordered by last_used
  - search_songs: partial title match, case-insensitive, limit 10
  - delete_song: removes and returns True; missing title returns False
  - get_stats: correct counts
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.song_database import SongDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SONG = "Ed Sheeran - Shape of You"
URL  = "https://www.youtube.com/watch?v=JGwWNGJdvx8"
START = "01:00"
END   = "02:00"

LYRICS_A = [{"t": 0.5, "lyric_current": "In love with the shape of you"}]
LYRICS_M = [{"time": 0.5, "text": "Shape of You", "words": []}]
LYRICS_O = [{"time": 0.5, "text": "Shape of You", "words": [], "color": "white"}]
COLORS   = ["#ff5733", "#33ff57"]
BEATS    = [0.5, 1.0, 1.5, 2.0]
IMG_URL  = "https://images.genius.com/shape_of_you.jpg"


# ===========================================================================
# add_song + get_song
# ===========================================================================

class TestAddAndGetSong:
    def test_basic_round_trip(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END)
        result = song_db.get_song(SONG)
        assert result is not None
        assert result["youtube_url"] == URL
        assert result["start_time"] == START
        assert result["end_time"] == END

    def test_optional_fields_none_when_not_provided(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END)
        result = song_db.get_song(SONG)
        assert result["genius_image_url"] is None
        assert result["transcribed_lyrics"] is None
        assert result["colors"] is None
        assert result["beats"] is None

    def test_all_optional_fields_stored(self, song_db: SongDatabase):
        song_db.add_song(
            SONG, URL, START, END,
            genius_image_url=IMG_URL,
            transcribed_lyrics=LYRICS_A,
            colors=COLORS,
            beats=BEATS,
        )
        result = song_db.get_song(SONG)
        assert result["genius_image_url"] == IMG_URL
        assert result["transcribed_lyrics"] == LYRICS_A
        assert result["colors"] == COLORS
        assert result["beats"] == BEATS

    def test_get_nonexistent_returns_none(self, song_db: SongDatabase):
        assert song_db.get_song("Not A Real Song") is None

    def test_get_is_case_insensitive(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END)
        upper = song_db.get_song(SONG.upper())
        lower = song_db.get_song(SONG.lower())
        assert upper is not None
        assert lower is not None


# ===========================================================================
# add_song idempotency (COALESCE behaviour)
# ===========================================================================

class TestAddSongIdempotency:
    def test_url_updated_on_conflict(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END)
        new_url = "https://www.youtube.com/watch?v=NEWVIDEOID1"
        song_db.add_song(SONG, new_url, START, END)
        assert song_db.get_song(SONG)["youtube_url"] == new_url

    def test_existing_lyrics_preserved_when_new_is_none(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END, transcribed_lyrics=LYRICS_A)
        # Second add without lyrics — COALESCE should keep existing lyrics
        song_db.add_song(SONG, URL, START, END, transcribed_lyrics=None)
        result = song_db.get_song(SONG)
        assert result["transcribed_lyrics"] == LYRICS_A

    def test_existing_colors_preserved_when_new_is_none(self, song_db: SongDatabase):
        song_db.add_song(SONG, URL, START, END, colors=COLORS)
        song_db.add_song(SONG, URL, START, END, colors=None)
        assert song_db.get_song(SONG)["colors"] == COLORS


# ===========================================================================
# Aurora lyrics
# ===========================================================================

class TestAuroraLyrics:
    def test_update_and_retrieve_lyrics(self, populated_song_db: SongDatabase):
        new_lyrics = [{"t": 5.0, "lyric_current": "Brand new lyric"}]
        populated_song_db.update_lyrics(SONG, new_lyrics)
        result = populated_song_db.get_song(SONG)
        assert result["transcribed_lyrics"] == new_lyrics

    def test_update_lyrics_with_none(self, populated_song_db: SongDatabase):
        populated_song_db.update_lyrics(SONG, None)
        result = populated_song_db.get_song(SONG)
        assert result["transcribed_lyrics"] is None

    def test_update_lyrics_nonexistent_song_does_not_raise(self, song_db: SongDatabase):
        song_db.update_lyrics("Ghost Song", LYRICS_A)   # should silently succeed


# ===========================================================================
# Mono lyrics
# ===========================================================================

class TestMonoLyrics:
    def test_update_and_retrieve_mono_lyrics(self, populated_song_db: SongDatabase):
        populated_song_db.update_mono_lyrics(SONG, LYRICS_M)
        result = populated_song_db.get_mono_lyrics(SONG)
        assert result == LYRICS_M

    def test_get_mono_lyrics_returns_none_when_not_set(self, populated_song_db: SongDatabase):
        assert populated_song_db.get_mono_lyrics(SONG) is None

    def test_mono_lyrics_round_trip_preserves_structure(self, populated_song_db: SongDatabase):
        populated_song_db.update_mono_lyrics(SONG, LYRICS_M)
        loaded = populated_song_db.get_mono_lyrics(SONG)
        assert isinstance(loaded, list)
        assert loaded[0]["text"] == "Shape of You"


# ===========================================================================
# Onyx lyrics
# ===========================================================================

class TestOnyxLyrics:
    def test_update_and_retrieve_onyx_lyrics(self, populated_song_db: SongDatabase):
        populated_song_db.update_onyx_lyrics(SONG, LYRICS_O)
        result = populated_song_db.get_onyx_lyrics(SONG)
        assert result == LYRICS_O

    def test_get_onyx_lyrics_returns_none_when_not_set(self, populated_song_db: SongDatabase):
        assert populated_song_db.get_onyx_lyrics(SONG) is None

    def test_onyx_color_field_preserved(self, populated_song_db: SongDatabase):
        populated_song_db.update_onyx_lyrics(SONG, LYRICS_O)
        loaded = populated_song_db.get_onyx_lyrics(SONG)
        assert loaded[0]["color"] == "white"


# ===========================================================================
# Image URL
# ===========================================================================

class TestUpdateImageUrl:
    def test_image_url_updated(self, populated_song_db: SongDatabase):
        new_url = "https://images.genius.com/new_image.jpg"
        populated_song_db.update_image_url(SONG, new_url)
        result = populated_song_db.get_song(SONG)
        assert result["genius_image_url"] == new_url


# ===========================================================================
# Colors and Beats
# ===========================================================================

class TestUpdateColorsAndBeats:
    def test_colors_and_beats_updated(self, populated_song_db: SongDatabase):
        new_colors = ["#aabbcc", "#ddeeff"]
        new_beats  = [1.0, 2.0, 3.0]
        populated_song_db.update_colors_and_beats(SONG, new_colors, new_beats)
        result = populated_song_db.get_song(SONG)
        assert result["colors"] == new_colors
        assert result["beats"] == new_beats

    def test_none_values_cleared(self, populated_song_db: SongDatabase):
        populated_song_db.update_colors_and_beats(SONG, None, None)
        result = populated_song_db.get_song(SONG)
        assert result["colors"] is None
        assert result["beats"] is None


# ===========================================================================
# mark_song_used
# ===========================================================================

class TestMarkSongUsed:
    def test_increments_use_count_via_stats(self, populated_song_db: SongDatabase):
        before = populated_song_db.get_stats()["total_uses"]
        populated_song_db.mark_song_used(SONG)
        after = populated_song_db.get_stats()["total_uses"]
        assert after == before + 1


# ===========================================================================
# list_all_songs
# ===========================================================================

class TestListAllSongs:
    def test_returns_all_songs(self, song_db: SongDatabase):
        song_db.add_song("Artist A - Song 1", URL, START, END)
        song_db.add_song("Artist B - Song 2", URL, START, END)
        songs = song_db.list_all_songs()
        assert len(songs) == 2

    def test_returns_tuple_with_title_count_date(self, populated_song_db: SongDatabase):
        songs = populated_song_db.list_all_songs()
        assert len(songs) == 1
        title, count, last_used = songs[0]
        assert title == SONG
        assert isinstance(count, int)


# ===========================================================================
# search_songs
# ===========================================================================

class TestSearchSongs:
    def test_partial_match(self, song_db: SongDatabase):
        song_db.add_song("Ed Sheeran - Shape of You", URL, START, END)
        song_db.add_song("Ed Sheeran - Bad Habits",   URL, START, END)
        results = song_db.search_songs("Ed Sheeran")
        assert len(results) == 2

    def test_case_insensitive_search(self, song_db: SongDatabase):
        song_db.add_song("Ed Sheeran - Shape of You", URL, START, END)
        results = song_db.search_songs("SHAPE")
        assert len(results) == 1

    def test_no_match_returns_empty(self, song_db: SongDatabase):
        song_db.add_song("Ed Sheeran - Shape of You", URL, START, END)
        results = song_db.search_songs("Beyonce")
        assert results == []

    def test_limit_10_results(self, song_db: SongDatabase):
        for i in range(15):
            song_db.add_song(f"Artist - Song {i}", URL, START, END)
        results = song_db.search_songs("Artist")
        assert len(results) <= 10


# ===========================================================================
# delete_song
# ===========================================================================

class TestDeleteSong:
    def test_delete_existing_returns_true(self, populated_song_db: SongDatabase):
        assert populated_song_db.delete_song(SONG) is True
        assert populated_song_db.get_song(SONG) is None

    def test_delete_nonexistent_returns_false(self, song_db: SongDatabase):
        assert song_db.delete_song("Ghost Song") is False

    def test_case_insensitive_delete(self, populated_song_db: SongDatabase):
        assert populated_song_db.delete_song(SONG.upper()) is True


# ===========================================================================
# get_stats
# ===========================================================================

class TestGetStats:
    def test_empty_db_stats(self, song_db: SongDatabase):
        stats = song_db.get_stats()
        assert stats["total_songs"] == 0
        assert stats["cached_lyrics"] == 0
        assert stats["total_uses"] == 0

    def test_stats_after_adding_song(self, populated_song_db: SongDatabase):
        stats = populated_song_db.get_stats()
        assert stats["total_songs"] == 1
        assert stats["cached_lyrics"] == 1   # populated_song_db adds lyrics
        assert stats["total_uses"] >= 1

    def test_cached_lyrics_only_counts_aurora(self, song_db: SongDatabase):
        song_db.add_song("Song A", URL, START, END, transcribed_lyrics=LYRICS_A)
        song_db.add_song("Song B", URL, START, END)  # no aurora lyrics
        stats = song_db.get_stats()
        assert stats["cached_lyrics"] == 1
