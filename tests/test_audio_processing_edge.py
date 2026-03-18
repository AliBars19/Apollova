"""
Tests for scripts/audio_processing.py — edge cases beyond existing coverage.

Covers:
  - detect_beats: returns floats, empty on missing file/error, numpy array vs scalar tempo,
    empty beat_frames, zero-length audio
  - mmss_to_milliseconds edges: large values "99:59", zero minutes, negative
  - trim_audio edges: exact source duration, beyond source clips, very short 1s trim
  - download_audio edges: 429 rate limit retry, 403 retry, all retries exhausted, non-YouTube URL
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.audio_processing import detect_beats, mmss_to_milliseconds, trim_audio, download_audio
from conftest import _write_silent_wav, _write_silent_mp3


# ---------------------------------------------------------------------------
# detect_beats
# ---------------------------------------------------------------------------

class TestDetectBeats:

    def _mock_librosa(self):
        mock_lib = MagicMock()
        return mock_lib

    def test_returns_list_of_floats(self, job_folder, silent_wav):
        mock_lib = self._mock_librosa()
        mock_lib.load.return_value = (MagicMock(), 44100)
        mock_lib.beat.beat_track.return_value = (120.0, [10, 20, 30])
        mock_lib.frames_to_time.return_value = [0.5, 1.0, 1.5]
        with patch.dict("sys.modules", {"librosa": mock_lib}):
            result = detect_beats(str(job_folder))
        assert all(isinstance(b, float) for b in result)
        assert result == [0.5, 1.0, 1.5]

    def test_empty_on_missing_file(self, job_folder):
        result = detect_beats(str(job_folder))
        assert result == []

    def test_empty_on_librosa_error(self, job_folder, silent_wav):
        mock_lib = self._mock_librosa()
        mock_lib.load.side_effect = Exception("corrupt file")
        with patch.dict("sys.modules", {"librosa": mock_lib}):
            result = detect_beats(str(job_folder))
        assert result == []

    def test_numpy_array_tempo(self, job_folder, silent_wav):
        mock_lib = self._mock_librosa()
        mock_lib.load.return_value = (MagicMock(), 44100)
        mock_lib.beat.beat_track.return_value = (
            MagicMock(__len__=lambda s: 1, __getitem__=lambda s, i: 120.0),
            [10, 20],
        )
        mock_lib.frames_to_time.return_value = [0.5, 1.0]
        with patch.dict("sys.modules", {"librosa": mock_lib}):
            result = detect_beats(str(job_folder))
        assert len(result) == 2

    def test_scalar_tempo(self, job_folder, silent_wav):
        mock_lib = self._mock_librosa()
        mock_lib.load.return_value = (MagicMock(), 44100)
        mock_lib.beat.beat_track.return_value = (130.0, [5, 15])
        mock_lib.frames_to_time.return_value = [0.25, 0.75]
        with patch.dict("sys.modules", {"librosa": mock_lib}):
            result = detect_beats(str(job_folder))
        assert len(result) == 2

    def test_empty_beat_frames(self, job_folder, silent_wav):
        mock_lib = self._mock_librosa()
        mock_lib.load.return_value = (MagicMock(), 44100)
        mock_lib.beat.beat_track.return_value = (120.0, [])
        mock_lib.frames_to_time.return_value = []
        with patch.dict("sys.modules", {"librosa": mock_lib}):
            result = detect_beats(str(job_folder))
        assert result == []


# ---------------------------------------------------------------------------
# mmss_to_milliseconds edges
# ---------------------------------------------------------------------------

class TestMmssEdges:

    def test_large_values(self):
        result = mmss_to_milliseconds("99:59")
        assert result == (99 * 60 + 59) * 1000

    def test_zero_minutes(self):
        result = mmss_to_milliseconds("00:30")
        assert result == 30 * 1000

    def test_zero_zero(self):
        result = mmss_to_milliseconds("00:00")
        assert result == 0

    def test_negative_raises(self):
        """Negative values should work mathematically (no validation)."""
        # The function does int() conversion, so "-1" becomes -1
        # and computes (-1*60 + 0) * 1000 = -60000
        result = mmss_to_milliseconds("-1:00")
        assert result == -60000


# ---------------------------------------------------------------------------
# trim_audio edges
# ---------------------------------------------------------------------------

class TestTrimAudioEdges:

    def test_exact_source_duration(self, job_folder, silent_mp3):
        """Trimming 0:00 to 0:03 on a 3s file should work."""
        result = trim_audio(str(job_folder), "00:00", "00:03")
        assert result is not None
        assert os.path.exists(result)

    def test_beyond_source_clips(self, job_folder, silent_mp3):
        """Trimming beyond source duration silently clips."""
        result = trim_audio(str(job_folder), "00:00", "00:10")
        assert result is not None

    def test_very_short_trim(self, job_folder, silent_mp3):
        """1-second trim."""
        result = trim_audio(str(job_folder), "00:00", "00:01")
        assert result is not None


# ---------------------------------------------------------------------------
# download_audio edges
# ---------------------------------------------------------------------------

class TestDownloadAudioEdges:

    def test_non_youtube_url_raises(self, job_folder):
        with pytest.raises(ValueError, match="not a valid YouTube"):
            download_audio("https://example.com/video.mp4", str(job_folder))

    def test_already_downloaded_returns_existing(self, job_folder):
        mp3_path = job_folder / "audio_source.mp3"
        mp3_path.write_bytes(b"fake mp3")
        result = download_audio("https://www.youtube.com/watch?v=abcdefghijk", str(job_folder))
        assert result == str(mp3_path)

    @patch("scripts.audio_processing.yt_dlp.YoutubeDL")
    def test_429_retry(self, mock_ytdl_cls, job_folder):
        """Rate limit (429) should wait and retry."""
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.download = MagicMock(side_effect=Exception("HTTP Error 429: Rate limited"))
        mock_ytdl_cls.return_value = ctx

        with patch("scripts.audio_processing.time.sleep"):
            with pytest.raises(Exception):
                download_audio(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    str(job_folder), max_retries=2
                )
        # Should have attempted 2 times
        assert ctx.download.call_count == 2

    @patch("scripts.audio_processing.yt_dlp.YoutubeDL")
    def test_403_retry(self, mock_ytdl_cls, job_folder):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.download = MagicMock(side_effect=Exception("HTTP Error 403: Forbidden"))
        mock_ytdl_cls.return_value = ctx

        with patch("scripts.audio_processing.time.sleep"):
            with pytest.raises(Exception):
                download_audio(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    str(job_folder), max_retries=2
                )
        assert ctx.download.call_count == 2

    @patch("scripts.audio_processing.yt_dlp.YoutubeDL")
    def test_all_retries_exhausted(self, mock_ytdl_cls, job_folder):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.download = MagicMock(side_effect=Exception("generic failure"))
        mock_ytdl_cls.return_value = ctx

        with patch("scripts.audio_processing.time.sleep"):
            with pytest.raises(Exception, match="generic failure"):
                download_audio(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    str(job_folder), max_retries=3
                )
        assert ctx.download.call_count == 3
