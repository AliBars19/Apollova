"""
Tests for whisper_common.rebuild_words_after_alignment edge cases.

Covers:
  - Skip conditions: empty genius text, no whisper words, texts already match
  - Fuzzy matching: apostrophe variants, fewer/equal/more genius words, punctuation stripped
  - Used-set prevents double mapping, single word marker, large word count mismatch
"""
from __future__ import annotations

import pytest

from scripts.whisper_common import rebuild_words_after_alignment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _marker(text, time=0.0, end_time=3.0, words=None):
    """Build a minimal marker dict."""
    if words is None:
        # Auto-generate word timings
        tokens = text.split()
        dur = end_time - time
        wd = dur / len(tokens) if tokens else dur
        words = [
            {"word": w, "start": round(time + i * wd, 3), "end": round(time + (i + 1) * wd, 3)}
            for i, w in enumerate(tokens)
        ]
    return {"time": time, "end_time": end_time, "text": text, "words": words}


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

class TestSkipConditions:

    def test_empty_genius_text_skips(self):
        """Marker with empty text → words unchanged."""
        m = _marker("", words=[{"word": "hello", "start": 0, "end": 1}])
        result = rebuild_words_after_alignment([m])
        assert result[0]["words"] == [{"word": "hello", "start": 0, "end": 1}]

    def test_no_whisper_words_skips(self):
        """Marker with no words → nothing to remap."""
        m = _marker("hello world", words=[])
        result = rebuild_words_after_alignment([m])
        assert result[0]["words"] == []

    def test_texts_already_match_skips(self):
        """When genius text matches whisper words joined, skip rebuild."""
        m = _marker("I love you", time=0, end_time=3.0)
        # Words already match the text
        result = rebuild_words_after_alignment([m])
        # words should be unchanged
        assert len(result[0]["words"]) == 3
        assert result[0]["words"][0]["word"] == "I"


# ---------------------------------------------------------------------------
# Fuzzy matching (fewer/equal genius words)
# ---------------------------------------------------------------------------

class TestFuzzyMatching:

    def test_apostrophe_variants_match(self):
        """'Im' should fuzzy-match 'I'm'."""
        m = _marker("I'm in love", words=[
            {"word": "Im", "start": 0.0, "end": 0.5},
            {"word": "in", "start": 0.5, "end": 1.0},
            {"word": "love", "start": 1.0, "end": 1.5},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert words[0]["word"] == "I'm"
        assert words[1]["word"] == "in"
        assert words[2]["word"] == "love"

    def test_fewer_genius_words(self):
        """Genius has fewer words than Whisper → fuzzy map subset."""
        m = _marker("hello world", words=[
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "beautiful", "start": 0.5, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 1.5},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert len(words) == 2
        assert words[0]["word"] == "hello"
        assert words[1]["word"] == "world"

    def test_equal_genius_words(self):
        """Same count → one-to-one fuzzy mapping."""
        m = _marker("running fast here", words=[
            {"word": "runnin", "start": 0.0, "end": 0.5},
            {"word": "fast", "start": 0.5, "end": 1.0},
            {"word": "here", "start": 1.0, "end": 1.5},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert len(words) == 3
        assert words[0]["word"] == "running"

    def test_punctuation_stripped_for_matching(self):
        """Punctuation shouldn't prevent a match."""
        m = _marker("Hello, world!", words=[
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert words[0]["word"] == "Hello,"
        assert words[1]["word"] == "world!"


# ---------------------------------------------------------------------------
# More genius words → even distribution
# ---------------------------------------------------------------------------

class TestMoreGeniusWords:

    def test_more_genius_words_distributes_evenly(self):
        """When genius has more words than whisper, distribute across time span."""
        m = _marker("I am in love with you", time=0.0, end_time=3.0, words=[
            {"word": "Im", "start": 0.0, "end": 1.0},
            {"word": "in", "start": 1.0, "end": 2.0},
            {"word": "love", "start": 2.0, "end": 3.0},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        # 6 genius words > 3 whisper words → even distribution
        assert len(words) == 6
        assert words[0]["word"] == "I"
        assert words[-1]["word"] == "you"
        # Evenly spaced: each word gets 0.5s
        assert abs(words[1]["start"] - 0.5) < 0.01


# ---------------------------------------------------------------------------
# Used-set and edge cases
# ---------------------------------------------------------------------------

class TestUsedSetAndEdges:

    def test_used_set_prevents_double_mapping(self):
        """Each whisper word should only be used once."""
        m = _marker("go go go", words=[
            {"word": "go", "start": 0.0, "end": 0.5},
            {"word": "go", "start": 0.5, "end": 1.0},
            {"word": "go", "start": 1.0, "end": 1.5},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert len(words) == 3
        # Each should map to a different whisper word's timing
        starts = [w["start"] for w in words]
        assert len(set(starts)) == 3  # all different

    def test_single_word_marker(self):
        """Single word in both genius and whisper."""
        m = _marker("Yeah", words=[
            {"word": "Yeh", "start": 0.0, "end": 0.5},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert len(words) == 1
        assert words[0]["word"] == "Yeah"

    def test_large_word_count_mismatch(self):
        """Many more genius words than whisper → even distribution."""
        genius_text = " ".join(f"word{i}" for i in range(20))
        m = _marker(genius_text, time=0.0, end_time=10.0, words=[
            {"word": "w0", "start": 0.0, "end": 5.0},
            {"word": "w1", "start": 5.0, "end": 10.0},
        ])
        result = rebuild_words_after_alignment([m])
        words = result[0]["words"]
        assert len(words) == 20

    def test_multiple_markers_processed(self):
        """All markers in the list are processed, not just the first."""
        m1 = _marker("I'm fine", words=[
            {"word": "Im", "start": 0.0, "end": 0.5},
            {"word": "fine", "start": 0.5, "end": 1.0},
        ])
        m2 = _marker("You're great", time=1.0, end_time=2.0, words=[
            {"word": "Youre", "start": 1.0, "end": 1.5},
            {"word": "great", "start": 1.5, "end": 2.0},
        ])
        result = rebuild_words_after_alignment([m1, m2])
        assert result[0]["words"][0]["word"] == "I'm"
        assert result[1]["words"][0]["word"] == "You're"
