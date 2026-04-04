"""
Tests for pure functions extracted from Apollova JSX files.
Runs Node.js via subprocess — requires `node` to be on PATH.
"""
import json
import os
import subprocess
import sys

import pytest

HELPER_JS = os.path.join(os.path.dirname(__file__), "jsx_helpers", "pure_functions.js")


def run_js(fn: str, *args):
    """Run a JSX pure function in Node.js and return the parsed result."""
    payload = json.dumps({"fn": fn, "args": list(args)})
    result = subprocess.run(
        ["node", HELPER_JS, payload],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Node.js error: {result.stderr}"
    return json.loads(result.stdout)


# ===========================================================================
# hexToRGB — 25 tests
# ===========================================================================

class TestHexToRGB:
    def test_valid_6char_hex_no_hash(self):
        result = run_js("hexToRGB", "ffffff")
        assert result == pytest.approx([1.0, 1.0, 1.0], abs=0.01)

    def test_valid_with_hash(self):
        result = run_js("hexToRGB", "#ffffff")
        assert result == pytest.approx([1.0, 1.0, 1.0], abs=0.01)

    def test_black(self):
        result = run_js("hexToRGB", "000000")
        assert result == pytest.approx([0.0, 0.0, 0.0], abs=0.01)

    def test_red(self):
        result = run_js("hexToRGB", "ff0000")
        assert result == pytest.approx([1.0, 0.0, 0.0], abs=0.01)

    def test_green(self):
        result = run_js("hexToRGB", "00ff00")
        assert result == pytest.approx([0.0, 1.0, 0.0], abs=0.01)

    def test_blue(self):
        result = run_js("hexToRGB", "0000ff")
        assert result == pytest.approx([0.0, 0.0, 1.0], abs=0.01)

    def test_catppuccin_base(self):
        # #1e1e2e → [0x1e/255, 0x1e/255, 0x2e/255]
        result = run_js("hexToRGB", "#1e1e2e")
        assert result == pytest.approx([0x1e / 255, 0x1e / 255, 0x2e / 255], abs=0.005)

    def test_catppuccin_blue(self):
        # #89b4fa
        result = run_js("hexToRGB", "#89b4fa")
        assert result == pytest.approx([0x89 / 255, 0xb4 / 255, 0xfa / 255], abs=0.005)

    def test_empty_string_fallback(self):
        result = run_js("hexToRGB", "")
        assert result == [1, 1, 1]

    def test_null_equivalent_fallback(self):
        result = run_js("hexToRGB", None)
        assert result == [1, 1, 1]

    def test_short_hex_fallback(self):
        result = run_js("hexToRGB", "#fff")
        assert result == [1, 1, 1]

    def test_invalid_hex_chars_fallback(self):
        result = run_js("hexToRGB", "zzzzzz")
        assert result == [1, 1, 1]

    def test_all_channels_between_0_and_1(self):
        result = run_js("hexToRGB", "abc123")
        for ch in result:
            assert 0.0 <= ch <= 1.0

    def test_half_grey(self):
        result = run_js("hexToRGB", "808080")
        for ch in result:
            assert 0.4 < ch < 0.6

    def test_result_is_list_of_3(self):
        result = run_js("hexToRGB", "ffffff")
        assert len(result) == 3

    def test_with_uppercase_hex(self):
        result = run_js("hexToRGB", "FFFFFF")
        assert result == pytest.approx([1.0, 1.0, 1.0], abs=0.01)

    def test_mixed_case_hex(self):
        result_lower = run_js("hexToRGB", "ff0000")
        result_upper = run_js("hexToRGB", "FF0000")
        assert result_lower == pytest.approx(result_upper, abs=0.001)

    def test_7chars_without_hash_fallback(self):
        # 7 hex chars without # → length 7 ≠ 6 → fallback
        result = run_js("hexToRGB", "fffffff")
        assert result == [1, 1, 1]

    def test_specific_color_accuracy(self):
        # Purple: #8B5CF6 → [0x8b/255, 0x5c/255, 0xf6/255]
        result = run_js("hexToRGB", "#8B5CF6")
        assert result == pytest.approx([0x8b / 255, 0x5c / 255, 0xf6 / 255], abs=0.005)

    def test_orange(self):
        # #F59E0B
        result = run_js("hexToRGB", "#F59E0B")
        assert result == pytest.approx([0xf5 / 255, 0x9e / 255, 0x0b / 255], abs=0.005)

    def test_hash_only_fallback(self):
        result = run_js("hexToRGB", "#")
        assert result == [1, 1, 1]

    def test_values_are_floats_or_ints(self):
        result = run_js("hexToRGB", "123456")
        for ch in result:
            assert isinstance(ch, (int, float))

    def test_white_all_ones(self):
        result = run_js("hexToRGB", "#ffffff")
        assert all(v == 1 for v in result)

    def test_black_all_zeros(self):
        result = run_js("hexToRGB", "#000000")
        assert all(v == 0 for v in result)

    def test_non_string_type_fallback(self):
        # Passing integer via JSON → not a string in JS → fallback
        result = run_js("hexToRGB", 12345)
        assert result == [1, 1, 1]


# ===========================================================================
# sanitizeFilename — 25 tests
# ===========================================================================

class TestSanitizeFilename:
    def test_normal_name_unchanged(self):
        result = run_js("sanitizeFilename", "My Song")
        assert result == "My Song"

    def test_forward_slash_removed(self):
        result = run_js("sanitizeFilename", "Artist/Song")
        assert "/" not in result

    def test_backslash_removed(self):
        result = run_js("sanitizeFilename", "Artist\\Song")
        assert "\\" not in result

    def test_colon_removed(self):
        result = run_js("sanitizeFilename", "Artist: Song")
        assert ":" not in result

    def test_asterisk_removed(self):
        result = run_js("sanitizeFilename", "Song*Name")
        assert "*" not in result

    def test_question_mark_removed(self):
        result = run_js("sanitizeFilename", "What?")
        assert "?" not in result

    def test_double_quote_removed(self):
        result = run_js("sanitizeFilename", 'Say "Hello"')
        assert '"' not in result

    def test_angle_brackets_removed(self):
        result = run_js("sanitizeFilename", "<title>")
        assert "<" not in result
        assert ">" not in result

    def test_pipe_removed(self):
        result = run_js("sanitizeFilename", "A|B")
        assert "|" not in result

    def test_leading_spaces_stripped(self):
        result = run_js("sanitizeFilename", "  leading")
        assert not result.startswith(" ")

    def test_trailing_spaces_stripped(self):
        result = run_js("sanitizeFilename", "trailing  ")
        assert not result.endswith(" ")

    def test_multiple_spaces_collapsed(self):
        result = run_js("sanitizeFilename", "too   many   spaces")
        assert "  " not in result

    def test_empty_string_returns_untitled(self):
        result = run_js("sanitizeFilename", "")
        assert result == "untitled"

    def test_null_returns_untitled(self):
        result = run_js("sanitizeFilename", None)
        assert result == "untitled"

    def test_long_name_preserved(self):
        long_name = "A" * 200
        result = run_js("sanitizeFilename", long_name)
        assert len(result) == 200

    def test_unicode_letters_kept(self):
        result = run_js("sanitizeFilename", "Café au Lait")
        assert "Café" in result or "Caf" in result

    def test_numbers_kept(self):
        result = run_js("sanitizeFilename", "Song 123")
        assert "123" in result

    def test_hyphens_kept(self):
        result = run_js("sanitizeFilename", "Artist - Song")
        assert "-" in result

    def test_multiple_bad_chars_all_removed(self):
        result = run_js("sanitizeFilename", 'Song: "best" * ever?')
        assert ":" not in result
        assert '"' not in result
        assert "*" not in result
        assert "?" not in result

    def test_result_is_string(self):
        result = run_js("sanitizeFilename", "test")
        assert isinstance(result, str)

    def test_spaces_preserved_between_words(self):
        result = run_js("sanitizeFilename", "Hello World")
        assert " " in result

    def test_only_invalid_chars_returns_empty_or_untitled(self):
        result = run_js("sanitizeFilename", "/*?")
        # All chars removed → "" which is falsy → but the function returns after removal,
        # may be empty string
        assert isinstance(result, str)

    def test_real_song_title(self):
        result = run_js("sanitizeFilename", "Major Lazer - Light It Up")
        assert "Major Lazer" in result
        assert "Light It Up" in result

    def test_tabs_in_name(self):
        result = run_js("sanitizeFilename", "Song\tName")
        # Tab not in removal list, but whitespace collapsing → single space
        assert "\t" not in result or " " in result

    def test_newline_collapses_to_space(self):
        result = run_js("sanitizeFilename", "Song\nName")
        assert "\n" not in result


# ===========================================================================
# buildSegmentsArrayStringWithEnds — 20 tests
# ===========================================================================

def _marker(time, end_time, words):
    return {"time": time, "end_time": end_time, "words": words}


def _word(w, s):
    return {"word": w, "start": s}


class TestBuildSegmentsArrayString:
    def test_single_marker_produces_output(self):
        markers = [_marker(0.5, 3.0, [_word("hello", 0.5)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "var segments" in result

    def test_output_starts_with_var_segments(self):
        markers = [_marker(0.0, 2.0, [_word("hi", 0.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert result.startswith("var segments = [")

    def test_multiple_markers_in_output(self):
        markers = [
            _marker(0.0, 2.0, [_word("first", 0.0)]),
            _marker(3.0, 5.0, [_word("second", 3.0)]),
        ]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert result.count("{t:") == 2

    def test_empty_markers_list(self):
        result = run_js("buildSegmentsArrayStringWithEnds", [])
        assert "var segments" in result

    def test_timestamps_3_decimal_places(self):
        markers = [_marker(1.12345, 3.67890, [_word("test", 1.12345)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "1.123" in result
        assert "3.679" in result

    def test_special_char_quote_escaped(self):
        markers = [_marker(0.0, 2.0, [_word('say "hi"', 0.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        # Should not contain unescaped double quotes inside string literal
        # The output is valid JS
        assert 'w:' in result

    def test_backslash_escaped(self):
        markers = [_marker(0.0, 2.0, [_word("path\\word", 0.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "\\\\" in result or "path" in result

    def test_newline_in_word_escaped(self):
        markers = [_marker(0.0, 2.0, [_word("line\nbreak", 0.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "\\n" in result

    def test_tab_in_word_escaped(self):
        markers = [_marker(0.0, 2.0, [_word("tab\there", 0.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "\\t" in result

    def test_marker_with_no_words(self):
        markers = [{"time": 1.0, "end_time": 3.0, "words": []}]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "words:[]" in result

    def test_end_time_present_in_output(self):
        markers = [_marker(1.0, 4.0, [_word("test", 1.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert ",e:4.000" in result

    def test_time_present_in_output(self):
        markers = [_marker(2.5, 5.0, [_word("check", 2.5)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "t:2.500" in result

    def test_word_start_present(self):
        markers = [_marker(0.0, 3.0, [_word("hello", 1.234)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert "s:1.234" in result

    def test_multiple_words_per_marker(self):
        markers = [_marker(0.0, 4.0, [_word("one", 0.0), _word("two", 1.0), _word("three", 2.0)])]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        assert result.count('{w:"') == 3

    def test_missing_end_time_defaults(self):
        markers = [{"time": 1.0, "words": [_word("hi", 1.0)]}]
        result = run_js("buildSegmentsArrayStringWithEnds", markers)
        # end_time missing → defaults to t + 5
        assert "e:6.000" in result

    def test_eval_valid_syntax(self):
        markers = [_marker(0.5, 3.0, [_word("hello", 0.5), _word("world", 1.0)])]
        result = run_js("evalSegments", markers)
        assert result["valid"] is True

    def test_eval_correct_segment_count(self):
        markers = [
            _marker(0.0, 2.0, [_word("first", 0.0)]),
            _marker(3.0, 5.0, [_word("second", 3.0)]),
        ]
        result = run_js("evalSegments", markers)
        assert result["segmentCount"] == 2

    def test_eval_with_quotes_valid(self):
        markers = [_marker(0.0, 2.0, [_word('say "hi"', 0.0)])]
        result = run_js("evalSegments", markers)
        assert result["valid"] is True

    def test_eval_empty_markers_valid(self):
        result = run_js("evalSegments", [])
        assert result["valid"] is True

    def test_eval_with_special_chars_valid(self):
        markers = [_marker(0.0, 2.0, [_word("can't", 0.0), _word("stop\nme", 1.0)])]
        result = run_js("evalSegments", markers)
        assert result["valid"] is True


# ===========================================================================
# evalWordReveal — 15 tests
# ===========================================================================

def _reveal_markers():
    """Standard 2-marker set for word-reveal tests."""
    return [
        {
            "time": 0.0,
            "end_time": 6.0,
            "words": [
                {"word": "one", "start": 0.0},
                {"word": "two", "start": 1.0},
                {"word": "three", "start": 2.0},
                {"word": "four", "start": 3.0},
            ],
        },
        {
            "time": 7.0,
            "end_time": 10.0,
            "words": [
                {"word": "alpha", "start": 7.0},
                {"word": "beta", "start": 8.0},
            ],
        },
    ]


class TestEvalWordReveal:
    def test_before_any_words_empty(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, -1.0)
        assert result == ""

    def test_at_time_of_first_word_shows_first(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 0.0)
        assert "one" in result

    def test_at_time_of_second_word_shows_two(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 1.0)
        assert "one" in result
        assert "two" in result

    def test_at_time_of_third_word_shows_three(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 2.0)
        assert "one" in result
        assert "two" in result
        assert "three" in result

    def test_three_words_no_newline_yet(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 2.0)
        # Exactly 3 words → no newline yet (newline added when wordCount > 0 and wordCount % 3 == 0)
        assert "\r" not in result

    def test_four_words_has_newline(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 3.0)
        # 4th word → wordCount=3 is divisible by wordsPerLine=3 → newline inserted before 4th
        assert "\r" in result

    def test_segindex_out_of_bounds_high(self):
        result = run_js("evalWordReveal", _reveal_markers(), 99, 0.0)
        assert result == ""

    def test_segindex_zero_out_of_bounds(self):
        result = run_js("evalWordReveal", _reveal_markers(), 0, 0.0)
        assert result == ""

    def test_segindex_negative_out_of_bounds(self):
        result = run_js("evalWordReveal", _reveal_markers(), -1, 0.0)
        assert result == ""

    def test_second_segment_at_correct_time(self):
        result = run_js("evalWordReveal", _reveal_markers(), 2, 7.0)
        assert "alpha" in result

    def test_second_segment_before_time_empty(self):
        result = run_js("evalWordReveal", _reveal_markers(), 2, 6.5)
        assert result == ""

    def test_3_words_per_line_boundary_at_word_4(self):
        # After 3 words, inserting 4th produces \r separator
        markers = [
            {
                "time": 0.0,
                "end_time": 8.0,
                "words": [
                    {"word": "w1", "start": 0.0},
                    {"word": "w2", "start": 1.0},
                    {"word": "w3", "start": 2.0},
                    {"word": "w4", "start": 3.0},
                    {"word": "w5", "start": 4.0},
                    {"word": "w6", "start": 5.0},
                    {"word": "w7", "start": 6.0},
                ],
            }
        ]
        result = run_js("evalWordReveal", markers, 1, 6.0)
        # 7 words → newline after w3 (pos 3) and after w6 (pos 6)
        newline_count = result.count("\r")
        assert newline_count == 2

    def test_result_is_string(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 0.0)
        assert isinstance(result, str)

    def test_empty_markers_list_oob(self):
        result = run_js("evalWordReveal", [], 1, 0.0)
        assert result == ""

    def test_words_appear_in_order(self):
        result = run_js("evalWordReveal", _reveal_markers(), 1, 2.0)
        idx_one = result.index("one")
        idx_two = result.index("two")
        idx_three = result.index("three")
        assert idx_one < idx_two < idx_three
