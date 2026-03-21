"""
Tests for scripts/audio_processing.py

Covers:
  - URL validation (valid, empty, 'unknown', malformed)
  - mmss_to_milliseconds conversion
  - trim_audio: happy path, start >= end guard, missing source file
  - download_audio: skips download when file already exists
  - download_audio: raises ValueError for premium / invalid URLs
"""
from __future__ import annotations

import os
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.audio_processing import (
    _validate_youtube_url,
    mmss_to_milliseconds,
    trim_audio,
    download_audio,
)


# ===========================================================================
# _validate_youtube_url
# ===========================================================================

class TestValidateYouTubeUrl:
    def test_valid_watch_url(self):
        # Should not raise
        _validate_youtube_url("https://www.youtube.com/watch?v=JGwWNGJdvx8")

    def test_valid_short_url(self):
        _validate_youtube_url("https://youtu.be/JGwWNGJdvx8")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="No YouTube URL"):
            _validate_youtube_url("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="No YouTube URL"):
            _validate_youtube_url("   ")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="No YouTube URL"):
            _validate_youtube_url(None)

    def test_unknown_placeholder_raises(self):
        with pytest.raises(ValueError, match="placeholder"):
            _validate_youtube_url("unknown")

    def test_unknown_case_insensitive(self):
        with pytest.raises(ValueError, match="placeholder"):
            _validate_youtube_url("UNKNOWN")

    def test_non_youtube_url_raises(self):
        with pytest.raises(ValueError, match="not a valid YouTube"):
            _validate_youtube_url("https://www.spotify.com/track/abc123")

    def test_watch_url_with_extra_params(self):
        # Extra query params should still be valid
        _validate_youtube_url(
            "https://www.youtube.com/watch?v=JGwWNGJdvx8&list=PL123&index=1"
        )


# ===========================================================================
# mmss_to_milliseconds
# ===========================================================================

class TestMmssToMilliseconds:
    def test_zero(self):
        assert mmss_to_milliseconds("00:00") == 0

    def test_one_minute(self):
        assert mmss_to_milliseconds("01:00") == 60_000

    def test_one_minute_thirty(self):
        assert mmss_to_milliseconds("01:30") == 90_000

    def test_ten_minutes(self):
        assert mmss_to_milliseconds("10:00") == 600_000

    def test_two_thirty(self):
        assert mmss_to_milliseconds("02:30") == 150_000

    def test_invalid_format_raises(self):
        with pytest.raises(Exception):
            mmss_to_milliseconds("90")

    def test_three_part_raises(self):
        with pytest.raises(Exception):
            mmss_to_milliseconds("01:02:03")

    def test_non_numeric_raises(self):
        with pytest.raises(Exception):
            mmss_to_milliseconds("ab:cd")


# ===========================================================================
# trim_audio
# ===========================================================================

class TestTrimAudio:
    def _write_mp3(self, job_folder: Path, duration_ms: int = 5000) -> Path:
        """Create a real silent MP3 using pydub so trim_audio can open it."""
        from pydub import AudioSegment
        path = job_folder / "audio_source.mp3"
        AudioSegment.silent(duration=duration_ms).export(str(path), format="mp3")
        return path

    def test_produces_wav_output(self, job_folder: Path):
        self._write_mp3(job_folder, duration_ms=10_000)
        result = trim_audio(str(job_folder), "00:00", "00:03")
        assert result is not None
        assert os.path.exists(result)
        assert result.endswith(".wav")

    def test_wav_duration_matches_trim(self, job_folder: Path):
        self._write_mp3(job_folder, duration_ms=10_000)
        trim_audio(str(job_folder), "00:00", "00:03")
        from pydub import AudioSegment
        trimmed = AudioSegment.from_file(str(job_folder / "audio_trimmed.wav"))
        # Allow ±200 ms tolerance for codec rounding
        assert abs(len(trimmed) - 3000) <= 200

    def test_returns_none_when_source_missing(self, job_folder: Path):
        # No audio_source.mp3 in job_folder
        result = trim_audio(str(job_folder), "00:00", "00:03")
        assert result is None

    def test_start_equals_end_returns_none(self, job_folder: Path):
        self._write_mp3(job_folder, duration_ms=5000)
        result = trim_audio(str(job_folder), "00:03", "00:03")
        assert result is None

    def test_start_after_end_returns_none(self, job_folder: Path):
        self._write_mp3(job_folder, duration_ms=5000)
        result = trim_audio(str(job_folder), "00:05", "00:02")
        assert result is None

    def test_non_zero_start_offset(self, job_folder: Path):
        """Trimming from 00:02 to 00:04 should yield a ~2s clip."""
        self._write_mp3(job_folder, duration_ms=10_000)
        trim_audio(str(job_folder), "00:02", "00:04")
        from pydub import AudioSegment
        trimmed = AudioSegment.from_file(str(job_folder / "audio_trimmed.wav"))
        assert abs(len(trimmed) - 2000) <= 200


# ===========================================================================
# download_audio — cache-hit path (no real network call)
# ===========================================================================

class TestDownloadAudioCacheHit:
    def test_skips_download_when_mp3_exists(self, job_folder: Path):
        """If audio_source.mp3 already exists, download_audio must return early."""
        mp3_path = job_folder / "audio_source.mp3"
        mp3_path.write_bytes(b"fake mp3 content")

        # yt_dlp is imported lazily inside download_audio — mock at module level
        mock_yt = MagicMock()
        with patch.dict("sys.modules", {"yt_dlp": mock_yt}):
            result = download_audio(
                "https://www.youtube.com/watch?v=JGwWNGJdvx8",
                str(job_folder),
            )

        assert result == str(mp3_path)
        mock_yt.YoutubeDL.assert_not_called()


# ===========================================================================
# download_audio — error path (no real network call)
# ===========================================================================

class TestDownloadAudioErrors:
    def test_premium_url_raises_value_error(self, job_folder: Path):
        """A 'music premium' download error should surface as a user-friendly ValueError."""
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_instance.download.side_effect = Exception(
            "This video is only available to Music Premium members"
        )

        # yt_dlp is imported lazily inside download_audio
        mock_yt = MagicMock()
        mock_yt.YoutubeDL.return_value = mock_ydl_instance
        with patch.dict("sys.modules", {"yt_dlp": mock_yt}):
            with pytest.raises(ValueError, match="Premium"):
                download_audio(
                    "https://www.youtube.com/watch?v=JGwWNGJdvx8",
                    str(job_folder),
                    max_retries=1,
                )

    def test_invalid_url_raises_before_network(self, job_folder: Path):
        with pytest.raises(ValueError, match="not a valid YouTube"):
            download_audio("https://spotify.com/invalid", str(job_folder))
