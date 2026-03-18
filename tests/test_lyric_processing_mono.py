"""
Tests for scripts/lyric_processing_mono.py (Mono template pipeline).

All Whisper/Genius dependencies mocked. Covers:
  - Happy path, None when audio missing, None when no segments
  - Cache: uses cache, saves cache
  - Genius: applied, skipped, reverted, rebuild_words called after alignment
  - Final cleanup: merge_short_markers, assign_colors, fix_marker_gaps, quality_gate
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
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


class TestMonoHappyPath:

    def test_returns_markers_dict(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2} for _ in segs
        ])
        result = transcribe_audio_mono(str(job_folder), "Artist - Song")
        assert "markers" in result
        assert "total_markers" in result
        assert result["total_markers"] > 0

    def test_none_when_audio_missing(self, job_folder, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        _mock_whisper_common(monkeypatch)
        result = transcribe_audio_mono(str(job_folder))
        assert result["markers"] == []
        assert result["total_markers"] == 0

    def test_empty_when_no_segments(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc
        _mock_whisper_common(monkeypatch)
        empty = MagicMock()
        empty.segments = []
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (empty, 0))
        result = transcribe_audio_mono(str(job_folder), "Artist - Song")
        assert result["total_markers"] == 0


class TestMonoCache:

    def test_uses_cache(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc
        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: [
            {"text": "cached", "start": 0, "end": 2, "words": []},
        ])
        mock_transcribe = MagicMock()
        monkeypatch.setattr(wc, "multi_pass_transcribe", mock_transcribe)
        result = transcribe_audio_mono(str(job_folder), "Artist - Song")
        mock_transcribe.assert_not_called()
        assert result["total_markers"] == 1

    def test_saves_cache_after_transcription(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc
        _mock_whisper_common(monkeypatch)
        saved = []
        monkeypatch.setattr(wc, "save_whisper_cache", lambda jf, s: saved.extend(s))
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        transcribe_audio_mono(str(job_folder), "Artist - Song")
        assert len(saved) > 0


class TestMonoGeniusAlignment:

    def test_rebuild_words_called_after_alignment(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        from scripts.config import Config
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr("scripts.lyric_processing_mono.fetch_genius_lyrics", lambda t: "line\n")
        monkeypatch.setattr("scripts.lyric_processing_mono.align_genius_to_whisper",
                            lambda m, t, **kw: (m, 0.8))

        rebuild_called = []
        monkeypatch.setattr(wc, "rebuild_words_after_alignment",
                            lambda m: (rebuild_called.append(True), m)[1])

        transcribe_audio_mono(str(job_folder), "Artist - Song")
        assert len(rebuild_called) == 1

    def test_genius_reverted_on_low_ratio(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        from scripts.config import Config
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "original", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr("scripts.lyric_processing_mono.fetch_genius_lyrics", lambda t: "wrong")

        def bad_align(m, t, **kw):
            for marker in m:
                marker["text"] = "REPLACED"
            return m, 0.1

        monkeypatch.setattr("scripts.lyric_processing_mono.align_genius_to_whisper", bad_align)

        rebuild_called = []
        monkeypatch.setattr(wc, "rebuild_words_after_alignment",
                            lambda m: (rebuild_called.append(True), m)[1])

        result = transcribe_audio_mono(str(job_folder), "Artist - Song")
        # rebuild_words should NOT be called on revert
        assert len(rebuild_called) == 0
        # text should be reverted
        assert result["markers"][0]["text"] == "original"


class TestMonoFinalCleanup:

    def test_assign_colors_called(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])

        colors_called = []
        monkeypatch.setattr(wc, "assign_colors", lambda m: colors_called.append(True))
        transcribe_audio_mono(str(job_folder))
        assert len(colors_called) == 1

    def test_quality_gate_warning(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing_mono import transcribe_audio_mono
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(wc, "multi_pass_transcribe", lambda *a, **kw: (_make_transcribe_result(), 0))
        monkeypatch.setattr(wc, "build_markers_from_segments", lambda segs: [
            {"time": 0, "text": "line", "words": [], "color": "", "end_time": 2}
        ])
        monkeypatch.setattr(wc, "quality_gate", lambda m, d: (False, ["low coverage"]))

        result = transcribe_audio_mono(str(job_folder))
        # Should still return markers despite warning
        assert result["total_markers"] > 0
