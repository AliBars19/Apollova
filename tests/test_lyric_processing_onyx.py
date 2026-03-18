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
    monkeypatch.setattr(wc, "detect_language", lambda t: "en")
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
        monkeypatch.setattr("scripts.lyric_processing_onyx.fetch_genius_lyrics", lambda t: "line\n")
        monkeypatch.setattr("scripts.lyric_processing_onyx.align_genius_to_whisper",
                            lambda m, t, **kw: (m, 0.8))

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
        monkeypatch.setattr("scripts.lyric_processing_onyx.fetch_genius_lyrics", lambda t: "wrong")

        def bad_align(m, t, **kw):
            for marker in m:
                marker["text"] = "REPLACED"
            return m, 0.1

        monkeypatch.setattr("scripts.lyric_processing_onyx.align_genius_to_whisper", bad_align)

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
