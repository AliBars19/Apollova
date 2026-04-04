"""
Tests for marker operations in assets/scripts/whisper_common.py

Covers: fix_marker_gaps, merge_short_markers, quality_gate, assign_colors,
        rebuild_words_after_alignment, build_markers_from_segments.
"""
import sys
import copy
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock heavy dependencies BEFORE importing whisper_common
# ---------------------------------------------------------------------------
sys.modules.setdefault("stable_whisper", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("pydub", MagicMock())
sys.modules.setdefault("pydub.playback", MagicMock())
sys.modules.setdefault("scripts.audio_processing", MagicMock())
pydub_mock = sys.modules["pydub"]
pydub_mock.AudioSegment = MagicMock()

import pytest

from scripts.whisper_common import (
    fix_marker_gaps,
    merge_short_markers,
    quality_gate,
    assign_colors,
    rebuild_words_after_alignment,
    build_markers_from_segments,
    MARKER_GAP_THRESHOLD_SEC,
)


# ---------------------------------------------------------------------------
# Mock segment helpers for build_markers_from_segments
# ---------------------------------------------------------------------------

class MockWord:
    def __init__(self, word: str, start: float, end: float, probability: float = None):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class MockSegment:
    def __init__(self, text: str, start: float, end: float, words=None,
                 avg_logprob: float = None, no_speech_prob: float = None):
        self.text = text
        self.start = start
        self.end = end
        self.words = words
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


# ===========================================================================
# fix_marker_gaps — 20 tests
# ===========================================================================

class TestFixMarkerGaps:
    def _marker(self, words):
        """Helper: create a single marker with given word list."""
        return {"time": words[0]["start"], "words": words, "text": " ".join(w["word"] for w in words)}

    def test_gap_above_threshold_compressed(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 10.0, "end": 11.0},  # gap = 9.0 > 4.0
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] < 10.0

    def test_gap_below_threshold_unchanged(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 2.0, "end": 3.0},  # gap = 1.0 < 4.0
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] == 2.0

    def test_gap_exactly_at_threshold_unchanged(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 5.0, "end": 6.0},  # gap = 4.0 == threshold
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] == 5.0

    def test_compression_capped_at_05(self):
        # gap * 0.1 > 0.5 → capped at 0.5
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 100.0, "end": 101.0},  # gap = 99s
        ])
        fix_marker_gaps([marker])
        # compression = min(99*0.1, 0.5) = 0.5 → new start = 1.0 + 0.5 = 1.5
        assert marker["words"][1]["start"] == pytest.approx(1.5, abs=0.001)

    def test_proportional_compression_small_gap(self):
        # gap = 5.0 → compression = 5.0 * 0.1 = 0.5
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 6.0, "end": 7.0},
        ])
        fix_marker_gaps([marker])
        # compression = min(5.0 * 0.1, 0.5) = 0.5 → new start = 1.0 + 0.5 = 1.5
        assert marker["words"][1]["start"] == pytest.approx(1.5, abs=0.001)

    def test_empty_words_list_no_crash(self):
        marker = {"time": 0.0, "words": [], "text": ""}
        fix_marker_gaps([marker])
        assert marker["words"] == []

    def test_single_word_no_crash(self):
        marker = self._marker([{"word": "solo", "start": 0.0, "end": 1.0}])
        fix_marker_gaps([marker])
        assert marker["words"][0]["start"] == 0.0

    def test_empty_markers_list_no_crash(self):
        fix_marker_gaps([])  # Should not raise

    def test_multiple_gaps_all_compressed(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 10.0, "end": 11.0},
            {"word": "c", "start": 20.0, "end": 21.0},
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] < 10.0
        assert marker["words"][2]["start"] < 20.0

    def test_mutates_in_place(self):
        words = [
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 10.0, "end": 11.0},
        ]
        marker = {"time": 0.0, "words": words, "text": "a b"}
        original_words = marker["words"]
        fix_marker_gaps([marker])
        assert marker["words"] is original_words

    def test_two_markers_both_processed(self):
        m1 = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 10.0, "end": 11.0},
        ])
        m2 = self._marker([
            {"word": "c", "start": 20.0, "end": 21.0},
            {"word": "d", "start": 30.0, "end": 31.0},
        ])
        fix_marker_gaps([m1, m2])
        assert m1["words"][1]["start"] < 10.0
        assert m2["words"][1]["start"] < 30.0

    def test_gap_just_above_threshold_compressed(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 5.1, "end": 6.0},  # gap = 4.1 > 4.0
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] < 5.1

    def test_three_words_first_gap_ok_second_large(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 2.0, "end": 3.0},  # gap 1.0 → ok
            {"word": "c", "start": 15.0, "end": 16.0},  # gap 12.0 → compressed
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] == 2.0  # unchanged
        assert marker["words"][2]["start"] < 15.0  # compressed

    def test_no_end_field_no_crash(self):
        # Words might not have end key in edge cases
        marker = {"time": 0.0, "words": [
            {"word": "a", "start": 0.0, "end": 1.0},
        ], "text": "a"}
        fix_marker_gaps([marker])

    def test_negative_gap_no_change(self):
        # Words out of order: second word starts before first ends
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 5.0},
            {"word": "b", "start": 3.0, "end": 4.0},  # gap = -2.0 → no change
        ])
        original_start = marker["words"][1]["start"]
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] == original_start

    def test_compression_formula_for_medium_gap(self):
        # gap = 6.0 → compression = min(0.6, 0.5) = 0.5
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 7.0, "end": 8.0},
        ])
        fix_marker_gaps([marker])
        assert marker["words"][1]["start"] == pytest.approx(1.5, abs=0.001)

    def test_words_without_gaps_unaffected(self):
        marker = self._marker([
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 0.6, "end": 1.1},
            {"word": "c", "start": 1.2, "end": 1.7},
        ])
        fix_marker_gaps([marker])
        assert marker["words"][0]["start"] == 0.0
        assert marker["words"][1]["start"] == 0.6
        assert marker["words"][2]["start"] == 1.2

    def test_large_gap_new_start_is_prev_end_plus_compression(self):
        marker = self._marker([
            {"word": "a", "start": 2.0, "end": 3.0},
            {"word": "b", "start": 20.0, "end": 21.0},
        ])
        fix_marker_gaps([marker])
        # gap = 17.0 → compression = 0.5 → new start = 3.0 + 0.5 = 3.5
        assert marker["words"][1]["start"] == pytest.approx(3.5, abs=0.001)

    def test_threshold_constant_is_4(self):
        assert MARKER_GAP_THRESHOLD_SEC == 4.0


# ===========================================================================
# merge_short_markers — 20 tests
# ===========================================================================

def _make_marker(time: float, text: str, end_time: float, color: str = "white"):
    words = [{"word": w, "start": time + i * 0.2, "end": time + (i + 1) * 0.2}
             for i, w in enumerate(text.split())]
    return {"time": time, "text": text, "words": words, "end_time": end_time, "color": color}


class TestMergeShortMarkers:
    def test_single_word_merged_with_next(self):
        markers = [
            _make_marker(0.0, "yeah", 0.5),
            _make_marker(0.8, "this is a song", 3.0),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 1
        assert "yeah" in result[0]["text"]

    def test_two_word_merged_with_next(self):
        markers = [
            _make_marker(0.0, "oh yeah", 0.8),
            _make_marker(1.0, "this is a song", 3.0),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 1

    def test_three_word_not_merged(self):
        markers = [
            _make_marker(0.0, "one two three", 1.5),
            _make_marker(2.0, "another line here", 4.0),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_gap_too_large_not_merged(self):
        markers = [
            _make_marker(0.0, "yeah", 0.5),
            _make_marker(5.0, "this is a song", 7.0),  # gap = 4.5 > 1.5
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_single_marker_returned_unchanged(self):
        markers = [_make_marker(0.0, "solo", 1.0)]
        result = merge_short_markers(markers)
        assert len(result) == 1

    def test_empty_list_returned(self):
        assert merge_short_markers([]) == []

    def test_merged_time_is_first_marker_time(self):
        markers = [
            _make_marker(1.5, "hey", 2.0),
            _make_marker(2.2, "how are you doing", 4.0),
        ]
        result = merge_short_markers(markers)
        assert result[0]["time"] == 1.5

    def test_merged_end_time_is_second_marker_end_time(self):
        markers = [
            _make_marker(1.5, "hey", 2.0),
            _make_marker(2.2, "how are you doing", 5.0),
        ]
        result = merge_short_markers(markers)
        assert result[0]["end_time"] == 5.0

    def test_merged_text_combines_both(self):
        markers = [
            _make_marker(0.0, "oh", 0.3),
            _make_marker(0.5, "my love", 1.5),
        ]
        result = merge_short_markers(markers)
        assert "oh" in result[0]["text"]
        assert "my love" in result[0]["text"]

    def test_skip_next_logic(self):
        # After merging, the consumed marker should not appear again
        markers = [
            _make_marker(0.0, "oh", 0.3),
            _make_marker(0.5, "my love", 1.5),
            _make_marker(2.0, "another line here now", 4.0),
        ]
        result = merge_short_markers(markers)
        # First two merged → 2 total
        assert len(result) == 2

    def test_last_marker_short_no_next_kept(self):
        markers = [
            _make_marker(0.0, "full long line here now", 2.0),
            _make_marker(3.0, "fin", 3.5),
        ]
        result = merge_short_markers(markers)
        # "fin" is last → no next to merge with → kept as-is
        assert len(result) == 2

    def test_words_combined_after_merge(self):
        markers = [
            _make_marker(0.0, "oh", 0.3),
            _make_marker(0.5, "my love", 1.5),
        ]
        result = merge_short_markers(markers)
        # Should have 3 words total (oh + my + love)
        assert len(result[0]["words"]) == 3

    def test_color_from_next_marker(self):
        markers = [
            _make_marker(0.0, "oh", 0.3, color="white"),
            _make_marker(0.5, "my love", 1.5, color="black"),
        ]
        result = merge_short_markers(markers)
        assert result[0]["color"] == "black"

    def test_two_markers_list_not_mutated(self):
        markers = [
            _make_marker(0.0, "long line of text", 2.0),
            _make_marker(3.0, "another line", 4.5),
        ]
        original = copy.deepcopy(markers)
        merge_short_markers(markers)
        assert len(markers) == len(original)

    def test_three_short_markers_in_a_row(self):
        # First merges with second (oh → "oh my"); the result has 2 words.
        # But merge_short_markers is a single pass — it doesn't re-evaluate merged results.
        # After merge: [("oh my", 0.0-0.8), ("love always", 1.0-2.5)] → 2 items.
        markers = [
            _make_marker(0.0, "oh", 0.3),
            _make_marker(0.5, "my", 0.8),
            _make_marker(1.0, "love always", 2.5),
        ]
        result = merge_short_markers(markers)
        # oh + my merged → "oh my"; skip_next=True skips "my"; "love always" kept
        assert len(result) == 2

    def test_max_gap_boundary(self):
        # gap = exactly max_gap (1.5) → merged
        markers = [
            _make_marker(0.0, "hey", 0.5),
            _make_marker(2.0, "a long line here", 4.0),  # gap = 1.5
        ]
        result = merge_short_markers(markers)
        assert len(result) == 1

    def test_gap_just_above_max_not_merged(self):
        markers = [
            _make_marker(0.0, "hey", 0.5),
            _make_marker(2.1, "a long line here", 4.0),  # gap = 1.6 > 1.5
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_result_is_list(self):
        markers = [_make_marker(0.0, "test line", 1.0)]
        result = merge_short_markers(markers)
        assert isinstance(result, list)

    def test_no_merge_when_first_marker_long(self):
        markers = [
            _make_marker(0.0, "this is a long line", 2.0),
            _make_marker(2.5, "another long one here", 4.0),
        ]
        result = merge_short_markers(markers)
        assert len(result) == 2

    def test_custom_max_words_param(self):
        markers = [
            _make_marker(0.0, "one two three", 1.5),
            _make_marker(2.0, "another line here", 4.0),
        ]
        # With max_words=3, three-word marker should merge
        result = merge_short_markers(markers, max_words=3)
        assert len(result) == 1


# ===========================================================================
# quality_gate — 20 tests
# ===========================================================================

class TestQualityGate:
    def test_no_markers_fails(self):
        passed, issues = quality_gate([], 60.0)
        assert not passed
        assert any("No markers" in i for i in issues)

    def test_coverage_below_25_fails(self):
        # 2 seconds covered out of 60s → 3.3%
        markers = [{"time": 0.0, "end_time": 2.0, "text": "short"}]
        passed, issues = quality_gate(markers, 60.0)
        assert not passed
        assert any("Coverage" in i for i in issues)

    def test_coverage_above_25_passes(self):
        # 20 seconds covered out of 60s → 33%
        markers = [{"time": 0.0, "end_time": 20.0, "text": "good coverage"}]
        passed, issues = quality_gate(markers, 60.0)
        # May still fail on other checks, but coverage check should pass
        assert not any("Coverage" in i for i in issues)

    def test_dead_space_above_50_fails(self):
        # Small gap at start, end, lots of space
        markers = [{"time": 25.0, "end_time": 27.0, "text": "tiny"}]
        passed, issues = quality_gate(markers, 60.0)
        assert not passed

    def test_single_marker_long_clip_fails(self):
        markers = [{"time": 0.0, "end_time": 60.0, "text": "all"}]
        passed, issues = quality_gate(markers, 60.0)
        assert any("Single marker" in i for i in issues)

    def test_single_marker_short_clip_passes(self):
        markers = [{"time": 0.0, "end_time": 8.0, "text": "short clip"}]
        passed, issues = quality_gate(markers, 8.0)
        # No "single marker" issue for short clips
        assert not any("Single marker" in i for i in issues)

    def test_none_duration_passes(self):
        markers = [{"time": 0.0, "end_time": 3.0, "text": "anything"}]
        passed, issues = quality_gate(markers, None)
        assert passed

    def test_zero_duration_passes(self):
        markers = [{"time": 0.0, "end_time": 3.0, "text": "anything"}]
        passed, issues = quality_gate(markers, 0)
        assert passed

    def test_negative_duration_passes(self):
        markers = [{"time": 0.0, "end_time": 3.0, "text": "anything"}]
        passed, issues = quality_gate(markers, -1)
        assert passed

    def test_good_coverage_multiple_markers(self):
        markers = [
            {"time": 0.0, "end_time": 10.0, "text": "first"},
            {"time": 10.5, "end_time": 20.0, "text": "second"},
            {"time": 20.5, "end_time": 30.0, "text": "third"},
        ]
        passed, issues = quality_gate(markers, 30.0)
        assert passed

    def test_non_latin_dominates_fails(self):
        markers = [
            {"time": 0.0, "end_time": 20.0, "text": "Привет мир это текст"},
        ]
        passed, issues = quality_gate(markers, 60.0)
        assert any("Non-Latin" in i for i in issues)

    def test_mostly_latin_passes_script_check(self):
        markers = [
            {"time": 0.0, "end_time": 20.0, "text": "hello world how are you"},
        ]
        passed, issues = quality_gate(markers, 60.0)
        assert not any("Non-Latin" in i for i in issues)

    def test_returns_tuple(self):
        result = quality_gate([], 60.0)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_passed_is_bool(self):
        passed, _ = quality_gate([], 60.0)
        assert isinstance(passed, bool)

    def test_issues_is_list(self):
        _, issues = quality_gate([], 60.0)
        assert isinstance(issues, list)

    def test_no_issues_when_passes(self):
        markers = [
            {"time": 0.0, "end_time": 10.0, "text": "first"},
            {"time": 10.5, "end_time": 20.0, "text": "second"},
            {"time": 20.5, "end_time": 30.0, "text": "third"},
        ]
        passed, issues = quality_gate(markers, 30.0)
        if passed:
            assert issues == []

    def test_large_initial_gap_fails(self):
        # First marker starts at 40s → large initial gap
        markers = [{"time": 40.0, "end_time": 60.0, "text": "late start"}]
        passed, issues = quality_gate(markers, 60.0)
        assert not passed  # Either coverage or dead space issue

    def test_end_gap_counted(self):
        # Last marker ends at 10s, clip is 60s → 50s end gap
        markers = [{"time": 0.0, "end_time": 10.0, "text": "early end"}]
        passed, issues = quality_gate(markers, 60.0)
        assert not passed

    def test_multiple_issues_collected(self):
        # Very few markers, low coverage
        markers = [{"time": 30.0, "end_time": 32.0, "text": "x"}]
        _, issues = quality_gate(markers, 100.0)
        assert len(issues) >= 1

    def test_two_adequate_markers_passes(self):
        markers = [
            {"time": 0.0, "end_time": 15.0, "text": "verse one"},
            {"time": 15.5, "end_time": 30.0, "text": "verse two"},
        ]
        passed, _ = quality_gate(markers, 30.0)
        assert passed


# ===========================================================================
# assign_colors — 10 tests
# ===========================================================================

class TestAssignColors:
    def _markers(self, n):
        return [{"time": float(i), "text": f"line {i}", "color": ""} for i in range(n)]

    def test_even_index_white(self):
        markers = self._markers(1)
        assign_colors(markers)
        assert markers[0]["color"] == "white"

    def test_odd_index_black(self):
        markers = self._markers(2)
        assign_colors(markers)
        assert markers[1]["color"] == "black"

    def test_alternating_pattern(self):
        markers = self._markers(6)
        assign_colors(markers)
        expected = ["white", "black", "white", "black", "white", "black"]
        assert [m["color"] for m in markers] == expected

    def test_empty_list_no_crash(self):
        assign_colors([])

    def test_single_marker_white(self):
        markers = self._markers(1)
        assign_colors(markers)
        assert markers[0]["color"] == "white"

    def test_three_markers_pattern(self):
        markers = self._markers(3)
        assign_colors(markers)
        assert markers[0]["color"] == "white"
        assert markers[1]["color"] == "black"
        assert markers[2]["color"] == "white"

    def test_mutates_in_place(self):
        markers = self._markers(2)
        assign_colors(markers)
        assert markers[0]["color"] == "white"

    def test_existing_color_overwritten(self):
        markers = [{"color": "red"}, {"color": "green"}]
        assign_colors(markers)
        assert markers[0]["color"] == "white"
        assert markers[1]["color"] == "black"

    def test_large_list_pattern_correct(self):
        markers = self._markers(10)
        assign_colors(markers)
        for i, m in enumerate(markers):
            expected = "white" if i % 2 == 0 else "black"
            assert m["color"] == expected

    def test_four_markers_all_assigned(self):
        markers = self._markers(4)
        assign_colors(markers)
        assert all(m["color"] in ("white", "black") for m in markers)


# ===========================================================================
# rebuild_words_after_alignment — 20 tests
# ===========================================================================

class TestRebuildWordsAfterAlignment:
    def _marker(self, text, words, t=0.0, end=4.0):
        return {"time": t, "text": text, "words": words, "end_time": end, "color": "white"}

    def test_genius_words_leq_whisper_fuzzy_match(self):
        # whisper joined = "hello world" == genius text "hello world" (case-insensitive check)
        # function checks: whisper_joined.strip().lower() == marker["text"].strip().lower()
        # "hello world" == "hello world" → SKIPPED (no rebuild)
        whisper_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
        ]
        marker = self._marker("hello world", whisper_words)
        rebuild_words_after_alignment([marker])
        texts = [w["word"] for w in marker["words"]]
        # Unchanged since exact match
        assert "hello" in texts
        assert "world" in texts

    def test_more_genius_words_distribute_evenly(self):
        whisper_words = [
            {"word": "hey", "start": 0.0, "end": 0.5},
        ]
        marker = self._marker("hey there how are you", whisper_words, t=0.0, end=5.0)
        rebuild_words_after_alignment([marker])
        assert len(marker["words"]) == 5
        # Each word should be ~1s apart
        assert marker["words"][1]["start"] > marker["words"][0]["start"]

    def test_exact_match_unchanged(self):
        whisper_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
        ]
        marker = self._marker("hello world", copy.deepcopy(whisper_words))
        rebuild_words_after_alignment([marker])
        assert marker["words"][0]["word"] == "hello"
        assert marker["words"][1]["word"] == "world"

    def test_empty_whisper_words_fallback(self):
        marker = self._marker("a b c", [], t=0.0, end=3.0)
        rebuild_words_after_alignment([marker])
        # With no whisper words and no genius words matched, text remains as is
        # (function skips when whisper_words is empty)
        assert isinstance(marker["words"], list)

    def test_empty_genius_words_skipped(self):
        marker = self._marker("", [{"word": "x", "start": 0.0, "end": 1.0}])
        original_words = copy.deepcopy(marker["words"])
        rebuild_words_after_alignment([marker])
        # Empty text.split() = [] → skipped
        assert marker["words"] == original_words

    def test_genius_has_more_words_even_distribution(self):
        whisper_words = [{"word": "a", "start": 0.0, "end": 0.5}]
        marker = self._marker("one two three four", whisper_words, t=0.0, end=4.0)
        rebuild_words_after_alignment([marker])
        starts = [w["start"] for w in marker["words"]]
        assert starts == sorted(starts)

    def test_sorted_by_start_time(self):
        whisper_words = [
            {"word": "second", "start": 1.0, "end": 1.5},
            {"word": "first", "start": 0.0, "end": 0.5},
        ]
        marker = self._marker("first second", whisper_words)
        rebuild_words_after_alignment([marker])
        starts = [w["start"] for w in marker["words"]]
        assert starts == sorted(starts)

    def test_multiple_markers_processed(self):
        m1 = self._marker("hello", [{"word": "hello", "start": 0.0, "end": 0.5}])
        m2 = self._marker("world", [{"word": "world", "start": 2.0, "end": 2.5}])
        rebuild_words_after_alignment([m1, m2])
        assert m1["words"][0]["word"] == "hello"
        assert m2["words"][0]["word"] == "world"

    def test_returns_markers_list(self):
        markers = [self._marker("test", [{"word": "test", "start": 0.0, "end": 1.0}])]
        result = rebuild_words_after_alignment(markers)
        assert isinstance(result, list)

    def test_empty_markers_list(self):
        result = rebuild_words_after_alignment([])
        assert result == []

    def test_fuzzy_match_preserves_genius_text(self):
        # whisper joined = "gonna be" != genius "Gonna be" (case differs)
        # But the comparison is: whisper_joined.strip().lower() == marker["text"].strip().lower()
        # "gonna be" == "gonna be" → EQUAL → skipped, no rebuild
        # So the word stays as "gonna" not "Gonna"
        whisper_words = [
            {"word": "gonna", "start": 0.5, "end": 0.9},
            {"word": "be", "start": 1.0, "end": 1.3},
        ]
        marker = self._marker("Gonna be", whisper_words)
        rebuild_words_after_alignment([marker])
        # Case-folded match → no rebuild → words unchanged as "gonna", "be"
        texts_lower = [w["word"].lower() for w in marker["words"]]
        assert "gonna" in texts_lower
        assert "be" in texts_lower

    def test_more_genius_than_whisper_uses_seg_time(self):
        whisper_words = [{"word": "hey", "start": 1.0, "end": 1.5}]
        marker = self._marker("hey there you are", whisper_words, t=1.0, end=5.0)
        rebuild_words_after_alignment([marker])
        # All start times should be >= marker time
        for w in marker["words"]:
            assert w["start"] >= 1.0

    def test_even_distribution_end_times(self):
        whisper_words = [{"word": "x", "start": 0.0, "end": 0.5}]
        marker = self._marker("a b", whisper_words, t=0.0, end=2.0)
        rebuild_words_after_alignment([marker])
        # 2 words over 2s → each 1s; word[0]: 0-1, word[1]: 1-2
        assert marker["words"][0]["end"] <= marker["words"][1]["start"] + 0.001

    def test_single_word_kept(self):
        whisper_words = [{"word": "solo", "start": 1.0, "end": 2.0}]
        marker = self._marker("solo", whisper_words)
        rebuild_words_after_alignment([marker])
        assert len(marker["words"]) == 1

    def test_genius_word_keeps_whisper_timing(self):
        whisper_words = [
            {"word": "running", "start": 5.0, "end": 5.5},
        ]
        marker = self._marker("Running", whisper_words)
        rebuild_words_after_alignment([marker])
        assert marker["words"][0]["start"] == 5.0
        assert marker["words"][0]["end"] == 5.5

    def test_used_set_prevents_double_matching(self):
        whisper_words = [
            {"word": "the", "start": 0.0, "end": 0.3},
            {"word": "the", "start": 0.5, "end": 0.8},
        ]
        marker = self._marker("the the", whisper_words)
        rebuild_words_after_alignment([marker])
        # Both whisper "the" words should be used
        assert len(marker["words"]) == 2

    def test_whisper_joined_equals_genius_text_skipped(self):
        # If whisper text already matches genius text, function skips
        whisper_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
        ]
        marker = self._marker("hello world", copy.deepcopy(whisper_words))
        rebuild_words_after_alignment([marker])
        # Should be unchanged
        assert marker["words"][0]["word"] == "hello"

    def test_distribute_preserves_word_texts(self):
        whisper_words = [{"word": "x", "start": 0.0, "end": 0.5}]
        marker = self._marker("alpha beta gamma", whisper_words, t=0.0, end=3.0)
        rebuild_words_after_alignment([marker])
        texts = [w["word"] for w in marker["words"]]
        assert "alpha" in texts
        assert "beta" in texts
        assert "gamma" in texts

    def test_fallback_timing_uses_marker_time_and_end(self):
        whisper_words = [{"word": "x", "start": 2.0, "end": 2.5}]
        marker = self._marker("a b c d", whisper_words, t=2.0, end=6.0)
        rebuild_words_after_alignment([marker])
        assert marker["words"][0]["start"] >= 2.0
        assert marker["words"][-1]["end"] <= 6.0 + 0.001

    def test_result_words_are_dicts(self):
        whisper_words = [{"word": "test", "start": 0.0, "end": 1.0}]
        marker = self._marker("test", whisper_words)
        rebuild_words_after_alignment([marker])
        for w in marker["words"]:
            assert isinstance(w, dict)


# ===========================================================================
# build_markers_from_segments — 20 tests
# ===========================================================================

class TestBuildMarkersFromSegments:
    def test_normal_segment_produces_marker(self):
        seg = MockSegment("hello world", 0.0, 2.0,
                          words=[MockWord("hello", 0.0, 0.8), MockWord("world", 1.0, 1.8)])
        result = build_markers_from_segments([seg])
        assert len(result) == 1
        assert result[0]["text"] == "hello world"

    def test_marker_has_required_fields(self):
        seg = MockSegment("test text", 1.0, 3.0,
                          words=[MockWord("test", 1.0, 1.5), MockWord("text", 1.6, 2.0)])
        result = build_markers_from_segments([seg])
        m = result[0]
        assert "time" in m
        assert "text" in m
        assert "words" in m
        assert "color" in m
        assert "end_time" in m

    def test_negative_start_clamped_to_zero(self):
        seg = MockSegment("hi there", -0.5, 2.0,
                          words=[MockWord("hi", -0.5, 0.5), MockWord("there", 0.6, 1.5)])
        result = build_markers_from_segments([seg])
        assert result[0]["time"] == 0.0

    def test_end_leq_start_skipped(self):
        seg = MockSegment("problem", 3.0, 3.0,
                          words=[MockWord("problem", 3.0, 3.0)])
        result = build_markers_from_segments([seg])
        assert len(result) == 0

    def test_end_less_than_start_skipped(self):
        seg = MockSegment("reversed", 5.0, 3.0)
        result = build_markers_from_segments([seg])
        assert len(result) == 0

    def test_segment_too_long_skipped(self):
        seg = MockSegment("very long segment", 0.0, 35.0,
                          words=[MockWord("very", 0.0, 1.0)])
        result = build_markers_from_segments([seg])
        assert len(result) == 0

    def test_segment_exactly_30s_kept(self):
        # The check is `> MAX_SEGMENT_DURATION_SEC` (strictly greater than 30),
        # so exactly 30s is NOT skipped.
        seg = MockSegment("thirty seconds", 0.0, 30.0,
                          words=[MockWord("thirty", 0.0, 1.0)])
        result = build_markers_from_segments([seg])
        assert len(result) == 1

    def test_segment_just_under_30s_kept(self):
        seg = MockSegment("twenty nine seconds", 0.0, 29.9,
                          words=[MockWord("twenty", 0.0, 1.0), MockWord("nine", 1.5, 2.0)])
        result = build_markers_from_segments([seg])
        assert len(result) == 1

    def test_no_word_level_data_fallback_even_split(self):
        seg = MockSegment("one two three", 0.0, 3.0, words=None)
        result = build_markers_from_segments([seg])
        assert len(result) == 1
        assert len(result[0]["words"]) == 3

    def test_fallback_words_evenly_spaced(self):
        seg = MockSegment("a b c", 0.0, 3.0, words=None)
        result = build_markers_from_segments([seg])
        words = result[0]["words"]
        assert words[0]["start"] == pytest.approx(0.0, abs=0.01)
        assert words[1]["start"] == pytest.approx(1.0, abs=0.01)
        assert words[2]["start"] == pytest.approx(2.0, abs=0.01)

    def test_empty_text_skipped(self):
        seg = MockSegment("", 0.0, 2.0)
        result = build_markers_from_segments([seg])
        assert len(result) == 0

    def test_short_text_skipped(self):
        seg = MockSegment("x", 0.0, 2.0)
        result = build_markers_from_segments([seg])
        assert len(result) == 0

    def test_multiple_segments_processed(self):
        segs = [
            MockSegment("first line", 0.0, 2.0,
                        words=[MockWord("first", 0.0, 0.8), MockWord("line", 0.9, 1.5)]),
            MockSegment("second line", 3.0, 5.0,
                        words=[MockWord("second", 3.0, 3.8), MockWord("line", 3.9, 4.5)]),
        ]
        result = build_markers_from_segments(segs)
        assert len(result) == 2

    def test_word_times_clamped_to_segment_bounds(self):
        seg = MockSegment("test word", 1.0, 3.0,
                          words=[MockWord("test", 0.5, 1.5), MockWord("word", 2.0, 4.0)])
        result = build_markers_from_segments([seg])
        for w in result[0]["words"]:
            assert w["start"] >= 1.0
            assert w["end"] <= 3.0

    def test_avg_logprob_stored(self):
        seg = MockSegment("hello", 0.0, 2.0, avg_logprob=-0.3,
                          words=[MockWord("hello", 0.0, 1.0)])
        result = build_markers_from_segments([seg])
        assert "avg_logprob" in result[0]

    def test_no_speech_prob_stored(self):
        seg = MockSegment("hello", 0.0, 2.0, no_speech_prob=0.05,
                          words=[MockWord("hello", 0.0, 1.0)])
        result = build_markers_from_segments([seg])
        assert "no_speech_prob" in result[0]

    def test_probability_stored_on_word(self):
        seg = MockSegment("hi", 0.0, 1.0,
                          words=[MockWord("hi", 0.0, 0.5, probability=0.95)])
        result = build_markers_from_segments([seg])
        assert "probability" in result[0]["words"][0]

    def test_empty_segments_list(self):
        result = build_markers_from_segments([])
        assert result == []

    def test_word_with_long_duration_capped(self):
        # Words > 3s duration get capped to ws + 1.0
        seg = MockSegment("long word", 0.0, 5.0,
                          words=[MockWord("long", 0.0, 4.0), MockWord("word", 4.1, 5.0)])
        result = build_markers_from_segments([seg])
        assert result[0]["words"][0]["end"] <= 1.0 + 0.001

    def test_time_rounded_to_3_decimal_places(self):
        seg = MockSegment("hi there", 1.12345, 3.67890,
                          words=[MockWord("hi", 1.12345, 2.0), MockWord("there", 2.1, 3.67890)])
        result = build_markers_from_segments([seg])
        # Should be rounded to 3 decimal places
        assert result[0]["time"] == round(1.12345, 3)
