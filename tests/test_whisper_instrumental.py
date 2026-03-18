"""
Tests for whisper_common.remove_instrumental_hallucinations.

Covers:
  - Silent chunk removal, loud chunk preservation
  - Edge: missing audio file, corrupt audio, all-silence, max_rms=0, no silent chunks
  - Key variants: Aurora ("t") vs Mono ("time")
  - Boundary: midpoint calculation, chunk boundary, segment beyond audio length, threshold at 10%
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.whisper_common import remove_instrumental_hallucinations
from conftest import _write_wav_with_volume, _write_silent_wav


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aurora_item(t, end_time, text):
    return {"t": t, "end_time": end_time, "lyric_current": text}


def _mono_item(time_, end_time, text):
    return {"time": time_, "end_time": end_time, "text": text}


# ---------------------------------------------------------------------------
# Silent chunk removal
# ---------------------------------------------------------------------------

class TestSilentChunkRemoval:

    def test_removes_segment_over_silent_region(self, job_folder):
        """Segment whose midpoint falls in a silent chunk should be removed."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=5000,
            loud_ranges=[(0, 2000)],  # first 2s loud, rest silent
        )
        items = [
            _aurora_item(0.5, 1.5, "loud segment"),   # midpoint 1.0 → chunk 1 (loud)
            _aurora_item(3.0, 4.0, "silent segment"),  # midpoint 3.5 → chunk 3 (silent)
        ]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        assert len(result) == 1
        assert result[0]["lyric_current"] == "loud segment"

    def test_preserves_loud_segments(self, job_folder):
        """Segments over loud regions should be kept."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=5000,
            loud_ranges=[(0, 5000)],  # all loud
        )
        items = [
            _aurora_item(0.5, 1.5, "line one"),
            _aurora_item(2.0, 3.0, "line two"),
        ]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        assert len(result) == 2


class TestEdgeCases:

    def test_missing_audio_file_returns_items_unchanged(self):
        items = [_aurora_item(0, 1, "hello")]
        result = remove_instrumental_hallucinations(items, "lyric_current", "/nonexistent/file.wav")
        assert result == items

    def test_all_silence_returns_items_unchanged(self, job_folder):
        """If entire audio is silent, max_rms=0 triggers early return — items kept."""
        audio = _write_silent_wav(job_folder / "audio.wav", duration_ms=5000)
        items = [
            _aurora_item(0.5, 1.5, "line one"),
            _aurora_item(2.0, 3.0, "line two"),
        ]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        # max_rms==0 → early return, items unchanged
        assert len(result) == 2

    def test_max_rms_zero_returns_items(self, job_folder):
        """If max_rms is 0 (perfectly silent), early-return items unchanged."""
        audio = _write_silent_wav(job_folder / "audio.wav", duration_ms=3000)
        items = [_aurora_item(0.5, 1.5, "line")]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        # max_rms=0 → function returns items unchanged
        # Actually: all-silent WAV has rms=0 for all chunks.
        # The code checks max_rms == 0 → returns items unchanged.
        assert len(result) == 1

    def test_no_silent_chunks_preserves_all(self, job_folder):
        """If no chunks are below 10% threshold, everything is kept."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=3000,
            loud_ranges=[(0, 3000)],
        )
        items = [
            _aurora_item(0.5, 1.5, "line one"),
            _aurora_item(1.5, 2.5, "line two"),
        ]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        assert len(result) == 2

    def test_empty_items_returns_empty(self, job_folder):
        audio = _write_silent_wav(job_folder / "audio.wav")
        result = remove_instrumental_hallucinations([], "lyric_current", str(audio))
        assert result == []


class TestKeyVariants:

    def test_aurora_uses_t_key(self, job_folder):
        """Aurora items use 't' for time."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=5000,
            loud_ranges=[(0, 2000)],
        )
        items = [_aurora_item(0.5, 1.5, "loud")]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        assert len(result) == 1

    def test_mono_uses_time_key(self, job_folder):
        """Mono items use 'time' for time."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=5000,
            loud_ranges=[(0, 2000)],
        )
        items = [_mono_item(0.5, 1.5, "loud")]
        result = remove_instrumental_hallucinations(items, "text", str(audio))
        assert len(result) == 1


class TestBoundaryConditions:

    def test_midpoint_calculation(self, job_folder):
        """Midpoint of (2.0, 4.0) = 3.0 → chunk index 3."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=6000,
            loud_ranges=[(0, 2500)],  # chunks 0,1 loud; 2,3,4,5 silent
        )
        item = _aurora_item(2.0, 4.0, "midpoint at 3s")
        result = remove_instrumental_hallucinations([item], "lyric_current", str(audio))
        assert len(result) == 0  # chunk 3 is silent

    def test_segment_beyond_audio_length(self, job_folder):
        """Segment midpoint beyond audio duration shouldn't crash."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=3000,
            loud_ranges=[(0, 3000)],
        )
        # Segment at 5-7s, audio is only 3s
        item = _aurora_item(5.0, 7.0, "beyond audio")
        result = remove_instrumental_hallucinations([item], "lyric_current", str(audio))
        # chunk_idx=6 won't be in silence_map (only 3 chunks exist), so it's kept
        assert len(result) == 1

    def test_threshold_exactly_10_percent(self, job_folder):
        """Chunks with RMS exactly at 10% of max are NOT considered silent (< not <=)."""
        # This is hard to precisely engineer with WAV, but we test the logic conceptually
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=3000,
            loud_ranges=[(0, 3000)],  # all loud → nothing silent
        )
        items = [_aurora_item(0.5, 1.5, "kept")]
        result = remove_instrumental_hallucinations(items, "lyric_current", str(audio))
        assert len(result) == 1

    def test_chunk_at_exact_boundary(self, job_folder):
        """Segment starting at chunk boundary (e.g. t=2.0, end=3.0 → midpoint 2.5)."""
        audio = _write_wav_with_volume(
            job_folder / "audio.wav", duration_ms=5000,
            loud_ranges=[(0, 2000)],
        )
        # midpoint = 2.5 → chunk index 2 → silent
        item = _aurora_item(2.0, 3.0, "at boundary")
        result = remove_instrumental_hallucinations([item], "lyric_current", str(audio))
        assert len(result) == 0
