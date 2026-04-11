"""
Tests for assets/scripts/genius_processing.py

Covers text normalization helpers and lyrics cleanup logic.
No API calls — all tests use pure string processing functions.
"""
import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before import
sys.modules.setdefault("scripts.image_processing", MagicMock())

import pytest

from scripts.genius_processing import (
    _fix_mojibake,
    _normalize_homoglyphs,
    _is_artist_title_line,
    _remove_consecutive_artist_titles,
    _clean_lyrics,
)


# ===========================================================================
# _fix_mojibake — 5 tests
# ===========================================================================

class TestFixMojibake:
    def test_em_dash_repaired(self):
        assert _fix_mojibake("with the\u00e2\u0080\u0094") == "with the\u2014"

    def test_right_single_quote_repaired(self):
        assert _fix_mojibake("don\u00e2\u0080\u0099t") == "don\u2019t"

    def test_already_correct_utf8_unchanged(self):
        text = "perfectly fine text"
        assert _fix_mojibake(text) == text

    def test_pure_ascii_unchanged(self):
        text = "hello world 123"
        assert _fix_mojibake(text) == text

    def test_unrecoverable_returns_original(self):
        # Arbitrary high-codepoint chars that can't encode as latin-1
        text = "hello \u4e16\u754c"
        assert _fix_mojibake(text) == text


# ===========================================================================
# _normalize_homoglyphs — 6 tests
# ===========================================================================

class TestNormalizeHomoglyphs:
    def test_cyrillic_e_replaced(self):
        # U+0435 (Cyrillic е) should become Latin e
        result = _normalize_homoglyphs("th\u0435 dark")
        assert result == "the dark"

    def test_multiple_cyrillic_chars(self):
        # Realistic case: long line with 2 Cyrillic chars among many Latin
        result = _normalize_homoglyphs("My friends are saying shut up Kevin just g\u0435t in th\u0435 car")
        assert result == "My friends are saying shut up Kevin just get in the car"

    def test_majority_cyrillic_not_modified(self):
        # >80% Cyrillic — leave it alone (actual Russian text)
        text = "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440"
        assert _normalize_homoglyphs(text) == text

    def test_pure_latin_unchanged(self):
        text = "hello world"
        assert _normalize_homoglyphs(text) == text

    def test_empty_string(self):
        assert _normalize_homoglyphs("") == ""

    def test_no_alpha_chars(self):
        text = "123 !@# 456"
        assert _normalize_homoglyphs(text) == text


# ===========================================================================
# _is_artist_title_line — 8 tests
# ===========================================================================

class TestIsArtistTitleLine:
    def test_simple_artist_title(self):
        assert _is_artist_title_line("LP - Lost on You") is True

    def test_multi_word_artist(self):
        assert _is_artist_title_line("The Ting Tings - Shut Up and Let Me Go") is True

    def test_artist_with_ampersand(self):
        assert _is_artist_title_line(
            "Joan Jett & The Blackhearts - Crimson and Clover"
        ) is True

    def test_artist_with_plus(self):
        assert _is_artist_title_line(
            "Florence + The Machine - Dog Days Are Over"
        ) is True

    def test_title_with_parenthetical(self):
        assert _is_artist_title_line(
            "Letters To Cleo - I Want You To Want Me (Soundtrack)"
        ) is True

    def test_lowercase_after_dash_is_not_metadata(self):
        assert _is_artist_title_line("Oh baby - why'd you leave me") is False

    def test_em_dash_is_not_metadata(self):
        assert _is_artist_title_line("Something \u2014 another thing") is False

    def test_no_dash_is_not_metadata(self):
        assert _is_artist_title_line("Just a normal lyric line") is False

    def test_single_char_sides_not_metadata(self):
        assert _is_artist_title_line("a - b") is False


# ===========================================================================
# _remove_consecutive_artist_titles — 4 tests
# ===========================================================================

class TestRemoveConsecutiveArtistTitles:
    def test_run_of_two_removed(self):
        lines = [
            "Normal lyric",
            "LP - Lost on You",
            "Annie Lennox - I Put A Spell On You",
            "Another lyric",
        ]
        result = _remove_consecutive_artist_titles(lines)
        assert result == ["Normal lyric", "Another lyric"]

    def test_single_artist_title_kept(self):
        lines = ["LP - Lost on You", "Normal lyric"]
        result = _remove_consecutive_artist_titles(lines)
        assert result == ["LP - Lost on You", "Normal lyric"]

    def test_run_of_three_removed(self):
        lines = [
            "LP - Lost on You",
            "Annie Lennox - I Put A Spell On You",
            "Florence + The Machine - Dog Days Are Over",
        ]
        result = _remove_consecutive_artist_titles(lines)
        assert result == []

    def test_empty_lines_break_run(self):
        lines = [
            "LP - Lost on You",
            "",
            "Annie Lennox - I Put A Spell On You",
        ]
        result = _remove_consecutive_artist_titles(lines)
        # Empty line breaks the run, so both singles are kept
        assert "LP - Lost on You" in result
        assert "Annie Lennox - I Put A Spell On You" in result


# ===========================================================================
# _clean_lyrics integration — 6 tests
# ===========================================================================

class TestCleanLyricsIntegration:
    def test_ymal_followed_by_artist_titles_stripped(self):
        text = (
            "Real lyric line one\n"
            "You might also like\n"
            "LP - Lost on You\n"
            "Annie Lennox - I Put A Spell On You\n"
            "Real lyric line two"
        )
        result = _clean_lyrics(text)
        assert "LP - Lost on You" not in result
        assert "Annie Lennox" not in result
        assert "Real lyric line one" in result
        assert "Real lyric line two" in result

    def test_consecutive_artist_titles_without_ymal(self):
        text = (
            "Real lyric\n"
            "LP - Lost on You\n"
            "The Ting Tings - Shut Up and Let Me Go\n"
            "Florence + The Machine - Dog Days Are Over\n"
            "Another real lyric"
        )
        result = _clean_lyrics(text)
        assert "LP - Lost on You" not in result
        assert "The Ting Tings" not in result
        assert "Florence" not in result
        assert "Real lyric" in result

    def test_single_artist_title_kept_without_ymal(self):
        text = "Some lyric\nLP - Lost on You\nAnother lyric"
        result = _clean_lyrics(text)
        assert "LP - Lost on You" in result

    def test_mojibake_repaired(self):
        # \xc3\xa2\xc2\x80\xc2\x99 is the latin-1 encoding of the UTF-8 bytes for '
        text = "don\u00e2\u0080\u0099t stop"
        result = _clean_lyrics(text)
        assert result is not None
        assert "\u00e2\u0080\u0099" not in result

    def test_homoglyphs_normalized(self):
        text = "th\u0435 dark night"  # Cyrillic е
        result = _clean_lyrics(text)
        assert result == "the dark night"

    def test_none_input(self):
        assert _clean_lyrics(None) is None

    def test_empty_input(self):
        assert _clean_lyrics("") is None


# ===========================================================================
# _wrap_line (imported from lyric_processing) — 6 tests
# ===========================================================================

class TestWrapLine:
    """Test the midpoint-based line wrapping."""

    @pytest.fixture(autouse=True)
    def _import_wrap(self):
        from scripts.lyric_processing import _wrap_line, _split_at_midpoint
        self._wrap_line = _wrap_line
        self._split_at_midpoint = _split_at_midpoint

    def test_short_line_not_wrapped(self):
        assert self._wrap_line("Hello world", limit=25) == "Hello world"

    def test_already_wrapped_unchanged(self):
        text = "first half \\r second half"
        assert self._wrap_line(text) == text

    def test_balanced_split(self):
        text = "Oh yeah yeah yeah yeah yeah yeah yeah yeah yeah yeah yeah"
        result = self._wrap_line(text, limit=25)
        assert "\\r" in result
        parts = result.split("\\r")
        first_len = len(parts[0].strip())
        second_len = len(parts[1].strip())
        # Halves should be within 15 chars of each other
        assert abs(first_len - second_len) < 15

    def test_empty_string(self):
        assert self._wrap_line("") == ""

    def test_no_spaces_splits_at_midpoint(self):
        text = "abcdefghijklmnopqrstuvwxyzabcdef"
        result = self._wrap_line(text, limit=10)
        assert "\\r" in result

    def test_recursive_wrap_three_lines(self):
        # 60 chars with limit=25 should produce 3+ lines
        text = "Oh yeah yeah yeah yeah yeah yeah yeah yeah yeah yeah yeah"
        result = self._wrap_line(text, limit=25)
        parts = result.split(" \\r ")
        assert len(parts) >= 3
        for part in parts:
            assert len(part.strip()) <= 25

    def test_recursive_wrap_all_fragments_under_limit(self):
        text = "Malcolm is in his feelings and he cannot get out of it ever"
        result = self._wrap_line(text, limit=20)
        for part in result.split(" \\r "):
            assert len(part.strip()) <= 20

    def test_midpoint_split_helper(self):
        first, rest = self._split_at_midpoint("hello beautiful world today")
        # Should split near the middle
        total = len("hello beautiful world today")
        assert abs(len(first) - len(rest)) < total // 2
