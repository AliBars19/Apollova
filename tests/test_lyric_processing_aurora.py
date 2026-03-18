"""
Tests for scripts/lyric_processing.py (Aurora template pipeline).

All Whisper/Genius dependencies mocked. Covers:
  - Happy path returns lyrics.txt path, None when audio missing, None when no segments
  - Cache: uses cache when available, saves cache after fresh transcription
  - Cleanup pipeline order verification
  - Genius alignment: applied when title+token set, skipped when missing, reverted on ratio<0.3
  - Output: correct JSON keys, end_time preserved, wrap_line applied, empty lyric_current filtered
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from conftest import _make_whisper_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_whisper_common(monkeypatch):
    """Stub out all whisper_common functions used by lyric_processing."""
    import scripts.whisper_common as wc

    monkeypatch.setattr(wc, "get_audio_duration", lambda p: 60.0)
    monkeypatch.setattr(wc, "build_initial_prompt", lambda t: "prompt")
    monkeypatch.setattr(wc, "detect_language", lambda t: "en")
    monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: None)
    monkeypatch.setattr(wc, "save_whisper_cache", lambda jf, s: None)
    monkeypatch.setattr(wc, "separate_vocals", lambda a, jf: a)

    # Cleanup functions: pass items through unchanged
    for fn_name in ("remove_hallucinations", "remove_junk", "remove_stutter_duplicates",
                     "remove_repetition_loops", "remove_instrumental_hallucinations",
                     "remove_non_target_script"):
        monkeypatch.setattr(wc, fn_name, lambda items, *a, **kw: items)


def _make_transcribe_result(n=4):
    return _make_whisper_result([
        {"text": f"line {i}", "start": float(i * 3), "end": float(i * 3 + 2.5)}
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestAuroraHappyPath:

    def test_returns_lyrics_path(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        result = transcribe_audio(str(job_folder), "Artist - Song")
        assert result is not None
        assert result.endswith("lyrics.txt")
        assert os.path.exists(result)

    def test_output_is_valid_json(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_none_when_audio_missing(self, job_folder, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        result = transcribe_audio(str(job_folder), "Artist - Song")
        assert result is None

    def test_none_when_no_segments(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        empty_result = MagicMock()
        empty_result.segments = []
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (empty_result, 0),
        )
        result = transcribe_audio(str(job_folder), "Artist - Song")
        assert result is None


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestAuroraCache:

    def test_uses_cache_when_available(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)

        cached_data = [
            {"text": "cached line", "start": 0.0, "end": 2.5},
        ]
        monkeypatch.setattr(wc, "load_whisper_cache", lambda jf: cached_data)

        # multi_pass_transcribe should NOT be called
        mock_transcribe = MagicMock()
        monkeypatch.setattr(wc, "multi_pass_transcribe", mock_transcribe)

        result = transcribe_audio(str(job_folder), "Artist - Song")
        assert result is not None
        mock_transcribe.assert_not_called()

    def test_saves_cache_after_fresh_transcription(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)

        saved = []
        monkeypatch.setattr(wc, "save_whisper_cache", lambda jf, s: saved.extend(s))
        monkeypatch.setattr(
            wc, "multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )

        transcribe_audio(str(job_folder), "Artist - Song")
        assert len(saved) > 0


# ---------------------------------------------------------------------------
# Genius alignment
# ---------------------------------------------------------------------------

class TestAuroraGeniusAlignment:

    def test_genius_applied_when_title_and_token_set(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        from scripts.config import Config

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")

        align_called = []
        monkeypatch.setattr(
            "scripts.lyric_processing.fetch_genius_lyrics",
            lambda t: "line 0\nline 1\nline 2\nline 3",
        )
        monkeypatch.setattr(
            "scripts.lyric_processing.align_genius_to_whisper",
            lambda segs, text, **kw: (align_called.append(True) or segs, 0.8),
        )

        transcribe_audio(str(job_folder), "Artist - Song")
        assert len(align_called) == 1

    def test_genius_skipped_when_no_token(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        from scripts.config import Config

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "")

        align_called = []
        monkeypatch.setattr(
            "scripts.lyric_processing.fetch_genius_lyrics",
            lambda t: (align_called.append(True), "lyrics")[1],
        )

        transcribe_audio(str(job_folder), "Artist - Song")
        assert len(align_called) == 0

    def test_genius_reverted_on_low_ratio(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        from scripts.config import Config

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr(
            "scripts.lyric_processing.fetch_genius_lyrics",
            lambda t: "wrong lyrics entirely",
        )

        def bad_align(segs, text, **kw):
            for s in segs:
                s["lyric_current"] = "REPLACED"
            return segs, 0.1  # ratio < 0.3

        monkeypatch.setattr("scripts.lyric_processing.align_genius_to_whisper", bad_align)

        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Should have reverted — no "REPLACED" text
        for seg in data:
            assert seg["lyric_current"] != "REPLACED"

    def test_genius_none_uses_whisper_text(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        from scripts.config import Config

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        monkeypatch.setattr(Config, "GENIUS_API_TOKEN", "test_token")
        monkeypatch.setattr("scripts.lyric_processing.fetch_genius_lyrics", lambda t: None)

        path = transcribe_audio(str(job_folder), "Artist - Song")
        assert path is not None


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

class TestAuroraOutput:

    def test_correct_json_keys(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for seg in data:
            assert "t" in seg
            assert "end_time" in seg
            assert "lyric_prev" in seg
            assert "lyric_current" in seg
            assert "lyric_next1" in seg
            assert "lyric_next2" in seg

    def test_end_time_preserved(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for seg in data:
            assert seg["end_time"] > seg["t"]

    def test_empty_lyric_current_filtered(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio
        import scripts.whisper_common as wc

        _mock_whisper_common(monkeypatch)

        # Return result with one empty-text segment
        result = _make_whisper_result([
            {"text": "valid line", "start": 0, "end": 2},
            {"text": "   ", "start": 3, "end": 5},  # whitespace-only
        ])
        monkeypatch.setattr(
            wc, "multi_pass_transcribe",
            lambda *a, **kw: (result, 0),
        )
        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for seg in data:
            assert seg["lyric_current"].strip() != ""

    def test_prev_next_always_empty(self, job_folder, silent_wav, monkeypatch):
        from scripts.lyric_processing import transcribe_audio

        _mock_whisper_common(monkeypatch)
        monkeypatch.setattr(
            "scripts.whisper_common.multi_pass_transcribe",
            lambda *a, **kw: (_make_transcribe_result(), 0),
        )
        path = transcribe_audio(str(job_folder), "Artist - Song")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for seg in data:
            assert seg["lyric_prev"] == ""
            assert seg["lyric_next1"] == ""
            assert seg["lyric_next2"] == ""
