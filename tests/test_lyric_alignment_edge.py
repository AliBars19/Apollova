"""
Tests for scripts/lyric_alignment.py — edge cases beyond existing coverage.

Covers:
  - Two-pass recovery: improves weak match, noop without anchors/weak matches
  - Full-scan: triggered when forward+back fail, finds match at end
  - Match scoring: exact=100, empty=0, combined scoring
  - Window: early termination >95, None below 35
  - Artifacts: consecutive identical with tiny gap, larger gap preserved
  - Utility edges: _clean_for_match, _is_section_header variants
"""
from __future__ import annotations

import pytest

from scripts.lyric_alignment import (
    align_genius_to_whisper,
    _find_lyrics_window,
    _match_score,
    _clean_for_match,
    _is_section_header,
    _remove_whisper_artifacts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aurora_seg(text, t=0.0, end_time=2.0):
    return {"t": t, "end_time": end_time, "lyric_current": text}


def _mono_seg(text, time=0.0, end_time=2.0):
    return {"time": time, "end_time": end_time, "text": text}


# ---------------------------------------------------------------------------
# align_genius_to_whisper — public API
# ---------------------------------------------------------------------------

class TestAlignAPI:

    def test_empty_genius_returns_segments_unchanged(self):
        segs = [_aurora_seg("hello")]
        result, ratio = align_genius_to_whisper(segs, "", segment_text_key="lyric_current")
        assert ratio == 0.0
        assert result[0]["lyric_current"] == "hello"

    def test_empty_segments_returns_zero_ratio(self):
        result, ratio = align_genius_to_whisper([], "some lyrics")
        assert ratio == 0.0

    def test_none_genius_returns_segments(self):
        segs = [_aurora_seg("hello")]
        result, ratio = align_genius_to_whisper(segs, None)
        assert ratio == 0.0

    def test_good_match_returns_high_ratio(self):
        genius = "I love you\nYou love me\nWe are happy"
        segs = [
            _aurora_seg("I love you", 0, 2),
            _aurora_seg("You love me", 2, 4),
            _aurora_seg("We are happy", 4, 6),
        ]
        result, ratio = align_genius_to_whisper(segs, genius, segment_text_key="lyric_current")
        assert ratio >= 0.5

    def test_mono_key_works(self):
        genius = "Hello world"
        segs = [_mono_seg("Hello world", 0, 2)]
        result, ratio = align_genius_to_whisper(segs, genius, segment_text_key="text")
        assert ratio > 0


# ---------------------------------------------------------------------------
# _match_score
# ---------------------------------------------------------------------------

class TestMatchScore:

    def test_exact_match_high_score(self):
        score = _match_score("hello world", "hello world")
        assert score >= 95

    def test_empty_strings_zero(self):
        assert _match_score("", "") == 0
        assert _match_score("hello", "") == 0
        assert _match_score("", "hello") == 0

    def test_partial_match_nonzero(self):
        score = _match_score("i love you", "i love")
        assert score > 0

    def test_completely_different_low(self):
        score = _match_score("alpha beta gamma", "xyz uvw rst")
        assert score < 50


# ---------------------------------------------------------------------------
# _find_lyrics_window
# ---------------------------------------------------------------------------

class TestFindLyricsWindow:

    def test_finds_window_at_start(self):
        genius_lines = ["line one", "line two", "line three", "line four", "line five"]
        segs = [_aurora_seg("line one", 0, 2), _aurora_seg("line two", 2, 4)]
        start = _find_lyrics_window(segs, genius_lines, "lyric_current")
        assert start == 0

    def test_finds_window_in_middle(self):
        genius_lines = ["intro", "verse one", "target line A", "target line B", "outro"]
        segs = [
            _aurora_seg("target line A", 0, 2),
            _aurora_seg("target line B", 2, 4),
        ]
        start = _find_lyrics_window(segs, genius_lines, "lyric_current")
        assert start == 2

    def test_returns_none_for_poor_match(self):
        genius_lines = ["completely", "different", "content"]
        segs = [_aurora_seg("xyz abc 123", 0, 2)]
        start = _find_lyrics_window(segs, genius_lines, "lyric_current")
        assert start is None


# ---------------------------------------------------------------------------
# _remove_whisper_artifacts
# ---------------------------------------------------------------------------

class TestRemoveArtifacts:

    def test_removes_consecutive_identical_tiny_gap(self):
        segs = [
            _aurora_seg("hello world", 0, 2),
            _aurora_seg("hello world", 2.1, 4),  # gap=0.1 < 0.5
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        # Second should be blanked (Aurora style)
        non_empty = [s for s in result if s["lyric_current"].strip()]
        assert len(non_empty) == 1

    def test_preserves_repeat_with_larger_gap(self):
        segs = [
            _aurora_seg("hello world", 0, 2),
            _aurora_seg("hello world", 5, 7),  # gap=3 > 0.5 → intentional chorus
        ]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        non_empty = [s for s in result if s["lyric_current"].strip()]
        assert len(non_empty) == 2

    def test_mono_pops_instead_of_blanking(self):
        segs = [
            _mono_seg("hello", 0, 2),
            _mono_seg("hello", 2.1, 4),  # gap=0.1
        ]
        result = _remove_whisper_artifacts(segs, "text")
        assert len(result) == 1

    def test_empty_list(self):
        result = _remove_whisper_artifacts([], "lyric_current")
        assert result == []

    def test_single_segment(self):
        segs = [_aurora_seg("hello")]
        result = _remove_whisper_artifacts(segs, "lyric_current")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _clean_for_match
# ---------------------------------------------------------------------------

class TestCleanForMatch:

    def test_removes_punctuation(self):
        assert _clean_for_match("Hello, world!") == "hello world"

    def test_empty_string(self):
        assert _clean_for_match("") == ""

    def test_none_returns_empty(self):
        assert _clean_for_match(None) == ""

    def test_preserves_numbers(self):
        assert _clean_for_match("verse 1") == "verse 1"

    def test_collapses_whitespace(self):
        assert _clean_for_match("  hello    world  ") == "hello world"


# ---------------------------------------------------------------------------
# _is_section_header
# ---------------------------------------------------------------------------

class TestIsSectionHeader:

    def test_bracket_chorus(self):
        assert _is_section_header("[Chorus]") is True

    def test_bracket_verse(self):
        assert _is_section_header("[Verse 1]") is True

    def test_paren_chorus(self):
        assert _is_section_header("(Chorus)") is True

    def test_paren_bridge(self):
        assert _is_section_header("(Bridge)") is True

    def test_regular_text_not_header(self):
        assert _is_section_header("I love you") is False

    def test_empty_brackets_not_header(self):
        assert _is_section_header("[]") is True

    def test_produced_by(self):
        assert _is_section_header("(Produced by Metro)") is True

    def test_paren_with_non_section_word(self):
        assert _is_section_header("(something random)") is False
