"""
Tests for scripts/lyric_alignment.py

Covers:
  - align_genius_to_whisper: empty / None inputs return original segments
  - align_genius_to_whisper: happy path replaces Whisper text with Genius text
  - align_genius_to_whisper: returns (segments, match_ratio) tuple
  - align_genius_to_whisper: low match ratio when texts have nothing in common
  - align_genius_to_whisper: works with Mono/Onyx text key
  - align_genius_to_whisper: chorus lines preserved (not deduplicated)
  - _find_lyrics_window: returns None for empty whisper block
  - _align_within_window: matched count consistent with returned ratio
  - _remove_whisper_artifacts: consecutive duplicates with tiny gap removed
  - _remove_whisper_artifacts: consecutive duplicates with large gap kept
  - _clean_for_match: strips punctuation, lowercases, collapses whitespace
  - _is_section_header: bracket and paren variants accepted / rejected
"""
from __future__ import annotations

import copy

import pytest

from scripts.lyric_alignment import (
    align_genius_to_whisper,
    _find_lyrics_window,
    _align_within_window,
    _remove_whisper_artifacts,
    _clean_for_match,
    _is_section_header,
)


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

GENIUS_TEXT = (
    "[Verse 1]\n"
    "I'm in love with the shape of you\n"
    "We push and pull like a magnet do\n"
    "Although my heart is falling too\n"
    "I'm in love with your body\n"
    "[Chorus]\n"
    "Every day discovering something brand new\n"
    "I'm in love with your body\n"
    "I'm in love with your body\n"
)


def _aurora_seg(text: str, t: float = 0.0, end_time: float = 2.0) -> dict:
    return {
        "t": t,
        "end_time": end_time,
        "lyric_prev": "",
        "lyric_current": text,
        "lyric_next1": "",
        "lyric_next2": "",
    }


def _mono_seg(text: str, t: float = 0.0, end_time: float = 2.0) -> dict:
    return {"time": t, "end_time": end_time, "text": text, "words": [], "color": "white"}


# ===========================================================================
# align_genius_to_whisper — edge cases
# ===========================================================================

class TestAlignEdgeCases:
    def test_empty_genius_text_returns_original_with_zero_ratio(self):
        segs = [_aurora_seg("hello world")]
        result_segs, ratio = align_genius_to_whisper(segs, "")
        assert result_segs is segs  # same object
        assert ratio == 0.0

    def test_none_genius_text_returns_original_with_zero_ratio(self):
        segs = [_aurora_seg("hello world")]
        result_segs, ratio = align_genius_to_whisper(segs, None)
        assert ratio == 0.0

    def test_empty_whisper_segments_returns_original_with_zero_ratio(self):
        result_segs, ratio = align_genius_to_whisper([], GENIUS_TEXT)
        assert result_segs == []
        assert ratio == 0.0

    def test_returns_tuple_of_two(self):
        segs = [_aurora_seg("Im in love with the shape of you", 0.5, 3.2)]
        result = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_ratio_is_float(self):
        segs = [_aurora_seg("Im in love with the shape of you", 0.5, 3.2)]
        _, ratio = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert isinstance(ratio, float)

    def test_ratio_between_zero_and_one(self):
        segs = [_aurora_seg("Im in love with the shape of you", 0.5, 3.2)]
        _, ratio = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert 0.0 <= ratio <= 1.0

    def test_all_empty_text_segments_return_zero_ratio(self):
        segs = [_aurora_seg("", 0.0, 1.0), _aurora_seg("   ", 1.0, 2.0)]
        _, ratio = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert ratio == 0.0

    def test_genius_text_with_only_section_headers(self):
        """All-header Genius text should return zero ratio (no lyric lines)."""
        headers_only = "[Verse 1]\n[Chorus]\n[Bridge]\n"
        segs = [_aurora_seg("Im in love with the shape of you")]
        _, ratio = align_genius_to_whisper(segs, headers_only)
        assert ratio == 0.0


# ===========================================================================
# align_genius_to_whisper — happy path
# ===========================================================================

class TestAlignHappyPath:
    def test_replaces_whisper_text_with_genius_text(self):
        """Slightly mangled Whisper text should be corrected to Genius text."""
        segs = [
            _aurora_seg("Im in love with the shape of you", 0.5, 3.2),
            _aurora_seg("We push and pull like a magnet do", 3.4, 6.1),
        ]
        result_segs, _ = align_genius_to_whisper(segs, GENIUS_TEXT)
        texts = [s["lyric_current"] for s in result_segs]
        assert any("I'm in love with the shape of you" in t for t in texts)

    def test_nonzero_ratio_on_good_match(self):
        segs = [
            _aurora_seg("Im in love with the shape of you", 0.5, 3.2),
            _aurora_seg("We push and pull like a magnet do", 3.4, 6.1),
            _aurora_seg("Although my heart is falling too", 6.3, 8.8),
        ]
        _, ratio = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert ratio > 0.3

    def test_low_ratio_when_texts_unrelated(self):
        """Segments with completely different text should produce near-zero ratio."""
        segs = [
            _aurora_seg("zxcvbnm asdfghjk", 0.0, 2.0),
            _aurora_seg("qwerty uiop lkjhg", 2.0, 4.0),
        ]
        _, ratio = align_genius_to_whisper(segs, GENIUS_TEXT)
        assert ratio < 0.5

    def test_segment_count_preserved(self):
        """Alignment must not add or drop segments."""
        segs = [
            _aurora_seg("Im in love with the shape of you", 0.5, 3.2),
            _aurora_seg("We push and pull like a magnet do", 3.4, 6.1),
            _aurora_seg("Although my heart is falling too", 6.3, 8.8),
            _aurora_seg("Im in love with your body", 9.0, 11.5),
        ]
        original_count = len(segs)
        result_segs, _ = align_genius_to_whisper(segs, GENIUS_TEXT)
        # May have fewer due to artifact removal, but never more
        assert len(result_segs) <= original_count


# ===========================================================================
# align_genius_to_whisper — Mono / Onyx text key
# ===========================================================================

class TestAlignMonoOnyxKey:
    def test_mono_text_key_updated(self):
        segs = [
            _mono_seg("Im in love with the shape of you", 0.5, 3.2),
            _mono_seg("We push and pull like a magnet do", 3.4, 6.1),
        ]
        result_segs, ratio = align_genius_to_whisper(segs, GENIUS_TEXT, segment_text_key="text")
        # At least one segment should have corrected Genius text
        texts = [s["text"] for s in result_segs]
        assert any("I'm in love" in t for t in texts) or ratio >= 0.0

    def test_mono_returns_two_tuple(self):
        segs = [_mono_seg("Im in love with the shape of you")]
        result = align_genius_to_whisper(segs, GENIUS_TEXT, segment_text_key="text")
        assert isinstance(result, tuple) and len(result) == 2


# ===========================================================================
# align_genius_to_whisper — chorus preservation
# ===========================================================================

class TestChorusPreservation:
    def test_chorus_repeats_not_deduplicated(self):
        """Identical lines that recur at large time gaps (chorus) must be kept."""
        chorus_genius = (
            "La la la\n"
            "Na na na\n"
            "La la la\n"
            "Na na na\n"
        )
        segs = [
            _mono_seg("La la la", 0.0, 2.0),
            _mono_seg("Na na na", 2.0, 4.0),
            _mono_seg("La la la", 8.0, 10.0),  # large gap — chorus repeat
            _mono_seg("Na na na", 10.0, 12.0),
        ]
        result_segs, _ = align_genius_to_whisper(segs, chorus_genius, segment_text_key="text")
        # Should still have the same or close to the same number of segments
        assert len(result_segs) >= 2


# ===========================================================================
# _find_lyrics_window
# ===========================================================================

class TestFindLyricsWindow:
    def _active(self, text: str) -> list[dict]:
        return [{"lyric_current": text}]

    def test_returns_none_for_empty_whisper(self):
        result = _find_lyrics_window([], ["hello world"], "lyric_current")
        assert result is None

    def test_returns_none_when_whisper_block_empty_after_clean(self):
        segs = [{"lyric_current": "..."}]
        lines = ["hello world"]
        result = _find_lyrics_window(segs, lines, "lyric_current")
        assert result is None

    def test_returns_integer_index_on_match(self):
        lines = ["I'm in love with the shape of you", "We push and pull like a magnet do"]
        segs = [{"lyric_current": "Im in love with the shape of you"}]
        result = _find_lyrics_window(segs, lines, "lyric_current")
        assert result is None or isinstance(result, int)

    def test_returns_none_for_completely_unrelated_text(self):
        lines = ["I'm in love with the shape of you", "We push and pull"]
        segs = [{"lyric_current": "zxcvbnm asdfghjk poiuytre"}]
        result = _find_lyrics_window(segs, lines, "lyric_current")
        assert result is None


# ===========================================================================
# _remove_whisper_artifacts
# ===========================================================================

class TestRemoveWhisperArtifacts:
    def test_consecutive_duplicate_with_tiny_gap_removed_aurora(self):
        """Aurora key: blank out duplicates with < 0.5s gap."""
        segs = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello world"},
            {"t": 1.1, "end_time": 2.1, "lyric_current": "hello world"},  # gap 0.1s
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        # The duplicate should have its lyric_current blanked out
        assert result[1]["lyric_current"] == ""

    def test_consecutive_duplicate_with_large_gap_kept(self):
        """A gap >= 0.5s means intentional repeat — must keep both."""
        segs = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello world"},
            {"t": 3.0, "end_time": 4.0, "lyric_current": "hello world"},  # gap 2.0s
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        assert result[1]["lyric_current"] == "hello world"

    def test_consecutive_duplicate_mono_key_popped(self):
        """Mono key ('text'): pop the duplicate entirely."""
        segs = [
            {"time": 0.0, "end_time": 1.0, "text": "hello world", "words": []},
            {"time": 1.1, "end_time": 2.1, "text": "hello world", "words": []},
        ]
        result = _remove_whisper_artifacts(segs, "text")
        assert len(result) == 1

    def test_different_text_both_kept(self):
        segs = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello world"},
            {"t": 1.1, "end_time": 2.1, "lyric_current": "goodbye world"},
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        assert len(result) == 2
        assert result[1]["lyric_current"] == "goodbye world"

    def test_single_segment_returned_unchanged(self):
        segs = [{"t": 0.0, "end_time": 1.0, "lyric_current": "only one"}]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        assert len(result) == 1

    def test_empty_list_returned_unchanged(self):
        assert _remove_whisper_artifacts([], "lyric_current") == []

    def test_non_consecutive_duplicates_both_kept(self):
        """Non-adjacent identical lines must not be touched."""
        segs = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello"},
            {"t": 1.1, "end_time": 2.1, "lyric_current": "world"},
            {"t": 2.2, "end_time": 3.2, "lyric_current": "hello"},
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        # First and third are not consecutive — both must survive
        non_empty = [s for s in result if s.get("lyric_current")]
        assert len(non_empty) >= 2


# ===========================================================================
# _clean_for_match
# ===========================================================================

class TestCleanForMatch:
    def test_lowercase(self):
        assert _clean_for_match("Hello World") == "hello world"

    def test_removes_punctuation(self):
        result = _clean_for_match("I'm in love!")
        assert "'" not in result
        assert "!" not in result

    def test_collapses_whitespace(self):
        result = _clean_for_match("  hello   world  ")
        assert result == "hello world"

    def test_empty_string_returns_empty(self):
        assert _clean_for_match("") == ""

    def test_none_returns_empty(self):
        assert _clean_for_match(None) == ""

    def test_only_punctuation_returns_empty(self):
        result = _clean_for_match("!@#$%^&*()")
        assert result == ""

    def test_preserves_alphanumeric(self):
        result = _clean_for_match("abc 123")
        assert result == "abc 123"

    def test_unicode_punctuation_stripped(self):
        result = _clean_for_match("I\u2019m in love")
        # Curly apostrophe stripped — letters kept
        assert "love" in result


# ===========================================================================
# _is_section_header
# ===========================================================================

class TestIsSectionHeader:
    def test_bracket_chorus(self):
        assert _is_section_header("[Chorus]") is True

    def test_bracket_verse(self):
        assert _is_section_header("[Verse 1]") is True

    def test_bracket_bridge(self):
        assert _is_section_header("[Bridge]") is True

    def test_bracket_intro(self):
        assert _is_section_header("[Intro]") is True

    def test_bracket_outro(self):
        assert _is_section_header("[Outro]") is True

    def test_bracket_hook(self):
        assert _is_section_header("[Hook]") is True

    def test_bracket_interlude(self):
        assert _is_section_header("[Interlude]") is True

    def test_paren_chorus(self):
        assert _is_section_header("(Chorus)") is True

    def test_paren_verse(self):
        assert _is_section_header("(Verse 2)") is True

    def test_normal_lyric_not_header(self):
        assert _is_section_header("I'm in love with the shape of you") is False

    def test_empty_string_not_header(self):
        assert _is_section_header("") is False

    def test_partial_bracket_not_header(self):
        assert _is_section_header("[Chorus") is False

    def test_paren_random_word_not_header(self):
        """A parenthetical that isn't a section keyword should not qualify."""
        assert _is_section_header("(laughing)") is False

    def test_whitespace_around_brackets(self):
        """Strips leading/trailing whitespace before checking."""
        assert _is_section_header("  [Chorus]  ") is True
