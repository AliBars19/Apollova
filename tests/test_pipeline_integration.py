"""
Full pipeline integration tests.

Tests complete end-to-end flows through:
  - Aurora pipeline (transcribe_audio): WAV -> cleanup -> JSON lyrics file
  - Mono pipeline (transcribe_audio_mono): WAV -> cleanup -> markers dict
  - Quality gate failure returning empty markers
  - Cache hit path (no re-transcription)

All Whisper model loading, Genius HTTP, and vocal separation are mocked.
Filesystem I/O (WAV reading, lyrics.txt writing) uses real tmp_path files.
"""
from __future__ import annotations

import json
import sys
import copy
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Make both scripts/ and upload/ importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "upload"))


# ---------------------------------------------------------------------------
# Shared mock setup helpers
# ---------------------------------------------------------------------------

def _mock_whisper_common_full(monkeypatch, *, segments_data=None):
    """
    Monkeypatch every external dependency inside scripts.whisper_common
    so no network or model loading occurs.

    segments_data: list of {text, start, end} dicts.  If None defaults to 4 lines.
    """
    from conftest import _make_whisper_result
    import scripts.whisper_common as wc

    if segments_data is None:
        segments_data = [
            {"text": "I'm in love with the shape of you", "start": 0.5,  "end": 3.2},
            {"text": "We push and pull like a magnet do",  "start": 3.4,  "end": 6.1},
            {"text": "Although my heart is falling too",   "start": 6.3,  "end": 8.8},
            {"text": "I'm in love with your body",          "start": 9.0,  "end": 11.5},
        ]

    fake_result = _make_whisper_result(segments_data)
    # Give the result .split_by_* methods for Onyx regrouping
    fake_result.split_by_gap = MagicMock(return_value=fake_result)
    fake_result.split_by_punctuation = MagicMock(return_value=fake_result)
    fake_result.split_by_length = MagicMock(return_value=fake_result)

    monkeypatch.setattr(wc, "get_audio_duration", lambda p: 15.0)
    monkeypatch.setattr(wc, "build_initial_prompt", lambda t: "prompt")
    monkeypatch.setattr(wc, "detect_language", lambda *a, **kw: "en")
    monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: None)
    monkeypatch.setattr(wc, "save_whisper_cache", lambda jf, s: None)
    monkeypatch.setattr(wc, "separate_vocals", lambda a, jf: a)
    monkeypatch.setattr(wc, "normalize_audio", lambda p: (p, 15.0))
    monkeypatch.setattr(wc, "reduce_noise", lambda p: p)
    monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (fake_result, 0))

    # Cleanup pipeline: pass-through (immutable — return new list)
    for fn_name in (
        "remove_hallucinations",
        "remove_junk",
        "remove_stutter_duplicates",
        "remove_repetition_loops",
        "remove_non_target_script",
    ):
        monkeypatch.setattr(wc, fn_name, lambda items, *a, **kw: list(items))

    def passthrough_instrumental(items, *a, **kw):
        return list(items)

    monkeypatch.setattr(wc, "remove_instrumental_hallucinations", passthrough_instrumental)

    monkeypatch.setattr(wc, "merge_short_markers", lambda m, **kw: list(m))
    monkeypatch.setattr(wc, "assign_colors", lambda m: None)
    monkeypatch.setattr(wc, "fix_marker_gaps", lambda m: None)
    monkeypatch.setattr(wc, "quality_gate", lambda m, d: (True, []))
    monkeypatch.setattr(wc, "rebuild_words_after_alignment", lambda m: m)

    return fake_result


# ---------------------------------------------------------------------------
# Aurora pipeline: transcribe_audio()
# ---------------------------------------------------------------------------

class TestAuroraPipelineIntegration:

    def test_produces_lyrics_txt_file(self, job_folder, silent_wav, monkeypatch):
        """Aurora pipeline must write a lyrics.txt file to job_folder on success."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder), "Ed Sheeran - Shape of You")

        assert result_path is not None
        lyrics_file = Path(result_path)
        assert lyrics_file.exists()
        assert lyrics_file.name == "lyrics.txt"

    def test_lyrics_txt_contains_valid_json(self, job_folder, silent_wav, monkeypatch):
        """lyrics.txt must contain a JSON array that can be parsed."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder), "Ed Sheeran - Shape of You")

        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        assert isinstance(segments, list)
        assert len(segments) > 0

    def test_output_segments_have_required_aurora_keys(self, job_folder, silent_wav, monkeypatch):
        """Every Aurora segment must carry: t, end_time, lyric_current, lyric_prev, lyric_next1, lyric_next2."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder), "Ed Sheeran - Shape of You")
        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        required_keys = {"t", "end_time", "lyric_current", "lyric_prev", "lyric_next1", "lyric_next2"}
        for seg in segments:
            missing = required_keys - seg.keys()
            assert not missing, f"Segment missing keys {missing}: {seg}"

    def test_lyric_prev_and_next_are_empty_strings(self, job_folder, silent_wav, monkeypatch):
        """Aurora format: lyric_prev, lyric_next1, lyric_next2 must always be empty strings."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder))
        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        for seg in segments:
            assert seg["lyric_prev"] == ""
            assert seg["lyric_next1"] == ""
            assert seg["lyric_next2"] == ""

    def test_returns_none_when_audio_missing(self, job_folder, monkeypatch):
        """Aurora pipeline must return None when audio_trimmed.wav is absent."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result = transcribe_audio(str(job_folder))
        assert result is None

    def test_returns_none_when_no_segments(self, job_folder, silent_wav, monkeypatch):
        """Aurora pipeline must return None when Whisper yields no segments."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch, segments_data=[])

        # Override multi_pass_transcribe to return empty result
        empty = MagicMock()
        empty.segments = []
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (empty, 0))
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result = transcribe_audio(str(job_folder))
        assert result is None

    def test_cache_hit_skips_transcription(self, job_folder, silent_wav, monkeypatch):
        """When whisper_raw.json cache exists, multi_pass_transcribe must NOT be called."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        cached_segs = [
            {"start": 0.5, "end": 3.2, "text": "Cached lyric line one"},
            {"start": 3.4, "end": 6.1, "text": "Cached lyric line two"},
        ]
        monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: cached_segs)

        transcribe_spy = MagicMock()
        monkeypatch.setattr(wc, "multi_pass_transcribe", transcribe_spy)

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder), "Test Artist - Test Song")
        transcribe_spy.assert_not_called()
        assert result_path is not None

    def test_genius_alignment_applied_when_token_present(self, job_folder, silent_wav, monkeypatch):
        """When GENIUS_API_TOKEN is set, Genius text must be fetched and alignment attempted."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "fake_token")

        align_called = []

        # Aurora imports fetch_genius_lyrics at module level
        monkeypatch.setattr(
            "scripts.lyric_processing.fetch_genius_lyrics",
            lambda t: "I'm in love with the shape of you\n",
        )
        monkeypatch.setattr(
            "scripts.lyric_processing.align_genius_to_whisper",
            lambda segs, text, **kw: (align_called.append(True), (segs, 0.9))[1],
        )

        from scripts.lyric_processing import transcribe_audio

        transcribe_audio(str(job_folder), "Ed Sheeran - Shape of You")
        assert len(align_called) == 1

    def test_genius_alignment_reverted_below_match_threshold(self, job_folder, silent_wav, monkeypatch):
        """When match_ratio < 0.3, Whisper segments must be preserved, not Genius text."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "fake_token")

        monkeypatch.setattr(
            "scripts.lyric_processing.fetch_genius_lyrics",
            lambda t: "completely wrong lyrics text that should be rejected",
        )

        def bad_align(segs, text, **kw):
            corrupted = [dict(s, lyric_current="WRONG") for s in segs]
            return corrupted, 0.1  # ratio below 0.3 threshold

        monkeypatch.setattr("scripts.lyric_processing.align_genius_to_whisper", bad_align)

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder), "Ed Sheeran - Shape of You")
        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        for seg in segments:
            assert seg["lyric_current"] != "WRONG", "Reverted segments must not contain Genius-replaced text"


# ---------------------------------------------------------------------------
# Mono pipeline: transcribe_audio_mono()
# ---------------------------------------------------------------------------

class TestMonoPipelineIntegration:

    def test_returns_markers_dict_with_expected_keys(self, job_folder, silent_wav, monkeypatch):
        """Mono pipeline must return a dict with 'markers' and 'total_markers'."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")

        assert isinstance(result, dict)
        assert "markers" in result
        assert "total_markers" in result

    def test_markers_have_word_level_timing(self, job_folder, silent_wav, monkeypatch):
        """Every Mono marker must contain a 'words' array with timing entries."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")

        assert result["total_markers"] > 0
        for marker in result["markers"]:
            assert "words" in marker
            assert isinstance(marker["words"], list)
            assert len(marker["words"]) > 0, f"Marker has no words: {marker}"

    def test_each_word_entry_has_start_end(self, job_folder, silent_wav, monkeypatch):
        """Word entries must carry start, end, and word keys."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")

        for marker in result["markers"]:
            for word in marker["words"]:
                assert "word" in word
                assert "start" in word
                assert "end" in word
                assert isinstance(word["start"], float)
                assert isinstance(word["end"], float)

    def test_word_timestamps_are_chronological(self, job_folder, silent_wav, monkeypatch):
        """Word start times within a marker must be non-decreasing."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")

        for marker in result["markers"]:
            words = marker["words"]
            for i in range(1, len(words)):
                assert words[i]["start"] >= words[i - 1]["start"], (
                    f"Non-chronological word timestamps in marker: {marker['text']}"
                )

    def test_empty_markers_when_audio_missing(self, job_folder, monkeypatch):
        """Mono pipeline must return empty markers when audio_trimmed.wav is absent."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        assert result["markers"] == []
        assert result["total_markers"] == 0

    def test_empty_markers_when_no_segments(self, job_folder, silent_wav, monkeypatch):
        """Mono pipeline must return empty markers when Whisper returns no segments."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch, segments_data=[])

        empty = MagicMock()
        empty.segments = []
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (empty, 0))
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        assert result["total_markers"] == 0

    def test_no_words_lost_across_all_markers(self, job_folder, silent_wav, monkeypatch):
        """
        The total number of words across all marker 'words' arrays must be >= the
        total number of words across all marker 'text' fields.
        """
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")

        text_word_count = sum(len(m["text"].split()) for m in result["markers"])
        array_word_count = sum(len(m["words"]) for m in result["markers"])

        assert array_word_count >= text_word_count, (
            f"Word entries ({array_word_count}) < text words ({text_word_count})"
        )

    def test_cache_hit_skips_transcription(self, job_folder, silent_wav, monkeypatch):
        """Mono pipeline must use cached Whisper data and skip model inference."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        cached_segs = [
            {"text": "Cached line one", "start": 0.0, "end": 2.5, "words": [
                {"word": "Cached", "start": 0.0, "end": 0.5},
                {"word": "line",   "start": 0.5, "end": 1.0},
                {"word": "one",    "start": 1.0, "end": 2.5},
            ]},
        ]
        monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: cached_segs)

        transcribe_spy = MagicMock()
        monkeypatch.setattr(wc, "multi_pass_transcribe", transcribe_spy)

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        transcribe_spy.assert_not_called()
        assert result["total_markers"] == 1

    def test_genius_alignment_applied_when_token_present(self, job_folder, silent_wav, monkeypatch):
        """Mono pipeline must attempt Genius alignment when token is configured."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "fake_token")

        align_called = []
        # fetch_genius_lyrics is deferred-imported inside whisper_common.transcribe_word_level
        monkeypatch.setattr(
            "scripts.genius_processing.fetch_genius_lyrics",
            lambda t: "I'm in love with the shape of you\n",
        )
        monkeypatch.setattr(
            "scripts.lyric_alignment.align_genius_to_whisper",
            lambda m, t, **kw: (align_called.append(True), (m, 0.9))[1],
        )

        import scripts.whisper_common as wc
        monkeypatch.setattr(wc, "rebuild_words_after_alignment", lambda m: m)

        from scripts.lyric_processing_mono import transcribe_audio_mono

        transcribe_audio_mono(str(job_folder), "Ed Sheeran - Shape of You")
        assert len(align_called) == 1


# ---------------------------------------------------------------------------
# Quality gate failure
# ---------------------------------------------------------------------------

class TestQualityGateIntegration:

    def test_mono_quality_gate_failure_still_returns_markers(self, job_folder, silent_wav, monkeypatch):
        """Quality gate failure emits a warning but does not suppress the result."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")
        monkeypatch.setattr(wc, "quality_gate", lambda m, d: (False, ["Coverage too low: 10%"]))

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        # Markers returned despite gate failure
        assert result["total_markers"] > 0

    def test_aurora_quality_gate_failure_still_writes_file(self, job_folder, silent_wav, monkeypatch):
        """Aurora pipeline writes lyrics.txt even when quality gate fails."""
        import scripts.whisper_common as wc
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        # Patch to emit a low quality warning on stdout (Aurora does its own quality check)
        monkeypatch.setattr(wc, "get_audio_duration", lambda p: 120.0)  # long clip
        # With only 4 segments for 120s, Aurora prints a warning but still writes the file

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder))
        assert result_path is not None
        assert Path(result_path).exists()


# ---------------------------------------------------------------------------
# Cross-pipeline invariants
# ---------------------------------------------------------------------------

class TestCrossPipelineInvariants:

    def test_aurora_segments_count_matches_total(self, job_folder, silent_wav, monkeypatch):
        """Segment count in lyrics.txt must match len() of the JSON array."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder))
        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        assert len(segments) > 0
        # Every item is a dict (not None, not a nested list)
        for seg in segments:
            assert isinstance(seg, dict)

    def test_mono_total_markers_matches_list_length(self, job_folder, silent_wav, monkeypatch):
        """total_markers must equal len(markers) in the returned dict."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        assert result["total_markers"] == len(result["markers"])

    def test_aurora_timing_values_are_numeric(self, job_folder, silent_wav, monkeypatch):
        """Aurora t and end_time must be numeric (int or float)."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing import transcribe_audio

        result_path = transcribe_audio(str(job_folder))
        with open(result_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        for seg in segments:
            assert isinstance(seg["t"], (int, float))
            assert isinstance(seg["end_time"], (int, float))

    def test_mono_marker_time_is_less_than_end_time(self, job_folder, silent_wav, monkeypatch):
        """Each Mono marker's time must be strictly less than end_time."""
        _mock_whisper_common_full(monkeypatch)
        monkeypatch.setattr("scripts.config.Config.GENIUS_API_TOKEN", "")

        from scripts.lyric_processing_mono import transcribe_audio_mono

        result = transcribe_audio_mono(str(job_folder))
        for marker in result["markers"]:
            assert marker["time"] < marker["end_time"], (
                f"time ({marker['time']}) not < end_time ({marker['end_time']}) in {marker}"
            )
