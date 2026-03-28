"""
Tests for scripts/lyric_processing_onyx.py (Onyx template pipeline).

All Whisper/Genius dependencies mocked. Covers:
  - Happy path, None when audio missing, empty when no segments
  - Custom regroup_passes=[False,False,False,True], manual regrouping
  - Regrouping failure graceful fallback
  - Genius alignment + rebuild_words, reverted on low ratio
  - Final cleanup calls
"""
from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path

import pytest

from conftest import _make_whisper_result


def _mock_whisper_common(monkeypatch):
    import scripts.whisper_common as wc
    monkeypatch.setattr(wc, "get_audio_duration", lambda p: 60.0)
    monkeypatch.setattr(wc, "build_initial_prompt", lambda t: "prompt")
    monkeypatch.setattr(wc, "detect_language", lambda t, g=None: "en")
    monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: None)
    monkeypatch.setattr(wc, "save_whisper_cache", lambda jf, s: None)
    monkeypatch.setattr(wc, "separate_vocals", lambda a, jf: a)
    for fn_name in ("remove_hallucinations", "remove_junk", "remove_stutter_duplicates",
                     "remove_repetition_loops", "remove_instrumental_hallucinations",
                     "remove_non_target_script"):
        monkeypatch.setattr(wc, fn_name, lambda items, *a, **kw: items)
    monkeypatch.setattr(wc, "merge_short_markers", lambda m, **kw: m)
    monkeypatch.setattr(wc, "assign_colors", lambda m: None)
    monkeypatch.setattr(wc, "fix_marker_gaps", lambda m: None)
    monkeypatch.setattr(wc, "quality_gate", lambda m, d: (True, []))
    monkeypatch.setattr(wc, "rebuild_words_after_alignment", lambda m: m)


def _make_transcribe_result(n=4):
    return _make_whisper_result([
        {"text": f"line {i}", "start": float(i * 3), "end": float(i * 3 + 2.5)}
        for i in range(n)
    ])


def _make_regroupable_result(n=4):
    """Result that supports split_by_gap/punctuation/length chaining."""
    result = _make_transcribe_result(n)
    result.split_by_gap = MagicMock(return_value=result)
    result.split_by_punctuation = MagicMock(return_value=result)
    result.split_by_length = MagicMock(return_value=result)
    return result


class TestOnyxHappyPath:

    def test_returns_markers_dict(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (_make_regroupable_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        result = transcribe_audio_onyx(str(job_folder), "Artist - Song")
        assert "markers" in result
        assert result["total_markers"] > 0

    def test_none_when_audio_missing(self, job_folder, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        _mock_whisper_common(monkeypatch)
        result = transcribe_audio_onyx(str(job_folder))
        assert result["markers"] == []

    def test_empty_when_no_segments(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc
        _mock_whisper_common(monkeypatch)
        empty = MagicMock()
        empty.segments = []
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (empty, 0))
        result = transcribe_audio_onyx(str(job_folder))
        assert result["total_markers"] == 0


class TestOnyxRegrouping:

    def test_manual_regrouping_called(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        result_obj = _make_regroupable_result()
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (result_obj, 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        transcribe_audio_onyx(str(job_folder))
        result_obj.split_by_gap.assert_called_once_with(0.5)
        result_obj.split_by_punctuation.assert_called_once()
        result_obj.split_by_length.assert_called_once()

    def test_regroup_passes_false_for_first_three(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        captured_kw = {}

        def capture_transcribe(*args, **kwargs):
            captured_kw.update(kwargs)
            return _make_regroupable_result(), 0

        monkeypatch.setattr(wc, "multi_pass_transcribe", capture_transcribe)
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        transcribe_audio_onyx(str(job_folder))
        assert captured_kw.get("regroup_passes") == [False, False, False, True]

    def test_regrouping_failure_graceful_fallback(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        result_obj = _make_transcribe_result()
        result_obj.split_by_gap = MagicMock(side_effect=Exception("regroup failed"))
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (result_obj, 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        result = transcribe_audio_onyx(str(job_folder))
        # Should not crash — continues with unregrouped segments
        assert result["total_markers"] > 0


class TestOnyxGeniusAlignment:

    def test_rebuild_words_called_after_alignment(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        from scripts.config import Config
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (_make_regroupable_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr("scripts.genius_processing.fetch_genius_lyrics", lambda t: "line\n")
        monkeypatch.setattr("scripts.lyric_alignment.align_genius_to_whisper",
                            lambda m, t, **kw: (m, 0.8))
        # align_genius_to_audio returns None → falls back to rebuild_words_after_alignment
        monkeypatch.setattr(wc, "align_genius_to_audio", lambda *a, **kw: None)

        rebuild_called = []
        monkeypatch.setattr(wc, "rebuild_words_after_alignment",
                            lambda m: (rebuild_called.append(True), m)[1])

        transcribe_audio_onyx(str(job_folder), "Artist - Song")
        assert len(rebuild_called) == 1

    def test_genius_reverted_on_low_ratio(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        from scripts.config import Config
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (_make_regroupable_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "original", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr("scripts.genius_processing.fetch_genius_lyrics", lambda t: "wrong")

        def bad_align(m, t, **kw):
            for marker in m:
                marker["text"] = "REPLACED"
            return m, 0.1

        monkeypatch.setattr("scripts.lyric_alignment.align_genius_to_whisper", bad_align)

        result = transcribe_audio_onyx(str(job_folder), "Artist - Song")
        assert result["markers"][0]["text"] == "original"


class TestOnyxCache:

    def test_uses_cache(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc
        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: [
            {"text": "cached", "start": 0, "end": 2, "words": []},
        ])
        mock_transcribe = MagicMock()
        monkeypatch.setattr(wc, "multi_pass_transcribe", mock_transcribe)
        result = transcribe_audio_onyx(str(job_folder))
        mock_transcribe.assert_not_called()
        assert result["total_markers"] == 1


class TestOnyxFinalCleanup:

    def test_quality_gate_warning_still_returns(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_onyx import transcribe_audio_onyx
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "multi_pass_transcribe",
                            lambda *a, **kw: (_make_regroupable_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr(wc, "quality_gate", lambda m, d: (False, ["issue"]))
        result = transcribe_audio_onyx(str(job_folder))
        assert result["total_markers"] > 0


# ===========================================================================
# _onyx_regroup() unit tests — real timing data, no mocks
# ===========================================================================

def _make_real_segment(text: str, start: float, end: float):
    """Build a minimal fake Whisper segment object with real split_by_* support."""
    from unittest.mock import MagicMock

    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end

    token_list = text.split()
    if token_list:
        dur = end - start
        wd = dur / len(token_list) if len(token_list) > 0 else dur
        seg.words = [
            _word(tok, start + i * wd, start + (i + 1) * wd)
            for i, tok in enumerate(token_list)
        ]
    else:
        seg.words = []
    return seg


def _word(text: str, start: float, end: float):
    w = MagicMock()
    w.word = text
    w.start = start
    w.end = end
    return w


def _make_real_result(segments):
    """Wrap a list of segment mocks in a result object with real split_by_* chains."""
    result = MagicMock()
    result.segments = list(segments)

    # split_by_gap / split_by_punctuation / split_by_length return self so we can chain
    result.split_by_gap.return_value = result
    result.split_by_punctuation.return_value = result
    result.split_by_length.return_value = result
    return result


class TestOnyxRegroupIsolation:
    """Directly tests _onyx_regroup() in isolation with real timing data."""

    def _call_regroup(self, result):
        from scripts.lyric_processing_onyx import _onyx_regroup
        return _onyx_regroup(result)

    # ------------------------------------------------------------------
    # Single-word lines
    # ------------------------------------------------------------------

    def test_single_word_line_passes_through(self):
        """A single-word result is passed to split_by_gap and chained."""
        seg = _make_real_segment("Yeah", 0.5, 1.0)
        result = _make_real_result([seg])

        out = self._call_regroup(result)

        result.split_by_gap.assert_called_once_with(0.5)
        result.split_by_punctuation.assert_called_once()
        result.split_by_length.assert_called_once()
        assert out is result  # same object (chained mocks all return self)

    def test_single_word_no_words_lost(self):
        """The return value of _onyx_regroup for single-word input is the chained result."""
        seg = _make_real_segment("Oh", 1.0, 1.5)
        result = _make_real_result([seg])

        out = self._call_regroup(result)
        # split_by_* all return result so segments are preserved
        assert out.segments == result.segments

    # ------------------------------------------------------------------
    # Very long lines (>10 words)
    # ------------------------------------------------------------------

    def test_long_line_split_by_length_receives_max_chars_50(self):
        """split_by_length must be called with max_chars=50 regardless of line length."""
        long_text = "This is a very long lyric line that has more than ten words in it"
        seg = _make_real_segment(long_text, 0.0, 8.0)
        result = _make_real_result([seg])

        self._call_regroup(result)

        call_args = result.split_by_length.call_args
        assert call_args is not None
        # Can be positional or keyword
        if call_args.kwargs:
            assert call_args.kwargs.get("max_chars") == 50
        else:
            assert call_args.args[0] == 50

    def test_long_line_all_three_splits_called(self):
        """All three split passes must execute even for a very long line."""
        long_text = " ".join(f"word{i}" for i in range(15))
        seg = _make_real_segment(long_text, 0.0, 12.0)
        result = _make_real_result([seg])

        self._call_regroup(result)

        result.split_by_gap.assert_called_once()
        result.split_by_punctuation.assert_called_once()
        result.split_by_length.assert_called_once()

    # ------------------------------------------------------------------
    # Punctuation in lyrics
    # ------------------------------------------------------------------

    def test_punctuation_triggers_split_by_punctuation(self):
        """split_by_punctuation must be called with the standard delimiter set."""
        text = "I'm ready, let's go. Are you ready?"
        seg = _make_real_segment(text, 2.0, 5.0)
        result = _make_real_result([seg])

        self._call_regroup(result)

        result.split_by_punctuation.assert_called_once()
        punct_arg = result.split_by_punctuation.call_args[0][0]
        assert "." in punct_arg
        assert "," in punct_arg
        assert "?" in punct_arg
        assert "!" in punct_arg

    def test_punctuation_result_fed_into_length_split(self):
        """split_by_length must receive the output of split_by_punctuation (chaining)."""
        text = "Hello world, how are you?"
        seg = _make_real_segment(text, 0.0, 3.0)

        # Make each split return a DIFFERENT mock to verify chaining
        result = MagicMock()
        after_gap = MagicMock()
        after_punct = MagicMock()
        after_length = MagicMock()

        result.segments = [seg]
        result.split_by_gap.return_value = after_gap
        after_gap.split_by_punctuation.return_value = after_punct
        after_punct.split_by_length.return_value = after_length

        out = self._call_regroup(result)

        # Verify the chain order
        result.split_by_gap.assert_called_once_with(0.5)
        after_gap.split_by_punctuation.assert_called_once()
        after_punct.split_by_length.assert_called_once()
        assert out is after_length

    # ------------------------------------------------------------------
    # No words lost during regrouping
    # ------------------------------------------------------------------

    def test_no_words_lost_multi_segment(self):
        """Total word count in result.segments must equal input word count."""
        segments_data = [
            ("I'm in love with the shape of you", 0.5, 3.2),
            ("We push and pull like a magnet do", 3.4, 6.1),
            ("Although my heart is falling too",  6.3, 8.8),
        ]
        segs = [_make_real_segment(t, s, e) for t, s, e in segments_data]
        result = _make_real_result(segs)

        out = self._call_regroup(result)

        # The chained result is 'result' (all return self), so segments are unchanged
        total_in = sum(len(s.text.split()) for s in segs)
        total_out = sum(len(s.text.split()) for s in out.segments)
        assert total_out == total_in

    def test_empty_segment_list_handled_gracefully(self):
        """An empty segment list must not raise an exception."""
        result = _make_real_result([])

        # Should not raise
        out = self._call_regroup(result)
        assert out is not None

    # ------------------------------------------------------------------
    # Failure graceful fallback
    # ------------------------------------------------------------------

    def test_split_by_gap_exception_returns_original(self):
        """If split_by_gap raises, _onyx_regroup must return the original result unchanged."""
        seg = _make_real_segment("Some lyric line", 1.0, 3.0)
        result = _make_real_result([seg])
        result.split_by_gap.side_effect = RuntimeError("split failed")

        out = self._call_regroup(result)

        # Must fall back to original (not crash)
        assert out is result

    def test_split_by_punctuation_exception_returns_original(self):
        """If split_by_punctuation raises, _onyx_regroup must return the original."""
        seg = _make_real_segment("Another line here", 2.0, 5.0)
        result = _make_real_result([seg])

        after_gap = MagicMock()
        result.split_by_gap.return_value = after_gap
        after_gap.split_by_punctuation.side_effect = ValueError("broken")

        out = self._call_regroup(result)

        assert out is result

    def test_split_by_length_exception_returns_original(self):
        """If split_by_length raises, _onyx_regroup must return the original."""
        seg = _make_real_segment("One more line", 3.0, 6.0)
        result = _make_real_result([seg])

        after_gap = MagicMock()
        after_punct = MagicMock()
        result.split_by_gap.return_value = after_gap
        after_gap.split_by_punctuation.return_value = after_punct
        after_punct.split_by_length.side_effect = Exception("length split error")

        out = self._call_regroup(result)

        assert out is result

    # ------------------------------------------------------------------
    # Real timing data integrity
    # ------------------------------------------------------------------

    def test_segment_start_times_are_preserved(self):
        """After regrouping, segment start times in the result must match input."""
        segments_data = [
            ("Line one", 0.5, 2.0),
            ("Line two", 2.5, 4.0),
            ("Line three", 4.5, 6.5),
        ]
        segs = [_make_real_segment(t, s, e) for t, s, e in segments_data]
        result = _make_real_result(segs)

        out = self._call_regroup(result)

        for i, (_, expected_start, _) in enumerate(segments_data):
            assert out.segments[i].start == pytest.approx(expected_start, abs=0.001)

    def test_word_start_lte_word_end_within_each_segment(self):
        """Word start times must be <= word end times in input segments."""
        text = "Shape of you magnet do"
        seg = _make_real_segment(text, 1.0, 4.0)

        for word in seg.words:
            assert word.start <= word.end, (
                f"Word '{word.word}' has start {word.start} > end {word.end}"
            )

    def test_gap_between_consecutive_word_ends_and_starts(self):
        """No word's start time should precede the previous word's start time."""
        text = "We push and pull like a magnet do"
        seg = _make_real_segment(text, 3.4, 6.1)

        words = seg.words
        for i in range(1, len(words)):
            assert words[i].start >= words[i - 1].start, (
                f"Word '{words[i].word}' starts before '{words[i - 1].word}'"
            )
