"""Tests for Whisper quality scoring."""
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock

sys.modules.setdefault("stable_whisper", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("pydub", MagicMock())
sys.modules.setdefault("pydub.AudioSegment", MagicMock())
sys.modules.setdefault("scripts.audio_processing", MagicMock())

import pytest

from scripts.whisper_common import compute_quality_score


class TestComputeQualityScore:
    def test_empty_markers(self):
        result = compute_quality_score([])
        assert result["coverage_pct"] == 0.0
        assert result["avg_prob"] == 0.0
        assert result["zero_time_words"] == 0

    def test_single_marker_full_coverage(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "hello", "words": [
            {"word": "hello", "start": 0.0, "end": 0.5, "probability": 0.95}
        ]}]
        result = compute_quality_score(markers)
        assert result["coverage_pct"] == 1.0
        assert result["avg_prob"] == 0.95

    def test_avg_prob_calculation(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "a b", "words": [
            {"word": "a", "start": 0.0, "end": 0.5, "probability": 0.8},
            {"word": "b", "start": 0.5, "end": 1.0, "probability": 0.6},
        ]}]
        result = compute_quality_score(markers)
        assert result["avg_prob"] == pytest.approx(0.7, abs=0.01)

    def test_zero_time_words_detected(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "a b", "words": [
            {"word": "a", "start": 0.0, "end": 0.0, "probability": 0.0},
            {"word": "b", "start": 0.5, "end": 1.0, "probability": 0.9},
        ]}]
        result = compute_quality_score(markers)
        assert result["zero_time_words"] == 1
        assert result["total_words"] == 2

    def test_no_probability_field(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "hello", "words": [
            {"word": "hello", "start": 0.0, "end": 0.5}
        ]}]
        result = compute_quality_score(markers)
        assert result["avg_prob"] == 0.0

    def test_multiple_markers_coverage(self):
        markers = [
            {"time": 0.0, "end_time": 2.0, "text": "a", "words": []},
            {"time": 5.0, "end_time": 7.0, "text": "b", "words": []},
        ]
        result = compute_quality_score(markers)
        # covered = 2 + 2 = 4, span = 7 - 0 = 7
        assert result["coverage_pct"] == pytest.approx(4 / 7, abs=0.01)

    def test_coverage_capped_at_1(self):
        # Overlapping markers could theoretically exceed 1.0
        markers = [
            {"time": 0.0, "end_time": 10.0, "text": "a", "words": []},
            {"time": 0.0, "end_time": 10.0, "text": "b", "words": []},
        ]
        result = compute_quality_score(markers)
        assert result["coverage_pct"] <= 1.0

    def test_all_zero_probability(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "a b c", "words": [
            {"word": "a", "start": 0.0, "end": 0.0, "probability": 0.0},
            {"word": "b", "start": 0.0, "end": 0.0, "probability": 0.0},
            {"word": "c", "start": 0.0, "end": 0.0, "probability": 0.0},
        ]}]
        result = compute_quality_score(markers)
        assert result["avg_prob"] == 0.0
        assert result["zero_time_words"] == 3

    def test_high_quality_transcription(self):
        markers = [
            {"time": 0.0, "end_time": 3.0, "text": "hello world", "words": [
                {"word": "hello", "start": 0.0, "end": 0.5, "probability": 0.98},
                {"word": "world", "start": 0.6, "end": 1.2, "probability": 0.95},
            ]},
            {"time": 3.5, "end_time": 6.0, "text": "goodbye", "words": [
                {"word": "goodbye", "start": 3.5, "end": 4.0, "probability": 0.92},
            ]},
        ]
        result = compute_quality_score(markers)
        assert result["avg_prob"] > 0.9
        assert result["zero_time_words"] == 0
        assert result["total_words"] == 3

    def test_words_without_end_field(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "test", "words": [
            {"word": "test", "start": 0.0}
        ]}]
        result = compute_quality_score(markers)
        # end defaults to 0, so end - start = 0 - 0 = 0 < MIN_WORD_DUR
        assert result["zero_time_words"] == 1

    def test_marker_without_words(self):
        markers = [{"time": 0.0, "end_time": 5.0, "text": "hello"}]
        result = compute_quality_score(markers)
        assert result["total_words"] == 0
        assert result["avg_prob"] == 0.0


# ============================================================================
# DATABASE QUALITY METHODS
# ============================================================================


class TestSongDatabaseQuality:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_songs.db")
        # Create minimal songs table
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_title TEXT UNIQUE NOT NULL,
            youtube_url TEXT NOT NULL DEFAULT '',
            start_time TEXT NOT NULL DEFAULT '00:00',
            end_time TEXT NOT NULL DEFAULT '00:40',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            use_count INTEGER DEFAULT 1
        )""")
        conn.execute("INSERT INTO songs (song_title) VALUES ('Test Song')")
        conn.execute("INSERT INTO songs (song_title) VALUES ('Good Song')")
        conn.execute("INSERT INTO songs (song_title) VALUES ('Bad Song')")
        conn.commit()
        conn.close()

    def _get_db(self):
        from scripts.song_database import SongDatabase
        return SongDatabase(db_path=self.db_path)

    def test_save_and_get_quality(self):
        db = self._get_db()
        db.save_whisper_quality("Test Song", 0.85, 0.72, 3, "medium")
        result = db.get_whisper_quality("Test Song")
        assert result is not None
        assert result["coverage_pct"] == 0.85
        assert result["avg_prob"] == 0.72
        assert result["zero_time_words"] == 3
        assert result["model"] == "medium"
        assert result["scored_at"] is not None

    def test_get_quality_nonexistent(self):
        db = self._get_db()
        result = db.get_whisper_quality("Nonexistent")
        assert result is None

    def test_get_quality_unscored(self):
        db = self._get_db()
        result = db.get_whisper_quality("Test Song")
        assert result is not None
        assert result["coverage_pct"] is None

    def test_get_low_quality_songs(self):
        db = self._get_db()
        db.save_whisper_quality("Good Song", 0.95, 0.88, 0, "medium")
        db.save_whisper_quality("Bad Song", 0.3, 0.2, 15, "small")
        low = db.get_low_quality_songs(min_coverage=0.5, min_avg_prob=0.3)
        assert len(low) == 1
        assert low[0]["song_title"] == "Bad Song"

    def test_get_low_quality_empty(self):
        db = self._get_db()
        low = db.get_low_quality_songs()
        assert low == []

    def test_save_quality_updates_existing(self):
        db = self._get_db()
        db.save_whisper_quality("Test Song", 0.5, 0.4, 10, "small")
        db.save_whisper_quality("Test Song", 0.9, 0.8, 2, "medium")
        result = db.get_whisper_quality("Test Song")
        assert result["coverage_pct"] == 0.9
        assert result["model"] == "medium"

    def test_ensure_quality_columns_idempotent(self):
        db = self._get_db()
        db._ensure_quality_columns()
        db._ensure_quality_columns()  # Should not throw
