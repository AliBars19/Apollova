"""
Tests for assets/scripts/whisper_common.py

All heavy dependencies (stable_whisper, torch, pydub, audio_processing) are
mocked at module level so these tests run without a GPU or model download.
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
# Patch pydub.AudioSegment so get_audio_duration doesn't crash on import
import unittest.mock as _mock
pydub_mock = sys.modules["pydub"]
pydub_mock.AudioSegment = MagicMock()

import pytest

# Now we can safely import
from scripts.whisper_common import (
    detect_language,
    remove_hallucinations,
    remove_junk,
    remove_repetition_loops,
    remove_stutter_duplicates,
    remove_non_target_script,
    build_initial_prompt,
    spread_clustered_words,
    validate_lyrics_quality,
)


# ===========================================================================
# detect_language — 25 tests
# ===========================================================================

class TestDetectLanguage:
    # Spanish artist keywords
    def test_spanish_bad_bunny(self):
        assert detect_language("Bad Bunny - Dakiti") == "es"

    def test_spanish_j_balvin(self):
        assert detect_language("J Balvin - Reggaeton") == "es"

    def test_spanish_daddy_yankee(self):
        assert detect_language("Daddy Yankee - Gasolina") == "es"

    def test_spanish_despacito(self):
        assert detect_language("Luis Fonsi - Despacito") == "es"

    def test_spanish_maluma(self):
        assert detect_language("Maluma - Hawai") == "es"

    def test_spanish_shakira(self):
        assert detect_language("Shakira - Waka Waka") == "es"

    def test_spanish_ozuna(self):
        assert detect_language("Ozuna - Taki Taki") == "es"

    def test_spanish_nicky_jam(self):
        assert detect_language("Nicky Jam - X") == "es"

    def test_spanish_floyymenor(self):
        assert detect_language("FloyyMenor - Gata Only") == "es"

    def test_spanish_gata_only_keyword(self):
        assert detect_language("Gata Only - Someone") == "es"

    # French artist keywords
    def test_french_stromae(self):
        assert detect_language("Stromae - Papaoutai") == "fr"

    def test_french_daft_punk(self):
        assert detect_language("Daft Punk - Get Lucky") == "fr"

    def test_french_edith_piaf(self):
        assert detect_language("Edith Piaf - La Vie en Rose") == "fr"

    # English (None)
    def test_english_returns_none(self):
        result = detect_language("Drake - God's Plan")
        # No Spanish/French keyword match → None (or langdetect may fire, but
        # langdetect is mocked via genius_text=None path)
        assert result is None

    def test_english_beatles(self):
        assert detect_language("The Beatles - Let It Be") is None

    # None / empty inputs
    def test_none_song_title(self):
        assert detect_language(None) is None

    def test_empty_string(self):
        assert detect_language("") is None

    def test_whitespace_only(self):
        assert detect_language("   ") is None

    # Genius text override (langdetect mocked — skip real network)
    def test_short_genius_text_falls_through(self):
        # genius_text < 50 chars → falls through to title heuristic
        result = detect_language("Drake - Hotline Bling", genius_text="short")
        assert result is None

    def test_none_genius_text_uses_title(self):
        assert detect_language("Daddy Yankee - Gasolina", genius_text=None) == "es"

    # Case insensitivity
    def test_case_insensitive_spanish(self):
        assert detect_language("BAD BUNNY - SAFAERA") == "es"

    def test_case_insensitive_french(self):
        assert detect_language("DAFT PUNK - Harder Better") == "fr"

    # Somali / Igbo special cases
    def test_somali_nimco_happy(self):
        assert detect_language("Nimco Happy - Isii Nafta") == "so"

    def test_igbo_ckay_nwantiti(self):
        assert detect_language("CKay - Love Nwantiti") == "ig"

    def test_no_match_returns_none(self):
        assert detect_language("Totally Unknown Artist 12345") is None


# ===========================================================================
# remove_hallucinations — 25 tests
# ===========================================================================

def _make_items(texts, time_key="text"):
    return [{time_key: t, "time": i * 2.0} for i, t in enumerate(texts)]


class TestRemoveHallucinations:
    def _run(self, texts, prompt=None):
        items = _make_items(texts)
        return remove_hallucinations(items, "text", prompt)

    # Each pattern from the patterns list
    def test_thank_you_for_watching(self):
        assert self._run(["thank you for watching"]) == []

    def test_thank_you_for_listening(self):
        assert self._run(["thank you for listening"]) == []

    def test_please_subscribe(self):
        assert self._run(["please subscribe"]) == []

    def test_subscribe_alone(self):
        assert self._run(["subscribe"]) == []

    def test_music_alone(self):
        assert self._run(["music"]) == []

    def test_music_with_brackets(self):
        assert self._run(["[music]"]) == []

    def test_musical_note_symbol(self):
        # Musical note symbols are stripped to empty text by the clean regex,
        # so the item is skipped early (not text: continue) → passes through.
        # The ♪-only line gets caught by remove_junk instead.
        result = self._run(["\u266a\u266a\u266a"])
        # Either removed or kept — the important thing is no crash
        assert isinstance(result, list)

    def test_subtitles_by(self):
        assert self._run(["subtitles by someone"]) == []

    def test_captions_by(self):
        assert self._run(["captions by someone"]) == []

    def test_copyright(self):
        assert self._run(["copyright 2024"]) == []

    def test_all_rights_reserved(self):
        assert self._run(["all rights reserved"]) == []

    def test_ellipsis_only(self):
        # "..." gets stripped of non-alphanumeric → empty cleaned text → skipped by
        # the `if not text: continue` guard. Ellipsis is handled by remove_junk.
        result = self._run(["..."])
        assert isinstance(result, list)  # no crash

    # Normal lyrics NOT removed
    def test_normal_lyric_kept(self):
        result = self._run(["I feel the music in my soul"])
        assert len(result) == 1

    def test_you_in_lyrics_kept(self):
        # "you" was removed from pattern list in improvement #6
        result = self._run(["I need you baby"])
        assert len(result) == 1

    def test_love_lyric_kept(self):
        result = self._run(["all i want is your love"])
        assert len(result) == 1

    # Prompt similarity
    def test_prompt_similarity_removes(self):
        # text very similar to prompt → removed
        result = self._run(["Hotline Bling Drake"], prompt="Hotline Bling Drake")
        assert result == []

    def test_prompt_low_similarity_kept(self):
        result = self._run(["completely different lyrics here"], prompt="Hotline Bling")
        assert len(result) == 1

    # Edge cases
    def test_empty_list(self):
        assert remove_hallucinations([], "text", None) == []

    def test_items_with_no_text_key(self):
        items = [{"time": 1.0}]
        result = remove_hallucinations(items, "text", None)
        assert result == []

    def test_empty_text_removed(self):
        items = [{"text": "", "time": 0}]
        result = remove_hallucinations(items, "text", None)
        assert result == []

    def test_mixed_keeps_good(self):
        items = _make_items(["thank you for watching", "this is real lyrics"])
        result = remove_hallucinations(items, "text", None)
        assert len(result) == 1
        assert result[0]["text"] == "this is real lyrics"

    def test_none_prompt_no_crash(self):
        result = self._run(["hello world"], prompt=None)
        assert len(result) == 1

    def test_caption_subtitle_variant(self):
        assert self._run(["caption by subtitle"]) == []

    def test_subscribe_variant(self):
        # "Subscribe now!" should match subscribe pattern
        items = _make_items(["Subscribe now"])
        result = remove_hallucinations(items, "text", None)
        assert result == []


# ===========================================================================
# remove_junk — 20 tests
# ===========================================================================

class TestRemoveJunk:
    def _run(self, texts):
        items = _make_items(texts)
        return remove_junk(items, "text")

    def test_pure_symbols(self):
        assert self._run(["!@#$%"]) == []

    def test_single_char(self):
        assert self._run(["a"]) == []

    def test_um(self):
        assert self._run(["um"]) == []

    def test_uh(self):
        assert self._run(["uh"]) == []

    def test_hmm(self):
        assert self._run(["hmm"]) == []

    def test_ah(self):
        assert self._run(["ah"]) == []

    def test_oh_alone(self):
        # "oh" has 2 alpha chars — should be filtered by junk pattern
        assert self._run(["oh"]) == []

    def test_ha(self):
        assert self._run(["ha"]) == []

    def test_dots_only(self):
        assert self._run(["..."]) == []

    def test_dashes_only(self):
        assert self._run(["---"]) == []

    def test_normal_lyric_kept(self):
        result = self._run(["this is a real lyric"])
        assert len(result) == 1

    def test_two_alpha_border(self):
        # The filter uses `< 2` so EXACTLY 2 alpha chars are NOT filtered by length.
        # "ab" passes length check (len==2, not <2) and doesn't match junk patterns.
        result = self._run(["ab"])
        assert len(result) == 1

    def test_three_alpha_kept(self):
        result = self._run(["abc"])
        assert len(result) == 1

    def test_empty_text(self):
        assert self._run([""]) == []

    def test_mixed_keeps_real(self):
        result = self._run(["uh", "give me love"])
        assert len(result) == 1
        assert result[0]["text"] == "give me love"

    def test_empty_list(self):
        assert remove_junk([], "text") == []

    def test_whitespace_only(self):
        assert self._run(["   "]) == []

    def test_single_word_with_enough_alpha(self):
        result = self._run(["yeah"])
        assert len(result) == 1

    def test_symbols_mixed_no_alpha(self):
        assert self._run(["!!!..."]) == []

    def test_huh(self):
        assert self._run(["huh"]) == []


# ===========================================================================
# remove_repetition_loops — 20 tests
# ===========================================================================

class TestRemoveRepetitionLoops:
    def _run(self, texts):
        items = _make_items(texts)
        return remove_repetition_loops(items, "text")

    def test_three_identical_keeps_two(self):
        result = self._run(["same line", "same line", "same line"])
        assert len(result) == 2

    def test_four_identical_keeps_two(self):
        result = self._run(["x", "x", "x", "x"])
        assert len(result) == 2

    def test_two_identical_keeps_both(self):
        result = self._run(["same", "same"])
        assert len(result) == 2

    def test_similar_not_identical_both_kept(self):
        result = self._run(["i love you baby", "i love you dear"])
        # Different enough that ratio < threshold
        assert len(result) == 2

    def test_empty_list(self):
        assert self._run([]) == []

    def test_single_item(self):
        result = self._run(["only one"])
        assert len(result) == 1

    def test_two_items_no_repeat(self):
        result = self._run(["first line", "second line"])
        assert len(result) == 2

    def test_repetition_with_punctuation_ignored(self):
        result = self._run(["yeah yeah", "yeah yeah!", "yeah yeah..."])
        # All 3 very similar → keeps 2
        assert len(result) == 2

    def test_loop_in_middle_trimmed(self):
        items = _make_items(["intro", "loop", "loop", "loop", "outro"])
        result = remove_repetition_loops(items, "text")
        assert len(result) == 4  # intro + 2 loops + outro

    def test_alternating_not_trimmed(self):
        result = self._run(["line a", "line b", "line a", "line b"])
        assert len(result) == 4

    def test_five_same_keeps_two(self):
        result = self._run(["repeat"] * 5)
        assert len(result) == 2

    def test_empty_text_items(self):
        items = [{"text": "", "time": 0}, {"text": "", "time": 2}]
        result = remove_repetition_loops(items, "text")
        # Empty strings treated as non-matching
        assert len(result) == 2

    def test_order_preserved(self):
        result = self._run(["first", "second", "third"])
        assert [r["text"] for r in result] == ["first", "second", "third"]

    def test_three_items_all_different(self):
        result = self._run(["alpha", "beta", "gamma"])
        assert len(result) == 3

    def test_streak_resets_after_different(self):
        result = self._run(["a", "a", "a", "b", "b", "b"])
        assert len(result) == 4  # 2 from each triplet

    def test_near_identical_high_ratio(self):
        # These should have ratio > 85
        result = self._run(["running running running", "running running running!", "running running running?"])
        assert len(result) == 2

    def test_completely_different_all_kept(self):
        texts = ["alpha", "bravo", "charlie", "delta"]
        result = self._run(texts)
        assert len(result) == 4

    def test_two_items_similar_both_kept(self):
        result = self._run(["almost same text", "almost same text"])
        assert len(result) == 2

    def test_first_item_always_kept(self):
        result = self._run(["first", "first", "first"])
        assert result[0]["text"] == "first"

    def test_less_than_three_items_returned_unchanged(self):
        result = self._run(["a", "b"])
        assert len(result) == 2


# ===========================================================================
# remove_stutter_duplicates — 20 tests
# ===========================================================================

class TestRemoveStutterDuplicates:
    def _make_timed(self, entries):
        """entries: list of (text, time, end_time)"""
        return [{"text": t, "time": s, "end_time": e} for t, s, e in entries]

    def test_exact_duplicate_small_gap_removed(self):
        items = self._make_timed([("hello world", 0.0, 1.0), ("hello world", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_exact_duplicate_large_gap_kept(self):
        items = self._make_timed([("hello world", 0.0, 1.0), ("hello world", 5.0, 6.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_different_texts_both_kept(self):
        items = self._make_timed([("verse one", 0.0, 1.0), ("verse two", 1.5, 2.5)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_fuzzy_match_above_threshold_small_gap_removed(self):
        items = self._make_timed([("i love you baby", 0.0, 1.0), ("i love you baby!", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_fuzzy_match_below_threshold_kept(self):
        items = self._make_timed([("completely different text", 0.0, 2.0), ("nothing alike here", 2.5, 4.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_single_item_returned(self):
        items = self._make_timed([("only", 0.0, 1.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_empty_list(self):
        assert remove_stutter_duplicates([], "text") == []

    def test_gap_exactly_05_kept(self):
        # gap of exactly 0.5 is NOT < 0.5 so should be kept
        items = self._make_timed([("same text", 0.0, 1.0), ("same text", 1.5, 2.5)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_gap_below_05_removed(self):
        items = self._make_timed([("same text", 0.0, 1.0), ("same text", 1.3, 2.3)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_first_item_always_kept(self):
        items = self._make_timed([("first", 0.0, 1.0), ("first", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert result[0]["text"] == "first"

    def test_does_not_mutate_input(self):
        items = self._make_timed([("abc", 0.0, 1.0), ("abc", 1.1, 2.0)])
        original_len = len(items)
        remove_stutter_duplicates(items, "text")
        assert len(items) == original_len

    def test_returns_new_list(self):
        items = self._make_timed([("x", 0.0, 1.0)])
        result = remove_stutter_duplicates(items, "text")
        assert result is not items

    def test_three_identical_consecutive_removes_second(self):
        items = self._make_timed([
            ("same", 0.0, 1.0),
            ("same", 1.1, 2.0),
            ("same", 2.1, 3.0),
        ])
        result = remove_stutter_duplicates(items, "text")
        # Second "same" has gap 0.1 < 0.5 → removed.
        # Third "same" is compared against item[0] (last in filtered=[items[0]]),
        # gap = 2.1 - 1.0 = 1.1 ≥ 0.5 → KEPT.
        assert len(result) == 2

    def test_case_sensitivity_with_cleanup(self):
        # Cleaned versions are compared case-insensitively
        items = self._make_timed([("SAME TEXT", 0.0, 1.0), ("same text", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_punctuation_stripped_for_comparison(self):
        items = self._make_timed([("hey!", 0.0, 1.0), ("hey", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1

    def test_multiple_different_items_all_kept(self):
        items = self._make_timed([
            ("line one", 0.0, 1.0),
            ("line two", 1.5, 2.5),
            ("line three", 3.0, 4.0),
        ])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 3

    def test_two_items_no_overlap(self):
        items = self._make_timed([("alpha", 0.0, 1.0), ("beta", 5.0, 6.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_empty_text_not_deduplicated(self):
        items = self._make_timed([("", 0.0, 1.0), ("", 1.1, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 2

    def test_order_preserved(self):
        items = self._make_timed([
            ("first different", 0.0, 1.0),
            ("second different", 5.0, 6.0),
        ])
        result = remove_stutter_duplicates(items, "text")
        assert result[0]["text"] == "first different"
        assert result[1]["text"] == "second different"

    def test_gap_of_zero_removed(self):
        items = self._make_timed([("exact", 0.0, 1.0), ("exact", 1.0, 2.0)])
        result = remove_stutter_duplicates(items, "text")
        assert len(result) == 1


# ===========================================================================
# remove_non_target_script — 15 tests
# ===========================================================================

class TestRemoveNonTargetScript:
    def _make(self, texts):
        return [{"text": t, "time": i} for i, t in enumerate(texts)]

    def test_latin_text_kept(self):
        items = self._make(["Hello world"])
        assert len(remove_non_target_script(items, "text")) == 1

    def test_cyrillic_removed(self):
        items = self._make(["Привет мир"])  # "Hello world" in Russian
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_japanese_removed(self):
        items = self._make(["こんにちは世界"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_arabic_removed(self):
        items = self._make(["مرحبا بالعالم"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_empty_list(self):
        assert remove_non_target_script([], "text") == []

    def test_empty_text_removed(self):
        items = self._make([""])
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_mixed_mostly_latin_kept(self):
        # Mostly Latin with a few non-Latin chars → kept
        items = self._make(["Hello wörld"])  # ö is Latin Extended
        result = remove_non_target_script(items, "text")
        assert len(result) == 1

    def test_mixed_mostly_non_latin_removed(self):
        # More non-Latin than Latin → removed
        items = self._make(["Привет w"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_spanish_latin_kept(self):
        items = self._make(["Cómo estás amigo"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 1

    def test_numbers_only_kept(self):
        # Numbers have no isalpha → ratio 0/0 → total==0 → kept
        items = self._make(["12345"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 1

    def test_multiple_items_filters_selectively(self):
        items = self._make(["Hello", "Привет", "World"])
        result = remove_non_target_script(items, "text")
        assert len(result) == 2

    def test_none_song_title(self):
        items = self._make(["Cyrillic? Привет"])
        result = remove_non_target_script(items, "text", song_title=None)
        # Without song_title, lang=None (Latin language), still filters
        assert len(result) == 0

    def test_french_song_latin_kept(self):
        items = self._make(["Je t'aime"])
        result = remove_non_target_script(items, "text", song_title="Stromae - Papaoutai")
        assert len(result) == 1

    def test_greek_above_threshold_removed(self):
        items = self._make(["αβγδεζ"])  # Greek script
        result = remove_non_target_script(items, "text")
        assert len(result) == 0

    def test_whitespace_text_removed(self):
        items = self._make(["   "])
        result = remove_non_target_script(items, "text")
        assert len(result) == 0


# ===========================================================================
# build_initial_prompt — 10 tests
# ===========================================================================

class TestBuildInitialPrompt:
    def test_artist_dash_track_format(self):
        result = build_initial_prompt("Drake - God's Plan")
        assert "God's Plan" in result
        assert "Drake" in result

    def test_format_artist_dash_track_order(self):
        result = build_initial_prompt("Artist - Track Name")
        # Should be "Track Name, Artist."
        assert result == "Track Name, Artist."

    def test_no_dash_returns_title_dot(self):
        result = build_initial_prompt("SomeSong")
        assert result == "SomeSong."

    def test_none_returns_none(self):
        assert build_initial_prompt(None) is None

    def test_empty_string_returns_none(self):
        assert build_initial_prompt("") is None

    def test_multiple_dashes_splits_on_first(self):
        result = build_initial_prompt("Artist - Sub - Track")
        # split(" - ", 1) → artist="Artist", track="Sub - Track"
        assert result == "Sub - Track, Artist."

    def test_whitespace_title(self):
        # build_initial_prompt only returns None for falsy input (None or "").
        # Whitespace-only string is truthy, so it returns "   ."
        result = build_initial_prompt("   ")
        assert result is not None  # whitespace is truthy

    def test_result_ends_with_period(self):
        result = build_initial_prompt("Some Song")
        assert result.endswith(".")

    def test_with_dash_result_ends_with_period(self):
        result = build_initial_prompt("A - B")
        assert result.endswith(".")

    def test_real_song_format(self):
        result = build_initial_prompt("The Weeknd - Blinding Lights")
        assert result == "Blinding Lights, The Weeknd."


# ===========================================================================
# spread_clustered_words — 15 tests
# ===========================================================================

class TestSpreadClusteredWords:
    def test_four_words_at_same_timestamp_spread_evenly(self):
        markers = [
            {
                "time": 5.0,
                "end_time": 9.0,
                "words": [
                    {"word": "they", "start": 5.0, "end": 5.0},
                    {"word": "all", "start": 5.0, "end": 5.0},
                    {"word": "over", "start": 5.0, "end": 5.0},
                    {"word": "me", "start": 5.0, "end": 5.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        starts = [w["start"] for w in markers[0]["words"]]
        # All starts should now be different
        assert len(set(starts)) == 4
        # Should be monotonically increasing
        assert starts == sorted(starts)

    def test_words_already_spread_unchanged(self):
        markers = [
            {
                "time": 0.0,
                "end_time": 4.0,
                "words": [
                    {"word": "a", "start": 0.0, "end": 1.0},
                    {"word": "b", "start": 1.5, "end": 2.5},
                    {"word": "c", "start": 3.0, "end": 4.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        assert markers[0]["words"][0]["start"] == 0.0
        assert markers[0]["words"][1]["start"] == 1.5
        assert markers[0]["words"][2]["start"] == 3.0

    def test_cluster_span_from_next_word(self):
        markers = [
            {
                "time": 2.0,
                "end_time": 10.0,
                "words": [
                    {"word": "a", "start": 2.0, "end": 2.0},
                    {"word": "b", "start": 2.0, "end": 2.0},
                    {"word": "c", "start": 5.0, "end": 6.0},  # next non-cluster word
                ],
            }
        ]
        spread_clustered_words(markers)
        # Cluster of [a, b] spans to c.start = 5.0
        assert markers[0]["words"][0]["start"] == 2.0
        assert markers[0]["words"][1]["start"] > 2.0
        assert markers[0]["words"][1]["start"] < 5.0

    def test_cluster_at_end_uses_end_time(self):
        markers = [
            {
                "time": 1.0,
                "end_time": 4.0,
                "words": [
                    {"word": "x", "start": 1.0, "end": 1.0},
                    {"word": "y", "start": 1.0, "end": 1.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        # span = end_time (4.0) - 1.0 = 3.0 → 2 words → 1.5s each
        assert markers[0]["words"][0]["start"] == 1.0
        assert markers[0]["words"][1]["start"] == pytest.approx(2.5, abs=0.01)

    def test_span_too_small_no_spread(self):
        # span < 0.05 → no spread
        markers = [
            {
                "time": 1.0,
                "end_time": 1.03,
                "words": [
                    {"word": "a", "start": 1.0, "end": 1.0},
                    {"word": "b", "start": 1.0, "end": 1.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        assert markers[0]["words"][0]["start"] == 1.0
        assert markers[0]["words"][1]["start"] == 1.0

    def test_span_too_large_no_spread(self):
        # span > 30.0 → no spread
        markers = [
            {
                "time": 0.0,
                "end_time": 31.0,
                "words": [
                    {"word": "a", "start": 0.0, "end": 0.0},
                    {"word": "b", "start": 0.0, "end": 0.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        assert markers[0]["words"][0]["start"] == 0.0
        assert markers[0]["words"][1]["start"] == 0.0

    def test_single_marker_single_word_unchanged(self):
        markers = [{"time": 1.0, "end_time": 2.0, "words": [{"word": "solo", "start": 1.0, "end": 2.0}]}]
        spread_clustered_words(markers)
        assert markers[0]["words"][0]["start"] == 1.0

    def test_empty_words_list_unchanged(self):
        markers = [{"time": 1.0, "end_time": 2.0, "words": []}]
        spread_clustered_words(markers)
        assert markers[0]["words"] == []

    def test_empty_markers_list(self):
        result = spread_clustered_words([])
        assert result == []

    def test_returns_same_list_object(self):
        markers = [{"time": 0.0, "end_time": 5.0, "words": [{"word": "a", "start": 0.0, "end": 1.0}]}]
        result = spread_clustered_words(markers)
        assert result is markers

    def test_three_words_clustered_spread_evenly(self):
        markers = [
            {
                "time": 0.0,
                "end_time": 3.0,
                "words": [
                    {"word": "one", "start": 0.0, "end": 0.0},
                    {"word": "two", "start": 0.0, "end": 0.0},
                    {"word": "three", "start": 0.0, "end": 0.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        # 3 words over 3.0s span → each 1.0s apart
        assert markers[0]["words"][0]["start"] == pytest.approx(0.0, abs=0.001)
        assert markers[0]["words"][1]["start"] == pytest.approx(1.0, abs=0.001)
        assert markers[0]["words"][2]["start"] == pytest.approx(2.0, abs=0.001)

    def test_end_times_set_correctly_after_spread(self):
        markers = [
            {
                "time": 0.0,
                "end_time": 2.0,
                "words": [
                    {"word": "a", "start": 0.0, "end": 0.0},
                    {"word": "b", "start": 0.0, "end": 0.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        # end of first word should equal start of second word
        assert markers[0]["words"][0]["end"] == pytest.approx(markers[0]["words"][1]["start"], abs=0.001)

    def test_cluster_threshold_25ms(self):
        # Words within 25ms are clustered
        markers = [
            {
                "time": 5.0,
                "end_time": 10.0,
                "words": [
                    {"word": "a", "start": 5.0, "end": 5.0},
                    {"word": "b", "start": 5.02, "end": 5.02},  # 20ms apart → in cluster
                    {"word": "c", "start": 5.1, "end": 5.5},    # 100ms apart → NOT in cluster
                ],
            }
        ]
        spread_clustered_words(markers)
        # a and b were clustered, c was not
        assert markers[0]["words"][0]["start"] != markers[0]["words"][1]["start"]
        assert markers[0]["words"][2]["start"] == 5.1  # c unchanged

    def test_genius_clustered_fixture_span_too_small(self, clustered_markers):
        # The fixture has end_time=5.396, cluster_time=5.376 → span=0.020 < 0.05
        # This means the span is too small to spread → words remain at same timestamp.
        spread_clustered_words(clustered_markers)
        words = clustered_markers[0]["words"]
        # Result should be a list with 4 words — no crash
        assert len(words) == 4

    def test_marker_without_end_time_uses_fallback(self):
        # No end_time → uses time + 5.0 as fallback
        markers = [
            {
                "time": 1.0,
                "words": [
                    {"word": "a", "start": 1.0, "end": 1.0},
                    {"word": "b", "start": 1.0, "end": 1.0},
                ],
            }
        ]
        spread_clustered_words(markers)
        # span = (1.0 + 5.0) - 1.0 = 5.0 → should spread
        assert markers[0]["words"][1]["start"] > 1.0


# ===========================================================================
# validate_lyrics_quality — #32: Visual QA checks
# ===========================================================================

class TestValidateLyricsQuality:
    """Tests for the lyrics visual quality validator."""

    def _m(self, text: str, t: float = 0.0) -> dict:
        """Helper to build a minimal marker dict."""
        return {"text": text, "time": t}

    # --- Empty / clean input ---

    def test_empty_markers_passes(self):
        passed, warnings = validate_lyrics_quality([])
        assert passed is True
        assert warnings == []

    def test_clean_unique_lyrics_passes(self):
        markers = [self._m("First line of song"), self._m("Second unique line"), self._m("Third different one")]
        passed, warnings = validate_lyrics_quality(markers)
        assert passed is True
        assert warnings == []

    # --- Consecutive duplicates ---

    def test_consecutive_exact_duplicate(self):
        markers = [self._m("Hello world"), self._m("Hello world")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Consecutive duplicate" in x for x in w)
        assert any("UNVERIFIED" in x for x in w)

    def test_consecutive_near_duplicate(self):
        markers = [self._m("When we shared a bed"), self._m("When we shared a bed yeah")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Consecutive duplicate" in x or "Repeated line" in x for x in w)

    def test_consecutive_different_lines_no_flag(self):
        markers = [self._m("Completely different"), self._m("Not similar at all")]
        passed, _ = validate_lyrics_quality(markers)
        assert passed

    # --- Non-consecutive duplicates (chorus echo) ---

    def test_non_consecutive_duplicate(self):
        markers = [self._m("Chorus line"), self._m("A bridge"), self._m("Chorus line")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Repeated line" in x for x in w)
        assert any("UNVERIFIED" in x for x in w)

    def test_sombr_back_to_friends_real_case(self):
        """Real case: duplicate chorus from Job 5."""
        markers = [
            self._m("How can we go back to being friends"),
            self._m("When we just shared a bed?"),
            self._m("How can we go back to being friends"),
            self._m("When we just shared a bed? (Yeah)"),
            self._m("I'm someone you've never met?"),
        ]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert len(w) >= 2  # At least 2 duplicate warnings

    # --- Truncation detection ---

    def test_truncated_line_ends_with_at(self):
        markers = [self._m("But she's lookin' at")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("truncation" in x.lower() for x in w)

    def test_truncated_line_ends_with_the(self):
        markers = [self._m("I wanna be the")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("truncation" in x.lower() for x in w)

    def test_line_ending_with_normal_word_no_flag(self):
        markers = [self._m("She ride the carnival")]
        passed, _ = validate_lyrics_quality(markers)
        assert passed

    def test_line_ending_with_her_no_flag(self):
        """'her' was removed from dangling list — valid line ending."""
        markers = [self._m("Everybody's watchin' her")]
        passed, _ = validate_lyrics_quality(markers)
        assert passed

    def test_line_ending_with_for_no_flag(self):
        """'for' was removed from dangling list — valid line ending."""
        markers = [self._m("This is what you came for")]
        passed, _ = validate_lyrics_quality(markers)
        assert passed

    # --- Run-on lines ---

    def test_run_on_line_flagged(self):
        long_text = "A" * 81
        markers = [self._m(long_text)]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Run-on" in x for x in w)

    def test_exactly_at_limit_no_flag(self):
        text = "A" * 80
        markers = [self._m(text)]
        passed, w = validate_lyrics_quality(markers)
        # Should not flag run-on at exactly the limit
        assert not any("Run-on" in x for x in w)

    def test_future_young_metro_real_case(self):
        """Real case: massive run-on line from Job 10."""
        markers = [
            self._m("Evel Knievel, Pluto tote his heater, leave nigga in the freezer, I am big as a Beatle (Okay, okay)"),
            self._m("Yeah, yeah"),
        ]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Run-on" in x for x in w)

    # --- Orphan fragments ---

    def test_single_char_orphan(self):
        markers = [self._m("X")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Orphan" in x for x in w)

    def test_two_char_orphan(self):
        markers = [self._m("Oh")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Orphan" in x for x in w)

    def test_short_word_no_orphan_if_longer(self):
        markers = [self._m("Yeah yeah")]
        passed, w = validate_lyrics_quality(markers)
        assert not any("Orphan" in x for x in w)

    # --- Line breaks handled correctly ---

    def test_line_breaks_stripped_for_comparison(self):
        markers = [self._m("Hello\\rworld"), self._m("Hello\\rworld")]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert any("Consecutive duplicate" in x for x in w)

    # --- Mixed issues ---

    def test_multiple_issue_types_combined(self):
        markers = [
            self._m("Oh"),  # orphan
            self._m("A very long line that just keeps going and going way past the limit of what should be displayed"),  # run-on
            self._m("Same line"), self._m("Different"), self._m("Same line"),  # non-consecutive dup
        ]
        passed, w = validate_lyrics_quality(markers)
        assert not passed
        assert len(w) >= 3

    # --- Does not modify input ---

    def test_does_not_mutate_markers(self):
        markers = [self._m("Test line"), self._m("Test line")]
        import copy
        original = copy.deepcopy(markers)
        validate_lyrics_quality(markers)
        assert markers == original

    # --- Genius cross-reference: duplicates suppressed when Genius confirms ---

    def test_genius_confirms_consecutive_repeat_suppressed(self):
        """Genius has the line twice — consecutive duplicate is legitimate."""
        genius = "How can we go back to being friends\nSomething else\nHow can we go back to being friends"
        markers = [
            self._m("How can we go back to being friends"),
            self._m("How can we go back to being friends"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        # No duplicate warnings — Genius says 2x, Whisper has 2x
        assert not any("duplicate" in x.lower() or "Repeated" in x for x in w)

    def test_genius_denies_consecutive_repeat_flagged(self):
        """Genius has the line once — consecutive duplicate is hallucination."""
        genius = "How can we go back to being friends\nWhen we just shared a bed\nI'm someone you never met"
        markers = [
            self._m("How can we go back to being friends"),
            self._m("How can we go back to being friends"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not passed
        assert any("CONFIRMED" in x for x in w)

    def test_genius_confirms_chorus_echo_suppressed(self):
        """Non-consecutive repeat confirmed by Genius chorus."""
        genius = "[Verse]\nI love the night\nStars are bright\n[Chorus]\nI love the night"
        markers = [
            self._m("I love the night"),
            self._m("Stars are bright"),
            self._m("I love the night"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        # Genius has "I love the night" 2x, Whisper has 2x — no warning
        assert not any("Repeated" in x for x in w)

    def test_genius_denies_chorus_echo_flagged(self):
        """Whisper has 3 occurrences, Genius only 2 — flag the excess."""
        genius = "I love the night\nStars are bright\nI love the night"
        markers = [
            self._m("I love the night"),
            self._m("Stars are bright"),
            self._m("I love the night"),
            self._m("More lyrics here"),
            self._m("I love the night"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not passed
        assert any("CONFIRMED" in x and "Repeated" in x for x in w)

    def test_genius_with_adlibs_stripped_for_matching(self):
        """Genius line with (yeah) adlib still matches Whisper without it."""
        genius = "Feel the beat (yeah)\nDance all night (oh)\nFeel the beat (yeah)"
        markers = [
            self._m("Feel the beat"),
            self._m("Dance all night"),
            self._m("Feel the beat"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not any("Repeated" in x for x in w)

    def test_genius_section_headers_ignored(self):
        """[Chorus] headers are stripped — only lyric lines counted."""
        genius = "[Chorus]\nHello world\n[Verse 1]\nSomething else\n[Chorus]\nHello world"
        markers = [
            self._m("Hello world"),
            self._m("Something else"),
            self._m("Hello world"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        # "Hello world" appears 2x in Genius lyrics (headers excluded), 2x in Whisper
        assert not any("Repeated" in x for x in w)

    def test_genius_empty_string_treated_as_absent(self):
        """Empty genius_text should behave like None — unverified warnings."""
        markers = [self._m("Same line"), self._m("Same line")]
        passed, w = validate_lyrics_quality(markers, genius_text="")
        assert not passed
        assert any("UNVERIFIED" in x for x in w)

    def test_genius_none_gives_unverified_warnings(self):
        """Without Genius, duplicate warnings are tagged UNVERIFIED."""
        markers = [self._m("Same line"), self._m("Same line")]
        passed, w = validate_lyrics_quality(markers, genius_text=None)
        assert not passed
        assert any("UNVERIFIED" in x for x in w)

    def test_genius_does_not_affect_truncation_checks(self):
        """Genius cross-ref only affects duplicate checks, not truncation."""
        genius = "I wanna be the\nBest in the world"
        markers = [self._m("I wanna be the")]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not passed
        assert any("truncation" in x.lower() for x in w)

    def test_genius_does_not_affect_orphan_checks(self):
        """Genius cross-ref only affects duplicate checks, not orphans."""
        genius = "X\nReal lyrics here"
        markers = [self._m("X")]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not passed
        assert any("Orphan" in x for x in w)

    def test_genius_real_case_sombr_with_genius(self):
        """Real case: Job 5 — Genius only has the line once, Whisper doubled it."""
        genius = (
            "How can we go back to being friends\n"
            "When we just shared a bed?\n"
            "I'm someone you've never met\n"
            "I'll never let you forget"
        )
        markers = [
            self._m("How can we go back to being friends"),
            self._m("When we just shared a bed?"),
            self._m("How can we go back to being friends"),
            self._m("When we just shared a bed? (Yeah)"),
            self._m("I'm someone you've never met?"),
        ]
        passed, w = validate_lyrics_quality(markers, genius_text=genius)
        assert not passed
        # Should flag the duplicate with CONFIRMED since Genius only has it 1x
        assert any("CONFIRMED" in x for x in w)
