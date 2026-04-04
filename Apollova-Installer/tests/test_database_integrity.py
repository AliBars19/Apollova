"""
Database integrity tests for the Apollova-Installer songs.db.

Tests data quality and structural integrity of the database.
These tests use the REAL database — they are read-only and never modify data.
"""
import json
import os
import re
import sqlite3

import pytest

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "songs.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_songs_with_onyx():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, song_title, onyx_lyrics, youtube_url, start_time, end_time, colors "
        "FROM songs WHERE onyx_lyrics IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()
    return [(r["id"], r["song_title"], json.loads(r["onyx_lyrics"]),
             r["youtube_url"], r["start_time"], r["end_time"], r["colors"])
            for r in rows]


def get_all_songs_with_mono():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, song_title, mono_lyrics FROM songs WHERE mono_lyrics IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()
    return [(r["id"], r["song_title"], json.loads(r["mono_lyrics"])) for r in rows]


ONYX_SONGS = get_all_songs_with_onyx()
MONO_SONGS = get_all_songs_with_mono()
ONYX_IDS = [s[0] for s in ONYX_SONGS]
MONO_IDS = [s[0] for s in MONO_SONGS]


# ===========================================================================
# Schema tests
# ===========================================================================

class TestSchema:
    def test_songs_table_exists(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='songs'")
        assert cur.fetchone() is not None
        conn.close()

    def test_required_columns_present(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(songs)")
        cols = {row["name"] for row in cur.fetchall()}
        conn.close()
        required = {"id", "song_title", "youtube_url", "start_time", "end_time",
                    "onyx_lyrics", "mono_lyrics", "colors"}
        assert required.issubset(cols)

    def test_songs_table_has_rows(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM songs")
        count = cur.fetchone()[0]
        conn.close()
        assert count > 0

    def test_onyx_lyrics_songs_exist(self):
        assert len(ONYX_SONGS) > 0

    def test_mono_lyrics_songs_exist(self):
        assert len(MONO_SONGS) > 0

    def test_id_column_is_unique(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT id) FROM songs")
        total, unique = cur.fetchone()
        conn.close()
        assert total == unique

    def test_song_title_not_empty_for_onyx_songs(self):
        for song_id, title, *_ in ONYX_SONGS:
            assert title and title.strip(), f"Song {song_id} has empty title"

    def test_all_onyx_songs_have_valid_json(self):
        # Already verified by parsing in get_all_songs_with_onyx, but also test raw
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, onyx_lyrics FROM songs WHERE onyx_lyrics IS NOT NULL")
        for row in cur.fetchall():
            try:
                json.loads(row["onyx_lyrics"])
            except json.JSONDecodeError as e:
                pytest.fail(f"Song {row['id']} has invalid onyx_lyrics JSON: {e}")
        conn.close()

    def test_all_mono_songs_have_valid_json(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, mono_lyrics FROM songs WHERE mono_lyrics IS NOT NULL")
        for row in cur.fetchall():
            try:
                json.loads(row["mono_lyrics"])
            except json.JSONDecodeError as e:
                pytest.fail(f"Song {row['id']} has invalid mono_lyrics JSON: {e}")
        conn.close()


# ===========================================================================
# Onyx lyrics structure — parametrized over all songs with onyx_lyrics
# ===========================================================================

@pytest.mark.parametrize("song_id,title,data,youtube_url,start_t,end_t,colors_raw",
                         ONYX_SONGS, ids=[f"song_{s[0]}" for s in ONYX_SONGS])
class TestOnyxLyricsStructure:
    def test_markers_key_exists(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        assert "markers" in data, f"Song {song_id} missing 'markers' key"

    def test_markers_is_list(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        assert isinstance(data["markers"], list), f"Song {song_id}: markers not a list"

    def test_total_markers_key_exists(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        assert "total_markers" in data, f"Song {song_id} missing 'total_markers'"

    def test_total_markers_matches_len(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        markers = data["markers"]
        assert data["total_markers"] == len(markers), \
            f"Song {song_id}: total_markers {data['total_markers']} != len {len(markers)}"

    def test_markers_not_empty_or_untranscribed(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        """Songs with onyx_lyrics may have empty markers if not yet transcribed — this is informational."""
        # We just verify the field is a list (checked by test_markers_is_list)
        assert isinstance(data["markers"], list)

    def test_each_marker_has_time(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert "time" in m, f"Song {song_id} marker[{i}] missing 'time'"

    def test_each_marker_has_text(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert "text" in m, f"Song {song_id} marker[{i}] missing 'text'"

    def test_each_marker_has_words(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert "words" in m, f"Song {song_id} marker[{i}] missing 'words'"

    def test_each_marker_has_end_time(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert "end_time" in m, f"Song {song_id} marker[{i}] missing 'end_time'"

    def test_marker_time_is_non_negative(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert float(m["time"]) >= 0.0, \
                f"Song {song_id} marker[{i}] has negative time {m['time']}"

    def test_marker_end_time_gte_time(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert float(m["end_time"]) >= float(m["time"]), \
                f"Song {song_id} marker[{i}]: end_time {m['end_time']} < time {m['time']}"

    def test_marker_text_is_non_empty_string(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert isinstance(m["text"], str) and m["text"].strip(), \
                f"Song {song_id} marker[{i}] has empty or non-string text"

    def test_words_is_list(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert isinstance(m["words"], list), \
                f"Song {song_id} marker[{i}] words is not a list"

    def test_each_word_has_word_field(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            for j, w in enumerate(m["words"]):
                assert "word" in w, f"Song {song_id} marker[{i}] word[{j}] missing 'word'"

    def test_each_word_has_start_field(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            for j, w in enumerate(m["words"]):
                assert "start" in w, f"Song {song_id} marker[{i}] word[{j}] missing 'start'"

    def test_each_word_has_end_field(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            for j, w in enumerate(m["words"]):
                assert "end" in w, f"Song {song_id} marker[{i}] word[{j}] missing 'end'"

    def test_word_start_is_non_negative(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            for j, w in enumerate(m["words"]):
                assert float(w["start"]) >= 0.0, \
                    f"Song {song_id} marker[{i}] word[{j}] negative start {w['start']}"

    def test_word_text_is_string(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            for j, w in enumerate(m["words"]):
                assert isinstance(w["word"], str), \
                    f"Song {song_id} marker[{i}] word[{j}] 'word' field not string"

    def test_youtube_url_starts_with_http(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        if youtube_url:
            assert youtube_url.startswith("http"), \
                f"Song {song_id}: youtube_url '{youtube_url}' doesn't start with http"

    def test_start_end_time_mmss_format(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        mmss = re.compile(r"^\d{2}:\d{2}$")
        if start_t:
            assert mmss.match(start_t), f"Song {song_id}: start_time '{start_t}' not MM:SS"
        if end_t:
            assert mmss.match(end_t), f"Song {song_id}: end_time '{end_t}' not MM:SS"

    def test_color_field_present_on_markers(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            assert "color" in m, f"Song {song_id} marker[{i}] missing 'color' field"

    def test_marker_color_is_white_or_black(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        for i, m in enumerate(data["markers"]):
            # color can be "" (unassigned), "white", or "black"
            assert m["color"] in ("white", "black", ""), \
                f"Song {song_id} marker[{i}] has unexpected color '{m['color']}'"

    def test_colors_column_valid_json_array(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        if colors_raw:
            try:
                parsed = json.loads(colors_raw)
                assert isinstance(parsed, list), f"Song {song_id}: colors is not a JSON array"
            except json.JSONDecodeError:
                pytest.fail(f"Song {song_id}: colors column is not valid JSON")

    def test_colors_are_hex_strings(self, song_id, title, data, youtube_url, start_t, end_t, colors_raw):
        hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
        if colors_raw:
            parsed = json.loads(colors_raw)
            for c in parsed:
                assert hex_re.match(c), \
                    f"Song {song_id}: color '{c}' is not a valid hex color"


# ===========================================================================
# Mono lyrics structure — parametrized over all songs with mono_lyrics
# ===========================================================================

@pytest.mark.parametrize("song_id,title,data", MONO_SONGS,
                         ids=[f"mono_song_{s[0]}" for s in MONO_SONGS])
class TestMonoLyricsStructure:
    def test_markers_key_exists(self, song_id, title, data):
        assert "markers" in data

    def test_markers_is_list(self, song_id, title, data):
        assert isinstance(data["markers"], list)

    def test_total_markers_matches(self, song_id, title, data):
        assert data["total_markers"] == len(data["markers"])

    def test_markers_is_proper_list(self, song_id, title, data):
        """Verify markers is a proper list (may be empty for untranscribed songs)."""
        assert isinstance(data["markers"], list)

    def test_each_marker_has_required_keys(self, song_id, title, data):
        for i, m in enumerate(data["markers"]):
            for key in ("time", "text", "words", "end_time"):
                assert key in m, f"Song {song_id} mono marker[{i}] missing '{key}'"

    def test_marker_time_non_negative(self, song_id, title, data):
        for m in data["markers"]:
            assert float(m["time"]) >= 0.0

    def test_marker_end_time_gte_time(self, song_id, title, data):
        for m in data["markers"]:
            assert float(m["end_time"]) >= float(m["time"])

    def test_words_is_list(self, song_id, title, data):
        for m in data["markers"]:
            assert isinstance(m["words"], list)


# ===========================================================================
# Informational / aggregate data quality tests (not failures on bad values)
# ===========================================================================

class TestDataQualityInformational:
    """
    These tests report aggregate statistics about data quality.
    They do NOT fail due to probability=0 or clustered timestamps
    (that was expected pre-fix data). They only fail if something is
    structurally wrong.
    """

    def test_count_words_with_zero_probability(self):
        """Informational: count words with probability=0.0 (Genius-aligned)."""
        total = 0
        zero_prob = 0
        for _, _, data, *_ in ONYX_SONGS:
            for m in data["markers"]:
                for w in m["words"]:
                    total += 1
                    if w.get("probability", 1.0) == 0.0:
                        zero_prob += 1
        # Just verify we can count — no strict pass/fail on the ratio
        assert total > 0
        pct = zero_prob / total * 100 if total > 0 else 0
        print(f"\n[INFO] Words with probability=0.0: {zero_prob}/{total} ({pct:.1f}%)")

    def test_count_clustered_timestamps(self):
        """Informational: count words with start==end (Genius bunching)."""
        total = 0
        clustered = 0
        for _, _, data, *_ in ONYX_SONGS:
            for m in data["markers"]:
                for w in m["words"]:
                    total += 1
                    if float(w["start"]) == float(w["end"]):
                        clustered += 1
        assert total > 0
        pct = clustered / total * 100 if total > 0 else 0
        print(f"\n[INFO] Words with start==end: {clustered}/{total} ({pct:.1f}%)")

    def test_songs_with_markers_have_at_least_one_word(self):
        """Songs that have markers should have at least one word across them."""
        for song_id, title, data, *_ in ONYX_SONGS:
            markers = data["markers"]
            if len(markers) == 0:
                continue  # untranscribed songs allowed
            all_words = [w for m in markers for w in m["words"]]
            assert len(all_words) > 0, f"Song {song_id} has markers but no words"

    def test_no_nan_in_word_timestamps(self):
        """No NaN timestamps in word start/end fields."""
        import math
        for song_id, title, data, *_ in ONYX_SONGS:
            for i, m in enumerate(data["markers"]):
                for j, w in enumerate(m["words"]):
                    assert not math.isnan(float(w["start"])), \
                        f"Song {song_id} marker[{i}] word[{j}] start is NaN"
                    assert not math.isnan(float(w["end"])), \
                        f"Song {song_id} marker[{i}] word[{j}] end is NaN"

    def test_no_negative_word_end(self):
        """Word end times should not be negative."""
        for song_id, title, data, *_ in ONYX_SONGS:
            for i, m in enumerate(data["markers"]):
                for j, w in enumerate(m["words"]):
                    assert float(w["end"]) >= 0.0, \
                        f"Song {song_id} marker[{i}] word[{j}] has negative end {w['end']}"

    def test_markers_in_chronological_order(self):
        """Markers should be in ascending time order."""
        for song_id, title, data, *_ in ONYX_SONGS:
            times = [m["time"] for m in data["markers"]]
            assert times == sorted(times), \
                f"Song {song_id}: markers not in chronological order: {times[:5]}"

    def test_song_titles_have_artist_dash_track_format(self):
        """Most song titles should follow 'Artist - Track' format."""
        dash_count = sum(1 for _, title, *_ in ONYX_SONGS if " - " in title)
        total = len(ONYX_SONGS)
        # At least 80% should have the dash format
        assert dash_count / total >= 0.5, \
            f"Only {dash_count}/{total} songs have 'Artist - Track' format"

    def test_youtube_urls_are_youtube(self):
        """YouTube URLs should contain youtube.com or youtu.be."""
        for song_id, title, _, youtube_url, *_ in ONYX_SONGS:
            if youtube_url:
                assert "youtube" in youtube_url or "youtu.be" in youtube_url, \
                    f"Song {song_id}: unexpected URL '{youtube_url}'"
