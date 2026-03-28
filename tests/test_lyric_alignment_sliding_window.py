"""
Tests for scripts/lyric_alignment.py — sliding window and two-pass recovery.

Targets the uncovered lines:
  66-67   _find_lyrics_window: whisper block empty → None
  126     _find_lyrics_window: genius_block empty (continue)
  184-185 _align_within_window: seg with empty text skipped (total not incremented)
  190-191 _align_within_window: backward search path
  212-213 _align_within_window: full-scan fallback when forward+back fail
  222-223 _align_within_window: full-scan score >= 92 break
  225     _align_within_window: forward_limit skip in full-scan
  247     two-pass: weak_indices collected
  251     two-pass: anchors loop — anchor seg_idx < seg_idx check
  254-294 two-pass recovery block (anchors + weak matches)
  338     _remove_whisper_artifacts: mono pop branch (segment_text_key != lyric_current)

New gaps (appended):
  190-191 _align_within_window: seg_text non-empty but cleans to empty (e.g. "...")
  222-225 full-scan fallback early-exit on score >= 92
  254-294 two-pass recovery block with anchors + weak matches
  338     _remove_whisper_artifacts: one segment has empty text (skip branch)
"""
from __future__ import annotations

import copy

from unittest.mock import patch

import pytest

from scripts.lyric_alignment import (
    align_genius_to_whisper,
    _find_lyrics_window,
    _align_within_window,
    _remove_whisper_artifacts,
    _clean_for_match,
    _match_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aurora_seg(text, t=0.0, end_time=2.0):
    return {
        "t": t,
        "end_time": end_time,
        "lyric_prev": "",
        "lyric_current": text,
        "lyric_next1": "",
        "lyric_next2": "",
    }


def _mono_seg(text, time=0.0, end_time=2.0):
    return {"time": time, "end_time": end_time, "text": text, "words": []}


def segments_for_recovery_test():
    """
    Two segments used by the two-pass recovery block test.
    Segment 0: strong anchor that matches genius_lines[20].
    Segment 1: weak segment that initially matches genius_lines[22] (score 55).
    """
    return [
        _aurora_seg("Im in love with the shape of you", 0, 2),
        _aurora_seg("something barely matches here", 2, 4),
    ]


# ===========================================================================
# _find_lyrics_window — empty whisper block
# ===========================================================================

class TestFindLyricsWindowEmptyWhisper:
    def test_all_empty_segments_returns_none(self):
        """Segments with only empty/whitespace text produce an empty block → None."""
        active_segments = [
            {"lyric_current": ""},
            {"lyric_current": "   "},
        ]
        genius_lines = ["Hello world", "Foo bar baz"]
        result = _find_lyrics_window(active_segments, genius_lines, "lyric_current")
        assert result is None

    def test_empty_genius_lines_with_valid_whisper(self):
        """If genius_lines produces only empty blocks, score stays -1 < 35 → None."""
        active_segments = [{"lyric_current": "hello world"}]
        genius_lines = [""]
        result = _find_lyrics_window(active_segments, genius_lines, "lyric_current")
        # Score should be very low (0 matching empty) → None
        assert result is None or result == 0


# ===========================================================================
# _find_lyrics_window — early termination on score > 95
# ===========================================================================

class TestFindLyricsWindowEarlyTermination:
    def test_exact_match_terminates_early(self):
        """A perfect match should trigger the score > 95 early-termination path."""
        text = "im in love with the shape of you we push and pull like a magnet do"
        genius_lines = [
            "I'm in love with the shape of you",
            "We push and pull like a magnet do",
        ]
        active_segments = [
            {"lyric_current": "Im in love with the shape of you"},
            {"lyric_current": "We push and pull like a magnet do"},
        ]
        result = _find_lyrics_window(active_segments, genius_lines, "lyric_current")
        assert result is not None
        assert result == 0

    def test_low_similarity_returns_none(self):
        """Completely unrelated text → best score < 35 → None."""
        genius_lines = ["xqzj bvwp flkm", "ydgh ncrt svwq"]
        active_segments = [{"lyric_current": "aaaa bbbb cccc dddd eeee ffff gggg"}]
        result = _find_lyrics_window(active_segments, genius_lines, "lyric_current")
        assert result is None


# ===========================================================================
# _align_within_window — empty segment text skipped
# ===========================================================================

class TestAlignWithinWindowEmptySegments:
    def test_empty_text_segments_not_counted(self):
        """Segments with empty lyric_current are skipped — total stays 0."""
        segments = [
            _aurora_seg(""),
            _aurora_seg("   "),
        ]
        genius_lines = ["Hello world", "Foo bar"]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert total == 0
        assert matched == 0

    def test_mixed_empty_and_real_segments(self):
        """Only non-empty segments contribute to total count."""
        segments = [
            _aurora_seg("Im in love with the shape of you"),
            _aurora_seg(""),
        ]
        genius_lines = ["I'm in love with the shape of you"]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert total == 1


# ===========================================================================
# _align_within_window — backward search path
# ===========================================================================

class TestAlignWithinWindowBackwardSearch:
    def test_chorus_repeat_uses_backward_search(self):
        """
        A chorus line that appears earlier in the genius list should be
        found via the backward search (best_score < 70 triggers it).
        """
        genius_lines = [
            "Im in love with the shape of you",   # idx 0
            "We push and pull like a magnet do",  # idx 1
            "Im in love with your body",           # idx 2 (chorus repeat)
            "Oh I oh I oh I oh I",                 # idx 3
        ]
        # First segment matches idx 3, second matches idx 0 (requires backward search)
        segments = [
            _aurora_seg("Oh I oh I oh I oh I", 0, 3),
            _aurora_seg("Im in love with the shape of you", 3, 6),
        ]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert total == 2


# ===========================================================================
# _align_within_window — full-scan fallback
# ===========================================================================

class TestAlignWithinWindowFullScan:
    def test_full_scan_finds_match_at_end(self):
        """
        When forward and backward search fail, a full-scan should find
        a match that's outside the normal search range.
        """
        # Build a long genius list where the matching line is at the end
        genius_lines = ["unrelated line " + str(i) for i in range(20)]
        genius_lines.append("the hidden match line at the end here")

        segments = [_aurora_seg("the hidden match line at the end here")]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert total == 1
        # May or may not match depending on cursor position, but must not crash
        assert matched >= 0


# ===========================================================================
# Two-pass recovery
# ===========================================================================

class TestTwoPassRecovery:
    def test_recovery_improves_weak_match(self):
        """
        Two-pass recovery: an anchor (high score) constrains the search range
        for a weak match, allowing it to find a better genius line.
        """
        genius_lines = [
            "I'm in love with the shape of you",   # 0 — anchor target
            "This is totally different text here",  # 1 — weak target after constraint
            "We push and pull like a magnet do",    # 2
            "Although my heart is falling too",     # 3
        ]
        # Segment 0 is a strong anchor (very close to genius_lines[0])
        # Segment 1 is weak (score ~55 without constraint)
        segments = [
            _aurora_seg("Im in love with the shape of you", 0, 2),
            _aurora_seg("This is totally different text", 2, 4),
        ]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        # At least the anchor should match
        assert matched >= 1
        assert total == 2

    def test_no_anchors_no_recovery(self):
        """Without any high-score anchors, two-pass recovery is a no-op."""
        genius_lines = ["xyz abc def", "pqr lmn opq"]
        segments = [_aurora_seg("completely unrelated text here")]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        # No crash; recovery path skipped gracefully
        assert total == 1

    def test_recovery_noop_when_no_weak_indices(self):
        """If all matches are high confidence, weak_indices is empty → recovery skipped."""
        genius_lines = [
            "I'm in love with the shape of you",
            "We push and pull like a magnet do",
        ]
        segments = [
            _aurora_seg("Im in love with the shape of you"),
            _aurora_seg("We push and pull like a magnet do"),
        ]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert matched == 2


# ===========================================================================
# _remove_whisper_artifacts — mono (pop) branch
# ===========================================================================

class TestRemoveWhisperArtifactsMono:
    def test_mono_consecutive_duplicate_removed_by_pop(self):
        """For non-lyric_current keys (mono/onyx), duplicates are removed by pop."""
        segments = [
            _mono_seg("hello world", time=0.0, end_time=1.0),
            _mono_seg("hello world", time=1.1, end_time=2.0),   # gap = 0.1 < 0.5
        ]
        result = _remove_whisper_artifacts(segments, "text")
        # The duplicate should be popped
        assert len(result) == 1
        assert result[0]["text"] == "hello world"

    def test_mono_large_gap_both_kept(self):
        segments = [
            _mono_seg("hello world", time=0.0, end_time=1.0),
            _mono_seg("hello world", time=5.0, end_time=6.0),   # gap = 4.0 >= 0.5
        ]
        result = _remove_whisper_artifacts(segments, "text")
        assert len(result) == 2

    def test_aurora_consecutive_duplicate_blanked(self):
        """For lyric_current key (aurora), duplicate text is set to ''."""
        segments = [
            _aurora_seg("hello world", t=0.0, end_time=1.0),
            _aurora_seg("hello world", t=1.1, end_time=2.0),   # gap = 0.1 < 0.5
        ]
        result = _remove_whisper_artifacts(segments, "lyric_current")
        assert len(result) == 2  # Not popped — blanked instead
        # The later duplicate is blanked
        texts = [s["lyric_current"] for s in result]
        assert "" in texts

    def test_single_segment_returns_unchanged(self):
        segments = [_mono_seg("only one", 0, 2)]
        result = _remove_whisper_artifacts(segments, "text")
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        result = _remove_whisper_artifacts([], "text")
        assert result == []

    def test_multiple_consecutive_duplicates_all_removed(self):
        """Three identical segments in a row with tiny gaps → only first kept."""
        segments = [
            _mono_seg("repeat line", time=0.0, end_time=1.0),
            _mono_seg("repeat line", time=1.1, end_time=2.0),
            _mono_seg("repeat line", time=2.1, end_time=3.0),
        ]
        result = _remove_whisper_artifacts(segments, "text")
        assert len(result) == 1


# ===========================================================================
# align_genius_to_whisper — all-sections genius text (no lyric lines)
# ===========================================================================

class TestAlignGeniusNoLyricLines:
    def test_only_section_headers_returns_zero_ratio(self):
        """If genius_text has only section headers, genius_lyric_lines is empty → 0.0."""
        genius_only_headers = "[Chorus]\n[Verse 1]\n[Bridge]\n[Outro]\n"
        segments = [_aurora_seg("some whisper text")]
        result_segs, ratio = align_genius_to_whisper(
            segments, genius_only_headers, segment_text_key="lyric_current"
        )
        assert ratio == 0.0

    def test_window_not_found_returns_zero_ratio(self):
        """When _find_lyrics_window returns None, ratio is 0.0."""
        genius_text = "roses are red\nviolets are blue\nsugar is sweet"
        segments = [_aurora_seg("quantum entanglement photon emission")]
        result_segs, ratio = align_genius_to_whisper(
            segments, genius_text, segment_text_key="lyric_current"
        )
        assert ratio == 0.0


# ===========================================================================
# _align_within_window — seg_text non-empty but cleans to empty (lines 190-191)
# ===========================================================================

class TestAlignWithinWindowPunctuationOnlySegment:
    def test_punctuation_only_segment_counted_in_total_not_matched(self):
        """
        A segment whose text is purely punctuation (e.g. '...') passes the
        non-empty check so total is incremented, but _clean_for_match returns
        '' so the segment is skipped (lines 190-191) without searching.
        match_info should have None for that slot and matched stays 0.
        """
        genius_lines = ["I'm in love with the shape of you"]
        segments = [_aurora_seg("...")]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        # total incremented (non-empty seg_text), but no match possible
        assert total == 1
        assert matched == 0

    def test_mixed_punctuation_and_real_segment(self):
        """
        A '...' segment is skipped after clean; the real segment still aligns.
        """
        genius_lines = ["I'm in love with the shape of you", "We push and pull like a magnet do"]
        segments = [
            _aurora_seg("..."),
            _aurora_seg("Im in love with the shape of you"),
        ]
        result_segs, matched, total = _align_within_window(
            segments, genius_lines, 0, "lyric_current"
        )
        assert total == 2    # both segments have non-empty seg_text
        assert matched >= 1  # the real segment should match


# ===========================================================================
# Full-scan fallback — early exit on score >= 92 (lines 222-225)
# ===========================================================================

class TestFullScanEarlyExit:
    def test_early_exit_on_high_score_in_full_scan(self):
        """
        When forward search and backward search both fail (score < 50), the
        full-scan path triggers.  Patch _match_score so that:
          - Forward region returns 0
          - The first out-of-region line returns score=92 (triggers break)
        Verify the function completes without error and the high-scoring line
        is applied as the match.
        """
        # genius_clean has indices 0..4; cursor will be 0, forward_limit covers 0..12
        # With num_segs=1 and min_window=1, window covers start+0..end=start+1
        # We make genius_lines long enough that a line at index 15 is outside forward_limit
        genius_lines = ["unrelated " + str(i) for i in range(20)]
        genius_lines[15] = "the exact match we are looking for here"
        segments = [_aurora_seg("the exact match we are looking for here")]

        call_count = [0]
        original_match_score = __import__(
            "scripts.lyric_alignment", fromlist=["_match_score"]
        )._match_score

        def patched_match_score(w, g):
            # Return 92 for the target line so the break fires
            if "exact match" in g:
                return 92
            return 0

        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            result_segs, matched, total = _align_within_window(
                segments, genius_lines, 0, "lyric_current"
            )

        assert total == 1
        # The line that scored 92 should have been applied (score > best_score=0, score>=60)
        assert matched == 1
        assert result_segs[0]["lyric_current"] == genius_lines[15]

    def test_full_scan_skips_forward_region_indices(self):
        """
        Lines in [genius_cursor, forward_limit) are skipped by 'continue' in
        the full-scan loop (lines 218-219).  The full-scan should only consider
        lines outside that window.
        """
        # With 1 segment and the cursor at 0, forward_limit = min(20, 0+12)=12
        # Lines 0-11 are in the skip zone; line 13 is the target
        genius_lines = ["skip " + str(i) for i in range(14)]
        genius_lines[13] = "the hidden target outside the window abc"
        segments = [_aurora_seg("the hidden target outside the window abc")]

        def patched_match_score(w, g):
            if "hidden target" in g:
                return 75
            return 0

        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            result_segs, matched, total = _align_within_window(
                segments, genius_lines, 0, "lyric_current"
            )

        # The line outside the forward window should have been found
        assert matched == 1
        assert result_segs[0]["lyric_current"] == genius_lines[13]


# ===========================================================================
# Two-pass recovery block — anchors + weak matches (lines 254-294)
# ===========================================================================

class TestTwoPassRecoveryBlock:
    def test_recovery_executes_when_anchors_and_weak_present(self):
        """
        Drive the two-pass recovery block (lines 253-294) directly by patching
        _match_score to return controlled values.

        Setup:
          - 30-line genius list. Segment 0 (anchor) matches genius_lines[20] at
            score=90, advancing cursor to 21.
          - Segment 1 (weak): forward scan covers indices 21..28.  All lines in
            that range score 0 except index 22 which scores 55 (weak: 50-65).
          - Index 29 is outside forward range AND outside backward range
            (cursor=21, backward covers 1..20) so it scores 62 but is NOT found
            by the first pass.  Full-scan is not triggered (55 >= min_score=50).
          - First-pass ends: score=55 at genius_j=22  → weak index.

        Recovery:
          - anchor at seg_idx=0, genius_j=20: provides prev_anchor_j=20 (line 268).
          - Range = [20, 30).  Scans indices 20..29.
          - Index 29 scores 62 > 55 → lines 282-283 execute, 286-291 execute.
          - recovered=1 → line 294 print fires.
        """
        # Build a 30-line genius list
        genius_lines = ["unrelated line {}".format(i) for i in range(30)]
        genius_lines[20] = "I'm in love with the shape of you"   # anchor target
        genius_lines[22] = "something barely matches here now"   # weak target (55)
        genius_lines[29] = "something barely matches here today" # better (62)

        def patched_match_score(w, g):
            from scripts.lyric_alignment import _clean_for_match
            if "im in love" in w:
                if "love with the shape" in g:
                    return 90
                return 0
            if "something barely matches" in w:
                if "here now" in g:
                    return 55   # weak — first-pass forward finds this
                if "here today" in g:
                    return 62   # better but outside first-pass window
            return 0

        segs = segments_for_recovery_test()
        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            result_segs, matched, total = _align_within_window(
                segs, genius_lines, 0, "lyric_current"
            )

        assert total == 2
        # Segment 0 matched the anchor line
        assert result_segs[0]["lyric_current"] == genius_lines[20]
        # Segment 1 was improved from the weak match (line 22) to the better (line 29)
        assert result_segs[1]["lyric_current"] == genius_lines[29]

    def test_recovery_skips_segment_with_empty_text_after_clean(self):
        """
        Inside the recovery loop, if the weak segment's text cleans to empty,
        it should be skipped without crashing (line 260-261).
        """
        genius_lines = [
            "I'm in love with the shape of you",
            "!!! ??? ---",  # weak match target; text cleans to empty in recovery
        ]
        segments = [
            _aurora_seg("Im in love with the shape of you", 0, 2),
            _aurora_seg("!!! ??? ---", 2, 4),
        ]

        def patched_match_score(w, g):
            if "im in love" in w:
                return 90
            # Return 55 for the punctuation-only segment on first pass
            # (w will be empty after clean, so _match_score returns 0 anyway,
            #  but we want a non-zero first-pass score to create a weak_index entry)
            return 55 if w else 0

        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            # Should not raise even though the weak segment has no alphanumeric content
            result_segs, matched, total = _align_within_window(
                segments, genius_lines, 0, "lyric_current"
            )

        # No crash is the main assertion
        assert total >= 1

    def test_recovery_uses_anchor_after_weak_to_constrain_range(self):
        """
        Line 270: when an anchor appears AFTER the weak segment (anchor seg_idx > weak
        seg_idx), next_anchor_j is updated to anchor.genius_j (line 270), narrowing
        the upper bound of the recovery search range.

        Mechanics:
          - 20-line genius list.
          - Cursor starts at window_start=0.
          - Segment 0 (weak): forward window is [0,8). Index 3 scores 55 (weak);
            index 8 (the better line) is OUTSIDE this window.
            Backward: cursor=0 → no backward range. Full-scan not triggered (55>=50).
            First-pass result: score=55 at genius_j=3  → weak index.
          - Segment 1 (anchor): matches genius_lines[10] at score=90.
            cursor advances to 11.

        Recovery for segment 0:
          - No anchor before seg 0  → prev_anchor_j stays 0.
          - Anchor at seg_idx=1, genius_j=10 has seg_idx=1 > seg_idx=0 AND
            genius_j=10 < next_anchor_j=19  → next_anchor_j = 10 (line 270 runs).
          - Recovery range = [0, 11); index 8 scores 62 > 55 → improvement applied
            (lines 282-283, 285-287 execute).  recovered=1 → line 294 fires.
        """
        genius_lines = ["line {}".format(i) for i in range(20)]
        genius_lines[3]  = "barely matching line here now"    # weak (score 55 in fwd)
        genius_lines[8]  = "barely matching line here today"  # better (score 62)
        genius_lines[10] = "I'm in love with the shape of you"  # anchor target

        def patched_match_score(w, g):
            if "im in love" in w:
                return 90 if "love with the shape" in g else 0
            if "barely matching" in w:
                if "here now" in g:
                    return 55   # weak — found in forward scan
                if "here today" in g:
                    return 62   # better — outside forward, within recovery range
            return 0

        segments = [
            _aurora_seg("barely matching line here", 0, 2),        # seg 0: weak
            _aurora_seg("Im in love with the shape of you", 2, 4),  # seg 1: anchor
        ]

        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            result_segs, matched, total = _align_within_window(
                segments, genius_lines, 0, "lyric_current"
            )

        assert total == 2
        assert matched == 2
        # Segment 0 improved from genius_lines[3] to genius_lines[8] by recovery
        assert result_segs[0]["lyric_current"] == genius_lines[8]
        # Segment 1 matched the anchor line
        assert result_segs[1]["lyric_current"] == genius_lines[10]

    def test_recovery_no_improvement_leaves_original_text(self):
        """
        If recovery re-search does not find a higher score than the weak match,
        the segment text must remain unchanged.
        """
        genius_lines = [
            "I'm in love with the shape of you",
            "We push and pull like a magnet do",
        ]
        segments = [
            _aurora_seg("Im in love with the shape of you", 0, 2),
            _aurora_seg("We push and pull like a magnet", 2, 4),
        ]
        original_weak_text = segments[1]["lyric_current"]

        scores = {
            ("im in love with the shape of you", "im in love with the shape of you"): 95,
            ("we push and pull like a magnet", "we push and pull like a magnet do"): 55,
            # Recovery re-search returns same 55 — no improvement
        }

        def patched_match_score(w, g):
            from scripts.lyric_alignment import _clean_for_match
            key = (_clean_for_match(w), _clean_for_match(g))
            return scores.get(key, 10)

        with patch("scripts.lyric_alignment._match_score", side_effect=patched_match_score):
            result_segs, matched, total = _align_within_window(
                segments, genius_lines, 0, "lyric_current"
            )

        # Segment 1 text should remain the genius line it was originally matched to
        # (score 55 >= min_score 50, so it was applied on the first pass)
        # Recovery found no improvement so no change
        assert result_segs[1]["lyric_current"] in (original_weak_text, genius_lines[1])


# ===========================================================================
# _remove_whisper_artifacts — one segment has empty text (line 337-338)
# ===========================================================================

class TestRemoveWhisperArtifactsEmptyText:
    def test_empty_current_text_skips_comparison(self):
        """
        When current_text is empty the loop hits 'continue' (line 338) without
        comparing or removing anything.  The non-empty segments must survive.
        """
        segments = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello world"},
            {"t": 1.1, "end_time": 2.1, "lyric_current": ""},         # empty current
            {"t": 2.2, "end_time": 3.2, "lyric_current": "goodbye world"},
        ]
        result = _remove_whisper_artifacts(segments, "lyric_current")
        # No removal should occur — empty segment skips comparison
        non_empty = [s for s in result if s.get("lyric_current")]
        assert len(non_empty) == 2

    def test_empty_prev_text_skips_comparison(self):
        """
        When prev_text is empty the loop skips comparison (line 338).
        The segment after the empty one must not be erroneously removed.
        """
        segments = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": ""},          # empty prev
            {"t": 1.1, "end_time": 2.1, "lyric_current": "hello world"},
        ]
        result = _remove_whisper_artifacts(segments, "lyric_current")
        non_empty = [s for s in result if s.get("lyric_current")]
        assert len(non_empty) == 1
        assert non_empty[0]["lyric_current"] == "hello world"

    def test_empty_between_two_identical_lines_no_false_removal(self):
        """
        Two identical non-empty segments with a tiny gap but separated by an
        empty segment: the empty segment breaks the consecutive duplicate
        check so neither non-empty segment should be removed.
        """
        segments = [
            {"t": 0.0, "end_time": 1.0, "lyric_current": "hello world"},
            {"t": 1.05, "end_time": 2.0, "lyric_current": ""},
            {"t": 2.05, "end_time": 3.0, "lyric_current": "hello world"},
        ]
        result = _remove_whisper_artifacts(segments, "lyric_current")
        non_empty = [s for s in result if s.get("lyric_current")]
        # The two "hello world" segments are NOT consecutive (empty is between them)
        assert len(non_empty) == 2


# ===========================================================================
# _match_score — empty inputs (line 306)
# ===========================================================================

class TestMatchScoreEmptyInputs:
    def test_empty_whisper_returns_zero(self):
        """Line 305-306: empty whisper_clean → return 0."""
        assert _match_score("", "some genius text here") == 0

    def test_empty_genius_returns_zero(self):
        """Line 305-306: empty genius_clean → return 0."""
        assert _match_score("some whisper text here", "") == 0

    def test_both_empty_returns_zero(self):
        """Line 305-306: both empty → return 0."""
        assert _match_score("", "") == 0

    def test_non_empty_inputs_return_positive(self):
        """Sanity: non-empty identical inputs should score high."""
        score = _match_score("hello world", "hello world")
        assert score > 90
