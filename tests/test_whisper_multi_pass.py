"""
Tests for whisper_common.multi_pass_transcribe — deep edge cases.

Covers:
  - Happy path: return type, early return on sufficient pass 1, best result by weighted score
  - Edge cases: None/zero/short/long duration, language None vs "en", word_timestamps, custom regroup
  - All-fail: empty segments, None result, exceptions on all passes, below-threshold best
  - GPU fallback: CUDA OOM triggers CPU reload (only once), non-OOM RuntimeError does NOT fallback
  - Time cap (180s): stops early with best, continues if no result yet
  - Segment counting: empty text not counted, single-char not counted, mixed valid/invalid
  - Weighted scoring: verify weights 1.0/0.9/0.75/0.6, higher weight wins with fewer raw segs
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.whisper_common import multi_pass_transcribe
from conftest import _make_result_with_n_segments, _make_whisper_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_model(side_effects):
    """Return (mock_model, patches) that make load_whisper_model return a model
    whose transcribe() calls return *side_effects* in order."""
    model = MagicMock()
    model.transcribe = MagicMock(side_effect=side_effects)
    return model


def _good_result(n_segments=10):
    return _make_result_with_n_segments(n_segments, valid=True)


def _empty_result():
    r = MagicMock()
    r.segments = []
    return r


def _none_segments_result():
    r = MagicMock()
    r.segments = None
    return r


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestMultiPassHappyPath:
    """Basic successful transcription scenarios."""

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_returns_tuple_of_result_and_index(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is not None
        assert isinstance(idx, int)
        assert idx == 0

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_early_return_on_pass1_sufficient(self, _dur, mock_load):
        model = _patch_model([_good_result(30)])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert idx == 0
        # Only one transcribe call (didn't proceed to pass 2)
        assert model.transcribe.call_count == 1

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_best_result_by_weighted_score(self, _dur, mock_load):
        """Pass 1 gets 5 segments (weight 1.0 = 5.0),
        Pass 2 gets 7 segments (weight 0.9 = 6.3) — pass 2 wins."""
        model = _patch_model([
            _good_result(5),   # pass 1: 5 * 1.0 = 5.0
            _good_result(7),   # pass 2: 7 * 0.9 = 6.3
            _good_result(3),   # pass 3: 3 * 0.75 = 2.25
            _good_result(4),   # pass 4: 4 * 0.6 = 2.4
        ])
        mock_load.return_value = model
        # min_expected = max(2, 60/3.5) = 17, so none pass early exit
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert idx == 1  # pass 2 had highest weighted score


# ---------------------------------------------------------------------------
# Duration edge cases
# ---------------------------------------------------------------------------

class TestDurationEdgeCases:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=0.0)
    def test_none_duration_uses_min_expected_2(self, _dur, mock_load):
        """When duration is None, min_expected=2, so even 2 segments suffice."""
        model = _patch_model([_good_result(2)])
        mock_load.return_value = model
        # get_audio_duration returns 0.0 (mocked), but caller passes None
        result, idx = multi_pass_transcribe("audio.wav", "prompt", None, "en")
        assert result is not None
        assert idx == 0

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=0.0)
    def test_zero_duration_min_expected_2(self, _dur, mock_load):
        model = _patch_model([_good_result(2)])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 0, "en")
        # duration=0 -> max(2, int(0/3.5))=max(2,0)=2
        assert result is not None

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=7.0)
    def test_short_duration_min_expected_2(self, _dur, mock_load):
        model = _patch_model([_good_result(2)])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 7.0, "en")
        assert result is not None

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=600.0)
    def test_long_duration_high_min_expected(self, _dur, mock_load):
        """600s -> min_expected = max(2, 171) = 171. Nothing reaches it."""
        model = _patch_model([
            _good_result(50),
            _good_result(60),
            _good_result(40),
            _good_result(30),
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 600.0, "en")
        # None reaches 171, so best weighted wins: 60*0.9=54 > 50*1.0=50
        assert idx == 1


# ---------------------------------------------------------------------------
# Language parameter
# ---------------------------------------------------------------------------

class TestLanguageParameter:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_language_none_omits_lang_param(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        multi_pass_transcribe("audio.wav", "prompt", 30.0, None)
        kwargs = model.transcribe.call_args[1]
        assert "language" not in kwargs

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_language_en_includes_lang_param(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        kwargs = model.transcribe.call_args[1]
        assert kwargs["language"] == "en"


# ---------------------------------------------------------------------------
# word_timestamps and regroup_passes
# ---------------------------------------------------------------------------

class TestTranscribeOptions:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_word_timestamps_true_by_default(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        multi_pass_transcribe("audio.wav", "prompt", 30.0, "en", word_timestamps=True)
        kwargs = model.transcribe.call_args[1]
        assert kwargs["word_timestamps"] is True

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_word_timestamps_false_omits_param(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        multi_pass_transcribe("audio.wav", "prompt", 30.0, "en", word_timestamps=False)
        kwargs = model.transcribe.call_args[1]
        assert "word_timestamps" not in kwargs

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_custom_regroup_passes(self, _dur, mock_load):
        model = _patch_model([_good_result(20)])
        mock_load.return_value = model
        custom = [False, False, False, True]
        multi_pass_transcribe("audio.wav", "prompt", 30.0, "en", regroup_passes=custom)
        kwargs = model.transcribe.call_args[1]
        assert kwargs["regroup"] is False  # pass 1 gets custom[0]


# ---------------------------------------------------------------------------
# All-fail scenarios
# ---------------------------------------------------------------------------

class TestAllFail:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_all_passes_return_empty_segments(self, _dur, mock_load):
        model = _patch_model([_empty_result()] * 4)
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is None
        assert idx == -1

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_all_passes_return_none_segments(self, _dur, mock_load):
        model = _patch_model([_none_segments_result()] * 4)
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is None

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_all_passes_raise_generic_exception(self, _dur, mock_load):
        model = _patch_model([Exception("fail")] * 4)
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is None

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_below_threshold_best_still_returned(self, _dur, mock_load):
        """Even if no pass reaches min_expected, the best is still returned."""
        model = _patch_model([
            _good_result(3),  # below min_expected=17
            _good_result(4),  # still below
            _empty_result(),
            _empty_result(),
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is not None
        # 4*0.9=3.6 > 3*1.0=3.0, so pass 2 wins
        assert idx == 1


# ---------------------------------------------------------------------------
# GPU fallback
# ---------------------------------------------------------------------------

class TestGPUFallback:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_cuda_oom_triggers_cpu_reload(self, _dur, mock_load):
        cpu_model = MagicMock()
        cpu_model.transcribe = MagicMock(return_value=_good_result(20))

        gpu_model = MagicMock()
        gpu_model.transcribe = MagicMock(
            side_effect=RuntimeError("CUDA out of memory")
        )

        mock_load.side_effect = [gpu_model, cpu_model]
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        assert result is not None
        # Should have called load_whisper_model twice: once GPU, once CPU
        assert mock_load.call_count == 2
        assert mock_load.call_args_list[1] == call(force_cpu=True)

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_cuda_oom_fallback_only_once(self, _dur, mock_load):
        """Second CUDA OOM should NOT trigger another CPU reload."""
        gpu_model = MagicMock()
        gpu_model.transcribe = MagicMock(
            side_effect=RuntimeError("CUDA out of memory")
        )
        cpu_model = MagicMock()
        # CPU transcribe: first call succeeds (but not enough), second raises OOM
        cpu_model.transcribe = MagicMock(side_effect=[
            _good_result(3),  # CPU pass 1: not sufficient (min_expected=17)
            RuntimeError("CUDA out of memory"),  # pass 2 — should NOT re-fallback
            _good_result(4),
            _good_result(5),
        ])
        mock_load.side_effect = [gpu_model, cpu_model]
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        # Only 2 load calls (initial GPU + one CPU fallback)
        assert mock_load.call_count == 2

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_non_oom_runtime_error_does_not_fallback(self, _dur, mock_load):
        """RuntimeError that is NOT CUDA OOM should just continue to next pass."""
        model = MagicMock()
        model.transcribe = MagicMock(side_effect=[
            RuntimeError("Some other error"),
            _good_result(20),
            _good_result(5),
            _good_result(5),
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        # Should NOT have reloaded model
        assert mock_load.call_count == 1
        assert result is not None
        assert idx == 1  # pass 2 succeeded

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_cpu_fallback_also_fails_continues(self, _dur, mock_load):
        gpu_model = MagicMock()
        gpu_model.transcribe = MagicMock(
            side_effect=RuntimeError("CUDA out of memory")
        )
        cpu_model = MagicMock()
        cpu_model.transcribe = MagicMock(side_effect=Exception("CPU also fails"))
        mock_load.side_effect = [gpu_model, cpu_model]
        # Should not crash — gracefully continues to remaining passes
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        # May or may not have a result, but should not raise


# ---------------------------------------------------------------------------
# Time cap
# ---------------------------------------------------------------------------

class TestTimeCap:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_time_cap_stops_early_with_best(self, _dur, mock_load):
        """If elapsed > 180s and we have a result, stop early."""
        call_count = 0
        real_time = time.time
        start = real_time()

        def slow_transcribe(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _good_result(5)  # Below min_expected
            return _good_result(3)

        model = MagicMock()
        model.transcribe = slow_transcribe
        mock_load.return_value = model

        def fake_time():
            # After first transcribe call, simulate >180s elapsed
            if call_count >= 1:
                return start + 200
            return start

        with patch("time.time", side_effect=fake_time):
            result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")

        assert result is not None
        # Should have returned after pass 1 due to time cap
        assert call_count <= 2

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=60.0)
    def test_time_cap_continues_if_no_result_yet(self, _dur, mock_load):
        """Time cap only applies if best_result is not None."""
        call_count = 0

        def transcribe_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _empty_result()
            return _good_result(20)

        model = MagicMock()
        model.transcribe = transcribe_fn
        mock_load.return_value = model

        result, idx = multi_pass_transcribe("audio.wav", "prompt", 60.0, "en")
        assert result is not None


# ---------------------------------------------------------------------------
# Segment counting
# ---------------------------------------------------------------------------

class TestSegmentCounting:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_empty_text_not_counted(self, _dur, mock_load):
        """Segments with empty text should not count toward the score."""
        result = MagicMock()
        segs = []
        # 5 valid segments
        for i in range(5):
            s = MagicMock()
            s.text = f"word{i} hello"
            s.start = float(i)
            s.end = float(i + 0.5)
            segs.append(s)
        # 10 empty segments
        for i in range(10):
            s = MagicMock()
            s.text = ""
            s.start = float(i + 5)
            s.end = float(i + 5.5)
            segs.append(s)
        result.segments = segs

        model = MagicMock()
        model.transcribe = MagicMock(return_value=result)
        mock_load.return_value = model
        r, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        # 5 valid segments < min_expected=8, so all passes run

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_single_char_not_counted(self, _dur, mock_load):
        """Single-char segments (len<=1 after strip) should not count."""
        result = MagicMock()
        segs = []
        for i in range(20):
            s = MagicMock()
            s.text = "x"  # single char
            s.start = float(i)
            s.end = float(i + 0.5)
            segs.append(s)
        result.segments = segs

        model = MagicMock()
        model.transcribe = MagicMock(side_effect=[result, _good_result(20)] + [_empty_result()] * 2)
        mock_load.return_value = model
        r, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        # Single-char segments -> count=0, so pass 1 doesn't satisfy min_expected
        # Pass 2 with 20 valid segments should succeed
        assert idx == 1

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=30.0)
    def test_mixed_valid_invalid_segments(self, _dur, mock_load):
        result = MagicMock()
        segs = []
        # 10 valid, 5 empty, 5 single-char
        for i in range(10):
            s = MagicMock()
            s.text = f"valid word{i}"
            s.start = float(i)
            s.end = float(i + 0.5)
            segs.append(s)
        for i in range(5):
            s = MagicMock()
            s.text = ""
            s.start = 10.0 + i
            s.end = 10.5 + i
            segs.append(s)
        for i in range(5):
            s = MagicMock()
            s.text = "a"
            s.start = 15.0 + i
            s.end = 15.5 + i
            segs.append(s)
        result.segments = segs

        model = MagicMock()
        model.transcribe = MagicMock(return_value=result)
        mock_load.return_value = model
        # min_expected = max(2, 30/3.5) = 8; count=10 >= 8
        r, idx = multi_pass_transcribe("audio.wav", "prompt", 30.0, "en")
        assert idx == 0  # sufficient on pass 1


# ---------------------------------------------------------------------------
# Weighted scoring verification
# ---------------------------------------------------------------------------

class TestWeightedScoring:

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=600.0)
    def test_weights_are_1_09_075_06(self, _dur, mock_load):
        """Verify the 4 pass weights: 1.0, 0.9, 0.75, 0.6."""
        # None will reach min_expected=171, so all 4 passes run
        model = _patch_model([
            _good_result(10),  # 10 * 1.0 = 10.0
            _good_result(10),  # 10 * 0.9 = 9.0
            _good_result(10),  # 10 * 0.75 = 7.5
            _good_result(10),  # 10 * 0.6 = 6.0
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 600.0, "en")
        # Equal raw count → pass 1 wins due to highest weight
        assert idx == 0

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=600.0)
    def test_higher_weight_wins_with_fewer_raw_segments(self, _dur, mock_load):
        """Pass 1 with 9 segs (9.0) should beat Pass 2 with 9 segs (8.1)."""
        model = _patch_model([
            _good_result(9),   # 9 * 1.0 = 9.0
            _good_result(9),   # 9 * 0.9 = 8.1
            _good_result(9),   # 9 * 0.75 = 6.75
            _good_result(9),   # 9 * 0.6 = 5.4
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 600.0, "en")
        assert idx == 0

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=600.0)
    def test_pass2_beats_pass1_when_enough_more_segments(self, _dur, mock_load):
        """Pass 2 needs >11% more segments to beat pass 1."""
        model = _patch_model([
            _good_result(9),   # 9 * 1.0 = 9.0
            _good_result(11),  # 11 * 0.9 = 9.9  — wins
            _good_result(5),   # 5 * 0.75 = 3.75
            _good_result(5),   # 5 * 0.6 = 3.0
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 600.0, "en")
        assert idx == 1

    @patch("scripts.whisper_common.load_whisper_model")
    @patch("scripts.whisper_common.get_audio_duration", return_value=600.0)
    def test_tie_goes_to_first_pass(self, _dur, mock_load):
        """When weighted scores are exactly equal, first pass wins (> not >=)."""
        # pass1: 9*1.0=9.0, pass2: 10*0.9=9.0
        model = _patch_model([
            _good_result(9),
            _good_result(10),
            _good_result(5),
            _good_result(5),
        ])
        mock_load.return_value = model
        result, idx = multi_pass_transcribe("audio.wav", "prompt", 600.0, "en")
        assert idx == 0  # tie → first pass
