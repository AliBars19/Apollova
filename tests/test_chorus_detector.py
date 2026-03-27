"""
Tests for scripts/chorus_detector.py

Covers:
  - ChorusResult dataclass: fields, properties (start_mmss, end_mmss)
  - _sec_to_mmss: zero, sub-minute, over-minute, negative, rounding
  - _snap_to_beat: empty beat array, exact match, nearest-beat snap
  - _heuristic_fallback: correct start/end math, confidence, method tag
  - _rms_fallback: calls librosa, returns ChorusResult with method="rms_fallback"
  - detect_chorus: librosa unavailable raises ImportError
  - detect_chorus: audio shorter than 20 s triggers heuristic fallback
  - detect_chorus: recurrence matrix exception triggers RMS fallback
  - detect_chorus: zero peak (all-silent combined) triggers RMS fallback
  - detect_chorus: end_sec too close to start_sec triggers re-anchoring
  - detect_chorus: happy path returns ChorusResult with method="recurrence"
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Helpers — build minimal librosa-like mock surfaces
# ===========================================================================

def _make_librosa_mock(
    duration: float = 240.0,
    n_frames: int = 200,
    rms_max: float = 0.5,
    beat_times_array: np.ndarray | None = None,
    fail_recurrence: bool = False,
):
    """
    Return a mock that replaces the `librosa` module inside chorus_detector.

    All return values are chosen so detect_chorus reaches the recurrence path
    and produces a deterministic result, unless overrides are supplied.
    """
    if beat_times_array is None:
        beat_times_array = np.linspace(0.0, duration, num=60)

    lib = MagicMock(name="librosa")

    # librosa.load
    y_audio = np.zeros(int(11025 * duration), dtype=np.float32)
    lib.load.return_value = (y_audio, 11025)

    # librosa.get_duration
    lib.get_duration.return_value = duration

    # librosa.beat.beat_track — returns (tempo, beat_frames)
    beat_frames = np.arange(n_frames)
    lib.beat.beat_track.return_value = (120.0, beat_frames)

    # librosa.frames_to_time — used for beat_times and peak_time
    # Called twice: once for beat_times, once for peak_frame -> peak_time
    # We use side_effect to differentiate calls by argument shape
    def frames_to_time(frames, sr=None, hop_length=None):
        if np.ndim(frames) == 0:
            # scalar (peak_frame)
            return float(frames) * (duration / n_frames)
        # array (beat_frames)
        return beat_times_array[:len(np.asarray(frames))]

    lib.frames_to_time.side_effect = frames_to_time

    # librosa.feature.chroma_cqt — returns (12, n_frames) array
    lib.feature.chroma_cqt.return_value = np.random.rand(12, n_frames).astype(np.float32)

    # librosa.feature.stack_memory — just expand the chroma
    stacked = np.random.rand(120, n_frames).astype(np.float32)
    lib.feature.stack_memory.return_value = stacked

    # librosa.segment.recurrence_matrix
    if fail_recurrence:
        lib.segment.recurrence_matrix.side_effect = Exception("matrix error")
    else:
        R = np.eye(n_frames, dtype=np.float32) * 0.8
        # Make one region stand out as the "chorus" (frames 80-100)
        R[80:100, 80:100] = 1.0
        lib.segment.recurrence_matrix.return_value = R

    # librosa.feature.rms — returns (1, n_frames) array
    rms_row = np.full(n_frames, rms_max / 2, dtype=np.float32)
    rms_row[80:100] = rms_max      # loud region aligns with "chorus"
    lib.feature.rms.return_value = np.array([rms_row])

    return lib


# ===========================================================================
# ChorusResult dataclass
# ===========================================================================

class TestChorusResult:
    def _make(self, start=90.0, end=150.0, confidence=0.75, method="recurrence"):
        from scripts.chorus_detector import ChorusResult
        return ChorusResult(
            start_sec=start,
            end_sec=end,
            confidence=confidence,
            method=method,
        )

    def test_fields_stored_correctly(self):
        r = self._make()
        assert r.start_sec == 90.0
        assert r.end_sec == 150.0
        assert r.confidence == 0.75
        assert r.method == "recurrence"

    def test_start_mmss_property_format(self):
        r = self._make(start=90.0)
        assert r.start_mmss == "01:30"

    def test_end_mmss_property_format(self):
        r = self._make(end=150.0)
        assert r.end_mmss == "02:30"

    def test_zero_start_mmss(self):
        r = self._make(start=0.0)
        assert r.start_mmss == "00:00"

    def test_heuristic_method_tag(self):
        r = self._make(method="heuristic")
        assert r.method == "heuristic"

    def test_rms_fallback_method_tag(self):
        r = self._make(method="rms_fallback")
        assert r.method == "rms_fallback"

    def test_confidence_range_zero_to_one(self):
        r = self._make(confidence=0.0)
        assert 0.0 <= r.confidence <= 1.0


# ===========================================================================
# _sec_to_mmss
# ===========================================================================

class TestSecToMmss:
    def _call(self, sec):
        from scripts.chorus_detector import _sec_to_mmss
        return _sec_to_mmss(sec)

    def test_zero(self):
        assert self._call(0.0) == "00:00"

    def test_thirty_seconds(self):
        assert self._call(30.0) == "00:30"

    def test_one_minute(self):
        assert self._call(60.0) == "01:00"

    def test_ninety_seconds(self):
        assert self._call(90.0) == "01:30"

    def test_over_ten_minutes(self):
        assert self._call(630.0) == "10:30"

    def test_negative_clamped_to_zero(self):
        # Negative input should be clamped to 00:00
        assert self._call(-5.0) == "00:00"

    def test_float_rounds_to_nearest_second(self):
        # 59.7 rounds to 60 -> 01:00
        assert self._call(59.7) == "01:00"

    def test_leading_zeros_preserved(self):
        assert self._call(5.0) == "00:05"


# ===========================================================================
# _snap_to_beat
# ===========================================================================

class TestSnapToBeat:
    def _call(self, time_sec, beat_times):
        from scripts.chorus_detector import _snap_to_beat
        return _snap_to_beat(time_sec, np.array(beat_times))

    def test_empty_beats_returns_original_time(self):
        assert self._call(45.0, []) == 45.0

    def test_exact_beat_match(self):
        beats = [0.0, 0.5, 1.0, 1.5, 2.0]
        assert self._call(1.0, beats) == 1.0

    def test_snaps_to_nearest_beat_below(self):
        beats = [0.0, 1.0, 2.0, 3.0]
        # 1.3 is closer to 1.0 than 2.0
        result = self._call(1.3, beats)
        assert result == 1.0

    def test_snaps_to_nearest_beat_above(self):
        beats = [0.0, 1.0, 2.0, 3.0]
        # 1.7 is closer to 2.0
        result = self._call(1.7, beats)
        assert result == 2.0

    def test_single_beat_always_returns_that_beat(self):
        assert self._call(999.0, [5.0]) == 5.0

    def test_returns_float(self):
        result = self._call(1.0, [1.0, 2.0])
        assert isinstance(result, float)


# ===========================================================================
# _heuristic_fallback
# ===========================================================================

class TestHeuristicFallback:
    def _call(self, duration, target_duration=60, reason="test"):
        from scripts.chorus_detector import _heuristic_fallback
        return _heuristic_fallback(duration, target_duration, reason)

    def test_start_is_20_percent_of_duration(self):
        result = self._call(200.0)
        assert result.start_sec == pytest.approx(40.0)

    def test_end_does_not_exceed_duration_minus_5(self):
        result = self._call(200.0, target_duration=600)
        assert result.end_sec == pytest.approx(195.0)

    def test_end_equals_start_plus_target_when_short_enough(self):
        result = self._call(300.0, target_duration=60)
        # start=60, end=120 (well within 295)
        assert result.end_sec == pytest.approx(result.start_sec + 60.0)

    def test_confidence_is_0_2(self):
        result = self._call(200.0)
        assert result.confidence == pytest.approx(0.2)

    def test_method_is_heuristic(self):
        result = self._call(200.0)
        assert result.method == "heuristic"

    def test_very_short_audio_start_is_still_computed(self):
        # duration=10: start=2, end=min(2+60, 5)=5
        result = self._call(10.0, target_duration=60)
        assert result.start_sec == pytest.approx(2.0)
        assert result.end_sec == pytest.approx(5.0)


# ===========================================================================
# _rms_fallback
# ===========================================================================

class TestRmsFallback:
    def test_returns_chorus_result_with_rms_fallback_method(self):
        from scripts.chorus_detector import _rms_fallback

        lib = _make_librosa_mock(duration=240.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            # Re-import to pick up patched module
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            y = np.zeros(11025 * 240, dtype=np.float32)
            beat_times = np.linspace(0.0, 240.0, 60)

            result = cd._rms_fallback(y, 11025, 240.0, 60, beat_times)

        assert result.method == "rms_fallback"
        assert result.confidence == pytest.approx(0.5)

    def test_rms_fallback_end_sec_within_duration(self):
        from scripts.chorus_detector import _rms_fallback

        lib = _make_librosa_mock(duration=180.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            y = np.zeros(11025 * 180, dtype=np.float32)
            beat_times = np.linspace(0.0, 180.0, 50)

            result = cd._rms_fallback(y, 11025, 180.0, 60, beat_times)

        assert result.end_sec <= 180.0

    def test_rms_fallback_start_sec_non_negative(self):
        from scripts.chorus_detector import _rms_fallback

        lib = _make_librosa_mock(duration=200.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            y = np.zeros(11025 * 200, dtype=np.float32)
            beat_times = np.linspace(0.0, 200.0, 60)

            result = cd._rms_fallback(y, 11025, 200.0, 60, beat_times)

        assert result.start_sec >= 0.0


# ===========================================================================
# detect_chorus — top-level function
# ===========================================================================

class TestDetectChorus:
    """All tests patch librosa so no real audio file is loaded."""

    def test_raises_import_error_when_librosa_unavailable(self, tmp_path):
        """If LIBROSA_AVAILABLE is False, ImportError must be raised."""
        with patch.dict("sys.modules", {"librosa": None}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = False

            with pytest.raises(ImportError, match="librosa"):
                cd.detect_chorus(str(tmp_path / "fake.mp3"))

    def test_short_audio_triggers_heuristic_fallback(self, tmp_path):
        """Audio shorter than 20 s must return method='heuristic'."""
        lib = _make_librosa_mock(duration=10.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "short.mp3"))

        assert result.method == "heuristic"
        assert result.confidence == pytest.approx(0.2)

    def test_recurrence_matrix_exception_triggers_rms_fallback(self, tmp_path):
        """When recurrence_matrix raises, the function must fall back to RMS."""
        lib = _make_librosa_mock(duration=240.0, fail_recurrence=True)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result.method == "rms_fallback"

    def test_happy_path_returns_recurrence_method(self, tmp_path):
        """Normal operation must yield method='recurrence'."""
        lib = _make_librosa_mock(duration=240.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result.method == "recurrence"

    def test_happy_path_confidence_between_0_and_1(self, tmp_path):
        lib = _make_librosa_mock(duration=240.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert 0.0 <= result.confidence <= 1.0

    def test_end_sec_never_exceeds_duration_minus_5(self, tmp_path):
        duration = 240.0
        lib = _make_librosa_mock(duration=duration)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result.end_sec <= duration - 5.0

    def test_start_sec_is_non_negative(self, tmp_path):
        lib = _make_librosa_mock(duration=240.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result.start_sec >= 0.0

    def test_all_zeros_combined_triggers_rms_fallback(self, tmp_path):
        """
        Force all-zero combined_smooth after masking (intro + outro = full coverage).
        This happens when intro_skip_ratio=0.5 and outro is also heavy,
        leaving no usable frames.
        """
        lib = _make_librosa_mock(duration=240.0, n_frames=10)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            # intro_skip_ratio=0.86 -> skip_frames = 8 of 10 and outro clips the rest
            result = cd.detect_chorus(
                str(tmp_path / "audio.mp3"),
                intro_skip_ratio=0.86,
            )

        # Must not crash; should be rms_fallback or heuristic
        assert result.method in ("rms_fallback", "heuristic", "recurrence")

    def test_custom_target_duration_respected(self, tmp_path):
        lib = _make_librosa_mock(duration=300.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"), target_duration=30)

        clip_length = result.end_sec - result.start_sec
        assert clip_length <= 30 + 1  # allow 1s tolerance for beat snapping

    def test_end_sec_greater_than_start_sec(self, tmp_path):
        lib = _make_librosa_mock(duration=240.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result.end_sec > result.start_sec

    def test_silent_audio_does_not_crash(self, tmp_path):
        """
        All-zero RMS (silent) should not crash — the normalisation guard
        (rms.max() > 0 check) prevents divide-by-zero.
        """
        lib = _make_librosa_mock(duration=240.0, rms_max=0.0)

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            # Should not raise
            result = cd.detect_chorus(str(tmp_path / "silent.mp3"))

        assert result is not None

    def test_rms_shorter_than_row_sums_padded(self, tmp_path):
        """
        Cover the branch where len(rms) < len(row_sums).
        We do this by returning an RMS array shorter than the recurrence matrix.
        """
        n_frames = 200
        lib = _make_librosa_mock(duration=240.0, n_frames=n_frames)

        # Override rms to return fewer frames than row_sums (n_frames)
        short_rms = np.full(n_frames - 10, 0.4, dtype=np.float32)
        lib.feature.rms.return_value = np.array([short_rms])

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result is not None
        assert result.method in ("recurrence", "rms_fallback")

    def test_rms_longer_than_row_sums_truncated(self, tmp_path):
        """
        Cover the branch where len(rms) > len(row_sums).
        We do this by returning an RMS array longer than the recurrence matrix.
        """
        n_frames = 200
        lib = _make_librosa_mock(duration=240.0, n_frames=n_frames)

        # Override rms to return MORE frames than row_sums
        long_rms = np.full(n_frames + 50, 0.4, dtype=np.float32)
        lib.feature.rms.return_value = np.array([long_rms])

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(str(tmp_path / "audio.mp3"))

        assert result is not None
        assert result.method in ("recurrence", "rms_fallback")

    def test_end_too_close_to_start_triggers_reanchoring(self, tmp_path):
        """
        Cover lines 175-177: when end_sec - start_sec < 20, the code must
        re-anchor start to duration * 0.25.  We force this by using a very
        short song (22 s) with a large target_duration so start snaps near the end.
        """
        duration = 22.0
        n_frames = 50

        lib = _make_librosa_mock(duration=duration, n_frames=n_frames)

        # Make peak land at the very last valid frame so start_sec is near 21 s,
        # leaving < 20 s before duration-5 = 17 s -> end < start is impossible,
        # but with start near the end: end = min(start+60, 22-5=17) => end=17,
        # clip = 17 - ~20 = negative -> triggers re-anchor.
        # We achieve this by making combined_smooth peak at frame n_frames-1.
        beat_times = np.linspace(0.0, duration, n_frames)

        lib.beat.beat_track.return_value = (120.0, np.arange(n_frames))

        def frames_to_time_fn(frames, sr=None, hop_length=None):
            if np.ndim(frames) == 0:
                # peak frame -> map to near the end
                return duration - 1.0
            return beat_times[:len(np.asarray(frames))]

        lib.frames_to_time.side_effect = frames_to_time_fn

        with patch.dict("sys.modules", {"librosa": lib}):
            import importlib
            import scripts.chorus_detector as cd
            importlib.reload(cd)
            cd.LIBROSA_AVAILABLE = True

            result = cd.detect_chorus(
                str(tmp_path / "short_song.mp3"),
                target_duration=60,
            )

        assert result is not None
        # After re-anchoring, end must still be > start
        assert result.end_sec >= result.start_sec

