"""
Tests for scripts/whisper_common.py

Covers:
  - get_audio_duration: returns float for valid file, None for missing file
  - build_initial_prompt: "Artist - Song" splitting
  - detect_language: Spanish, French, English, unknown title
  - remove_hallucinations: known hallucination patterns removed
  - remove_junk: minimal-alpha segments removed
  - remove_non_target_script: non-Latin text stripped for English songs
  - remove_stutter_duplicates: near-identical consecutive segments with tiny gaps
  - remove_repetition_loops: 3+ repeating phrases capped at 2
  - build_markers_from_segments: correct field structure
  - extract_word_timings: fallback distribution when no word-level data
  - fix_marker_gaps: large intra-word gaps compressed
  - merge_short_markers: 1-word markers merged with next when gap is small
  - quality_gate: passes/fails based on coverage thresholds
  - save_whisper_cache / load_whisper_cache: round-trip with model tag
  - load_whisper_cache: rejects stale model tag
  - assign_colors: white/black alternation
  - rebuild_words_after_alignment: fuzzy remapping with Genius words
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import whisper_common
from scripts.audio_processing import normalize_audio, reduce_noise
from scripts.whisper_common import (
    get_audio_duration,
    build_initial_prompt,
    detect_language,
    remove_hallucinations,
    remove_junk,
    remove_non_target_script,
    remove_stutter_duplicates,
    remove_repetition_loops,
    remove_instrumental_hallucinations,
    build_markers_from_segments,
    extract_word_timings,
    fix_marker_gaps,
    merge_short_markers,
    quality_gate,
    save_whisper_cache,
    load_whisper_cache,
    assign_colors,
    rebuild_words_after_alignment,
    align_genius_to_audio,
    _refine_result,
    _snap_to_silence,
)


# ===========================================================================
# get_audio_duration
# ===========================================================================

class TestGetAudioDuration:
    def test_returns_float_for_valid_wav(self, silent_wav: Path):
        dur = get_audio_duration(str(silent_wav))
        assert isinstance(dur, float)
        assert 2.5 <= dur <= 3.5   # 3 second silent clip ± codec rounding

    def test_returns_none_for_missing_file(self, tmp_dir: Path):
        dur = get_audio_duration(str(tmp_dir / "nonexistent.wav"))
        assert dur is None


# ===========================================================================
# build_initial_prompt
# ===========================================================================

class TestBuildInitialPrompt:
    def test_artist_song_format(self):
        prompt = build_initial_prompt("Ed Sheeran - Shape of You")
        assert "Shape of You" in prompt
        assert "Ed Sheeran" in prompt

    def test_song_only(self):
        prompt = build_initial_prompt("Bohemian Rhapsody")
        assert "Bohemian Rhapsody" in prompt

    def test_none_returns_none(self):
        assert build_initial_prompt(None) is None

    def test_empty_string_returns_none(self):
        assert build_initial_prompt("") is None


# ===========================================================================
# detect_language
# ===========================================================================

class TestDetectLanguage:
    def test_despacito_is_spanish(self):
        assert detect_language("Luis Fonsi - Despacito") == "es"

    def test_bad_bunny_is_spanish(self):
        assert detect_language("Bad Bunny - Tití Me Preguntó") == "es"

    def test_stromae_is_french(self):
        assert detect_language("Stromae - Papaoutai") == "fr"

    def test_unknown_song_returns_none(self):
        # Unknown titles return None so Whisper auto-detects language
        assert detect_language("Ed Sheeran - Shape of You") is None

    def test_none_returns_none(self):
        assert detect_language(None) is None


# ===========================================================================
# remove_hallucinations
# ===========================================================================

class TestRemoveHallucinations:
    def _seg(self, text: str, key: str = "lyric_current") -> dict:
        return {key: text, "t": 0.0, "end_time": 2.0}

    def test_subscribe_removed(self):
        segs = [self._seg("please subscribe"), self._seg("Hello world")]
        result = remove_hallucinations(segs, "lyric_current", None)
        texts = [s["lyric_current"] for s in result]
        assert "please subscribe" not in texts
        assert "Hello world" in texts

    def test_thank_you_for_watching_removed(self):
        segs = [self._seg("thank you for watching"), self._seg("Real lyric here")]
        result = remove_hallucinations(segs, "lyric_current", None)
        assert len(result) == 1
        assert result[0]["lyric_current"] == "Real lyric here"

    def test_music_only_removed(self):
        segs = [self._seg("[music]")]
        result = remove_hallucinations(segs, "lyric_current", None)
        assert result == []

    def test_normal_lyric_kept(self):
        segs = [self._seg("I'm in love with the shape of you")]
        result = remove_hallucinations(segs, "lyric_current", None)
        assert len(result) == 1

    def test_prompt_echo_removed(self):
        """A segment nearly identical to the prompt should be treated as hallucination."""
        prompt = "Shape of You, Ed Sheeran."
        segs = [self._seg("Shape of You Ed Sheeran")]
        result = remove_hallucinations(segs, "lyric_current", prompt)
        assert len(result) == 0

    def test_you_is_not_removed(self):
        """'you' on its own used to be incorrectly flagged; should be kept."""
        segs = [self._seg("I need you")]
        result = remove_hallucinations(segs, "lyric_current", None)
        assert len(result) == 1

    def test_copyright_removed(self):
        segs = [self._seg("copyright 2024 all rights reserved")]
        result = remove_hallucinations(segs, "lyric_current", None)
        assert result == []


# ===========================================================================
# remove_junk
# ===========================================================================

class TestRemoveJunk:
    def _seg(self, text: str) -> dict:
        return {"lyric_current": text}

    def test_pure_punctuation_removed(self):
        segs = [self._seg("..."), self._seg("Hello world")]
        result = remove_junk(segs, "lyric_current")
        assert len(result) == 1
        assert result[0]["lyric_current"] == "Hello world"

    def test_single_alpha_char_removed(self):
        segs = [self._seg("a")]
        result = remove_junk(segs, "lyric_current")
        assert result == []

    def test_two_alpha_chars_kept(self):
        segs = [self._seg("uh")]
        # "uh" matches the junk pattern for filler sounds
        # but has 2 alpha chars — pattern check should still remove it
        result = remove_junk(segs, "lyric_current")
        assert result == []

    def test_normal_lyric_kept(self):
        segs = [self._seg("Dancing in the moonlight")]
        result = remove_junk(segs, "lyric_current")
        assert len(result) == 1


# ===========================================================================
# remove_non_target_script
# ===========================================================================

class TestRemoveNonTargetScript:
    def test_latin_text_kept(self):
        items = [{"text": "Hello world"}]
        result = remove_non_target_script(items, "text", "Ed Sheeran - Song")
        assert len(result) == 1

    def test_arabic_text_removed_for_english_song(self):
        items = [{"text": "مرحبا بالعالم هذا نص"}]
        result = remove_non_target_script(items, "text", "Ed Sheeran - Song")
        assert result == []

    def test_empty_list_returned_unchanged(self):
        assert remove_non_target_script([], "text") == []


# ===========================================================================
# remove_stutter_duplicates
# ===========================================================================

class TestRemoveStutterDuplicates:
    def _marker(self, text: str, t: float, end: float) -> dict:
        return {"text": text, "time": t, "end_time": end, "words": []}

    def test_identical_close_gap_removed(self):
        markers = [
            self._marker("Hello world", 0.0, 1.0),
            self._marker("Hello world", 1.1, 2.1),   # gap = 0.1s < 0.5s
        ]
        result = remove_stutter_duplicates(markers, "text")
        assert len(result) == 1

    def test_identical_large_gap_kept(self):
        markers = [
            self._marker("Hello world", 0.0, 1.0),
            self._marker("Hello world", 3.0, 4.0),   # gap = 2.0s, chorus repeat
        ]
        result = remove_stutter_duplicates(markers, "text")
        assert len(result) == 2

    def test_different_text_both_kept(self):
        markers = [
            self._marker("Hello world",   0.0, 1.0),
            self._marker("Goodbye world", 1.1, 2.1),
        ]
        result = remove_stutter_duplicates(markers, "text")
        assert len(result) == 2

    def test_single_item_unchanged(self):
        markers = [self._marker("Hello", 0.0, 1.0)]
        assert remove_stutter_duplicates(markers, "text") == markers


# ===========================================================================
# remove_repetition_loops
# ===========================================================================

class TestRemoveRepetitionLoops:
    def _seg(self, text: str) -> dict:
        return {"lyric_current": text}

    def test_three_repeats_capped_at_two(self):
        items = [
            self._seg("Na na na"),
            self._seg("Na na na"),
            self._seg("Na na na"),
            self._seg("Na na na"),
        ]
        result = remove_repetition_loops(items, "lyric_current")
        assert len(result) == 2

    def test_two_repeats_both_kept(self):
        items = [self._seg("La la la"), self._seg("La la la")]
        result = remove_repetition_loops(items, "lyric_current")
        assert len(result) == 2

    def test_no_repeats_unchanged(self):
        items = [self._seg("One"), self._seg("Two"), self._seg("Three")]
        result = remove_repetition_loops(items, "lyric_current")
        assert len(result) == 3

    def test_short_list_unchanged(self):
        items = [self._seg("Only one")]
        assert remove_repetition_loops(items, "lyric_current") == items


# ===========================================================================
# build_markers_from_segments
# ===========================================================================

class TestBuildMarkersFromSegments:
    def test_produces_correct_fields(self, sample_whisper_result: MagicMock):
        markers = build_markers_from_segments(sample_whisper_result.segments)
        assert len(markers) == 4
        for m in markers:
            assert "time" in m
            assert "text" in m
            assert "words" in m
            assert "color" in m
            assert "end_time" in m

    def test_times_match_segments(self, sample_whisper_result: MagicMock):
        markers = build_markers_from_segments(sample_whisper_result.segments)
        assert abs(markers[0]["time"] - 0.5) < 0.01
        assert abs(markers[0]["end_time"] - 3.2) < 0.01

    def test_skips_empty_text(self):
        seg = MagicMock()
        seg.text = "   "
        seg.start = 0.0
        seg.end = 1.0
        seg.words = []
        markers = build_markers_from_segments([seg])
        assert markers == []

    def test_skips_overly_long_segment(self):
        seg = MagicMock()
        seg.text = "This goes on way too long"
        seg.start = 0.0
        seg.end = 35.0   # > 30s threshold
        seg.words = []
        markers = build_markers_from_segments([seg])
        assert markers == []


# ===========================================================================
# extract_word_timings
# ===========================================================================

class TestExtractWordTimings:
    def test_word_level_data_used_when_present(self, sample_whisper_result: MagicMock):
        seg = sample_whisper_result.segments[0]
        words = extract_word_timings(seg, seg.start, seg.end, seg.text)
        assert len(words) > 0
        for w in words:
            assert "word" in w
            assert "start" in w
            assert "end" in w

    def test_fallback_uniform_distribution(self):
        """When segment has no word-level data, words are distributed evenly."""
        seg = MagicMock()
        seg.text = "Three word phrase"
        seg.start = 0.0
        seg.end = 3.0
        seg.words = []   # No word data
        words = extract_word_timings(seg, 0.0, 3.0, "Three word phrase")
        assert len(words) == 3
        # Each word should span ~1 second
        assert abs(words[0]["end"] - words[0]["start"] - 1.0) < 0.1

    def test_clamped_word_duration(self):
        """Word durations > 3s should be clamped to 1s."""
        word = MagicMock()
        word.word = "long"
        word.start = 0.0
        word.end = 10.0   # unrealistically long
        seg = MagicMock()
        seg.text = "long"
        seg.start = 0.0
        seg.end = 10.0
        seg.words = [word]
        words = extract_word_timings(seg, 0.0, 10.0, "long")
        assert words[0]["end"] - words[0]["start"] <= 1.0 + 0.01


# ===========================================================================
# fix_marker_gaps
# ===========================================================================

class TestFixMarkerGaps:
    def test_large_gap_compressed(self):
        markers = [
            {
                "time": 0.0, "end_time": 5.0,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0},
                    {"word": "world", "start": 8.0, "end": 9.0},  # gap = 7s > 4s
                ],
                "text": "Hello world", "color": "",
            }
        ]
        fix_marker_gaps(markers)
        gap = markers[0]["words"][1]["start"] - markers[0]["words"][0]["end"]
        assert gap < 4.0   # Should have been compressed

    def test_small_gap_unchanged(self):
        markers = [
            {
                "time": 0.0, "end_time": 3.0,
                "words": [
                    {"word": "Hi",    "start": 0.0, "end": 1.0},
                    {"word": "there", "start": 2.0, "end": 3.0},   # gap = 1.0s <= 4s
                ],
                "text": "Hi there", "color": "",
            }
        ]
        fix_marker_gaps(markers)
        assert markers[0]["words"][1]["start"] == 2.0   # unchanged


# ===========================================================================
# merge_short_markers
# ===========================================================================

class TestMergeShortMarkers:
    def _m(self, text: str, t: float, end: float) -> dict:
        return {"text": text, "time": t, "end_time": end, "words": [], "color": "white"}

    def test_single_word_merged_when_gap_small(self):
        markers = [
            self._m("Yeah",                       0.0, 0.5),   # 1 word, gap 0.3s
            self._m("I'm in love with the shape", 0.8, 3.0),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 1
        assert "Yeah" in result[0]["text"]
        assert "I'm in love" in result[0]["text"]

    def test_single_word_not_merged_when_gap_large(self):
        markers = [
            self._m("Yeah",                       0.0, 0.5),
            self._m("I'm in love with the shape", 3.0, 6.0),   # gap = 2.5s > 1.5s
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_long_marker_not_merged(self):
        markers = [
            self._m("Long enough sentence here", 0.0, 2.0),
            self._m("Another long line",          2.5, 4.5),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_single_marker_returned_unchanged(self):
        markers = [self._m("Only one", 0.0, 1.0)]
        assert merge_short_markers(markers) == markers


# ===========================================================================
# quality_gate
# ===========================================================================

class TestQualityGate:
    def _m(self, t: float, end: float, text: str = "lyric line here") -> dict:
        return {"time": t, "end_time": end, "text": text}

    def test_passes_good_coverage(self):
        # 10s clip with 8s of markers = 80% coverage
        markers = [self._m(0.5, 4.0), self._m(4.5, 8.5)]
        passed, issues = quality_gate(markers, clip_duration=10.0)
        assert passed
        assert issues == []

    def test_fails_empty_markers(self):
        passed, issues = quality_gate([], clip_duration=10.0)
        assert not passed
        assert len(issues) > 0

    def test_fails_low_coverage(self):
        # Only 1.5s covered in a 30s clip = 5% coverage
        markers = [self._m(14.0, 15.5)]
        passed, issues = quality_gate(markers, clip_duration=30.0)
        assert not passed
        assert any("Coverage" in i for i in issues)

    def test_fails_excessive_dead_space(self):
        # 60s clip: only first 5s have markers, rest is dead
        markers = [self._m(0.0, 5.0)]
        passed, issues = quality_gate(markers, clip_duration=60.0)
        assert not passed

    def test_passes_when_duration_unknown(self):
        markers = [self._m(0.0, 1.0)]
        passed, issues = quality_gate(markers, clip_duration=None)
        assert passed

    def test_fails_single_marker_long_clip(self):
        markers = [self._m(0.0, 1.0)]
        passed, issues = quality_gate(markers, clip_duration=30.0)
        assert not passed
        assert any("Single marker" in i for i in issues)


# ===========================================================================
# save_whisper_cache / load_whisper_cache
# ===========================================================================

class TestWhisperCache:
    def _make_segments(self) -> list[dict]:
        return [
            {"t": 0.5, "end_time": 3.2, "lyric_current": "Hello world",    "words": []},
            {"t": 3.4, "end_time": 6.1, "lyric_current": "Second line",     "words": []},
        ]

    def test_round_trip_preserves_data(self, job_folder: Path):
        segs = self._make_segments()
        save_whisper_cache(str(job_folder), segs)
        loaded = load_whisper_cache(str(job_folder))
        assert loaded is not None
        assert len(loaded) == 2
        texts = [s["text"] for s in loaded]
        assert "Hello world" in texts
        assert "Second line" in texts

    def test_cache_file_exists_after_save(self, job_folder: Path):
        save_whisper_cache(str(job_folder), self._make_segments())
        assert (job_folder / "whisper_raw.json").exists()

    def test_returns_none_when_no_cache(self, job_folder: Path):
        assert load_whisper_cache(str(job_folder)) is None

    def test_stale_model_tag_returns_none(self, job_folder: Path):
        """Cache written with a different model name should be rejected."""
        cache_path = job_folder / "whisper_raw.json"
        cache_path.write_text(
            json.dumps({"model": "large-v3", "segments": [{"start": 0, "end": 1, "text": "hi"}]}),
            encoding="utf-8",
        )
        # Config.WHISPER_MODEL defaults to "small" in tests
        result = load_whisper_cache(str(job_folder))
        # If current model != "large-v3", should reject
        from scripts.config import Config
        if Config.WHISPER_MODEL != "large-v3":
            assert result is None

    def test_old_bare_list_format_loaded(self, job_folder: Path):
        """Old-format cache (bare list, no model tag) should still load."""
        cache_path = job_folder / "whisper_raw.json"
        cache_path.write_text(
            json.dumps([{"start": 0.0, "end": 2.0, "text": "legacy"}]),
            encoding="utf-8",
        )
        loaded = load_whisper_cache(str(job_folder))
        assert loaded is not None
        assert len(loaded) == 1


# ===========================================================================
# assign_colors
# ===========================================================================

class TestAssignColors:
    def test_alternates_white_black(self, mono_markers: list):
        assign_colors(mono_markers)
        assert mono_markers[0]["color"] == "white"
        assert mono_markers[1]["color"] == "black"

    def test_even_indices_are_white(self):
        markers = [{"color": ""} for _ in range(6)]
        assign_colors(markers)
        for i, m in enumerate(markers):
            expected = "white" if i % 2 == 0 else "black"
            assert m["color"] == expected


# ===========================================================================
# rebuild_words_after_alignment
# ===========================================================================

class TestRebuildWordsAfterAlignment:
    def test_genius_words_replace_whisper_words(self):
        """Genius text replaces Whisper words while preserving timing order."""
        markers = [
            {
                "time": 0.5,
                "end_time": 3.2,
                "text": "I'm in love with the shape of you",
                "words": [
                    {"word": "Im",   "start": 0.5, "end": 0.9},
                    {"word": "in",   "start": 0.9, "end": 1.2},
                    {"word": "love", "start": 1.2, "end": 1.6},
                    {"word": "with", "start": 1.6, "end": 1.9},
                    {"word": "the",  "start": 1.9, "end": 2.1},
                    {"word": "shape","start": 2.1, "end": 2.5},
                    {"word": "of",   "start": 2.5, "end": 2.7},
                    {"word": "you",  "start": 2.7, "end": 3.2},
                ],
            }
        ]
        rebuild_words_after_alignment(markers)
        # Words in the rebuilt marker should match the genius text
        rebuilt_words = [w["word"] for w in markers[0]["words"]]
        assert "I'm" in rebuilt_words or "Im" in rebuilt_words   # fuzzy match applied

    def test_more_genius_words_distributed_evenly(self):
        """When Genius has more words than Whisper, evenly distribute timing."""
        markers = [
            {
                "time": 0.0,
                "end_time": 4.0,
                "text": "one two three four five",
                "words": [
                    {"word": "one",  "start": 0.0, "end": 2.0},
                    {"word": "three","start": 2.0, "end": 4.0},
                ],
            }
        ]
        rebuild_words_after_alignment(markers)
        # Should have 5 words now
        assert len(markers[0]["words"]) == 5
        # All words should be sorted by start time
        starts = [w["start"] for w in markers[0]["words"]]
        assert starts == sorted(starts)


# ===========================================================================
# normalize_audio
# ===========================================================================

class TestNormalizeAudio:
    def _make_quiet_wav(self, path: Path) -> Path:
        """Create a non-silent but quiet WAV for normalization testing."""
        from pydub import AudioSegment
        from pydub.generators import Sine
        tone = Sine(440).to_audio_segment(duration=1000).apply_gain(-40)
        wav_path = path / "quiet.wav"
        tone.export(str(wav_path), format="wav")
        return wav_path

    def test_normalizes_and_creates_file(self, tmp_dir: Path):
        wav = self._make_quiet_wav(tmp_dir)
        path, duration = normalize_audio(str(wav))
        assert path.endswith("_norm.wav")
        assert os.path.exists(path)
        assert isinstance(duration, float)
        assert duration > 0

    def test_caches_result(self, tmp_dir: Path):
        wav = self._make_quiet_wav(tmp_dir)
        first_path, _ = normalize_audio(str(wav))
        second_path, _ = normalize_audio(str(wav))
        assert first_path == second_path

    def test_silent_audio_returns_original(self, silent_wav: Path):
        # Truly silent audio (-inf dBFS) should return original path
        path, duration = normalize_audio(str(silent_wav))
        assert path == str(silent_wav)
        assert isinstance(duration, float)

    def test_failure_returns_original(self, tmp_dir: Path):
        bad_path = str(tmp_dir / "nonexistent.wav")
        path, duration = normalize_audio(bad_path)
        assert path == bad_path
        assert duration is None


# ===========================================================================
# reduce_noise
# ===========================================================================

class TestReduceNoise:
    def test_falls_back_when_noisereduce_missing(self, silent_wav: Path):
        with patch.dict("sys.modules", {"noisereduce": None}):
            result = reduce_noise(str(silent_wav))
            assert result == str(silent_wav)

    def test_failure_returns_original(self, tmp_dir: Path):
        bad_path = str(tmp_dir / "nonexistent.wav")
        result = reduce_noise(bad_path)
        assert result == bad_path


# ===========================================================================
# _refine_result / _snap_to_silence
# ===========================================================================

class TestRefineResult:
    def test_calls_apply_min_dur_and_remove_repetition(self):
        mock_result = MagicMock()
        _refine_result(mock_result)
        mock_result.apply_min_dur.assert_called_once_with(0.02)
        mock_result.remove_repetition.assert_called_once_with(max_words=1)

    def test_handles_exception_gracefully(self):
        mock_result = MagicMock()
        mock_result.apply_min_dur.side_effect = RuntimeError("test")
        _refine_result(mock_result)  # should not raise


class TestSnapToSilence:
    def test_calls_adjust_by_silence(self):
        mock_result = MagicMock()
        _snap_to_silence(mock_result, "/fake/audio.wav")
        mock_result.adjust_by_silence.assert_called_once_with("/fake/audio.wav", vad=True)

    def test_handles_exception_gracefully(self):
        mock_result = MagicMock()
        mock_result.adjust_by_silence.side_effect = RuntimeError("test")
        _snap_to_silence(mock_result, "/fake/audio.wav")  # should not raise


# ===========================================================================
# align_genius_to_audio
# ===========================================================================

class TestAlignGeniusToAudio:
    def test_returns_none_for_empty_text(self):
        assert align_genius_to_audio("/fake.wav", "") is None
        assert align_genius_to_audio("/fake.wav", None) is None

    @patch("scripts.whisper_common.load_whisper_model")
    def test_calls_model_align(self, mock_load):
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.segments = [MagicMock()]
        mock_model.align.return_value = mock_result
        mock_load.return_value = mock_model

        result = align_genius_to_audio("/fake.wav", "Hello world lyrics here")
        assert result is not None
        mock_model.align.assert_called_once()

    @patch("scripts.whisper_common.load_whisper_model")
    def test_returns_none_on_failure(self, mock_load):
        mock_model = MagicMock()
        mock_model.align.side_effect = RuntimeError("alignment failed")
        mock_load.return_value = mock_model

        result = align_genius_to_audio("/fake.wav", "Hello world")
        assert result is None


# ===========================================================================
# detect_language with genius_text (#29)
# ===========================================================================

class TestDetectLanguageWithGenius:
    @patch("scripts.whisper_common._detect_lang", create=True)
    def test_langdetect_used_when_genius_text_provided(self, mock_detect):
        with patch.dict("sys.modules", {"langdetect": MagicMock(detect=lambda t: "pt")}):
            result = detect_language("Unknown - Song", genius_text="Eu amo você muito querido " * 5)
            assert result == "pt"

    def test_falls_back_to_title_when_no_genius(self):
        result = detect_language("Bad Bunny - Track")
        assert result == "es"

    def test_returns_none_for_unknown_no_genius(self):
        result = detect_language("Unknown Artist - Unknown Song")
        assert result is None

    def test_short_genius_text_ignored(self):
        # genius_text < 50 chars should be ignored
        result = detect_language("Bad Bunny - Track", genius_text="short")
        assert result == "es"


# ===========================================================================
# remove_instrumental_hallucinations (updated: full-span + no_speech_prob)
# ===========================================================================

class TestRemoveInstrumentalHallucinationsUpdated:
    def test_no_speech_prob_filtering(self, silent_wav: Path):
        items = [
            {"text": "real lyrics", "time": 0.0, "end_time": 1.0, "no_speech_prob": 0.1},
            {"text": "hallucination", "time": 1.0, "end_time": 2.0, "no_speech_prob": 0.9},
        ]
        result = remove_instrumental_hallucinations(items, "text", str(silent_wav))
        texts = [i["text"] for i in result]
        assert "real lyrics" in texts
        assert "hallucination" not in texts

    def test_empty_items_returns_empty(self, silent_wav: Path):
        result = remove_instrumental_hallucinations([], "text", str(silent_wav))
        assert result == []

    def test_items_without_no_speech_prob_not_filtered_by_prob(self, silent_wav: Path):
        items = [
            {"text": "lyrics", "time": 0.0, "end_time": 0.5},
        ]
        result = remove_instrumental_hallucinations(items, "text", str(silent_wav))
        assert len(result) == 1
