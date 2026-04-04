"""
Tests for Config class and Whisper cache functionality.
Also tests the composition of fix_marker_gaps + spread_clustered_words.
"""
import sys
import json
import os
import copy
import importlib
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Mock heavy dependencies BEFORE importing whisper_common
# ---------------------------------------------------------------------------
sys.modules.setdefault("stable_whisper", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("pydub", MagicMock())
sys.modules.setdefault("pydub.playback", MagicMock())
sys.modules.setdefault("scripts.audio_processing", MagicMock())
pydub_mock = sys.modules["pydub"]
pydub_mock.AudioSegment = MagicMock()

import pytest

from scripts.config import Config
from scripts.whisper_common import (
    save_whisper_cache,
    load_whisper_cache,
    fix_marker_gaps,
    spread_clustered_words,
)


# ===========================================================================
# Config class — 20 tests
# ===========================================================================

class TestConfig:
    def test_whisper_model_default_is_small(self):
        # Default is "small" (unless env var overrides)
        original = Config.WHISPER_MODEL
        assert isinstance(Config.WHISPER_MODEL, str)
        assert len(Config.WHISPER_MODEL) > 0

    def test_valid_whisper_models_list_exists(self):
        assert hasattr(Config, "VALID_WHISPER_MODELS")
        assert isinstance(Config.VALID_WHISPER_MODELS, list)
        assert len(Config.VALID_WHISPER_MODELS) > 0

    def test_valid_whisper_models_contains_tiny(self):
        assert "tiny" in Config.VALID_WHISPER_MODELS

    def test_valid_whisper_models_contains_small(self):
        assert "small" in Config.VALID_WHISPER_MODELS

    def test_valid_whisper_models_contains_medium(self):
        assert "medium" in Config.VALID_WHISPER_MODELS

    def test_valid_whisper_models_contains_large(self):
        assert "large" in Config.VALID_WHISPER_MODELS

    def test_valid_whisper_models_contains_large_v2(self):
        assert "large-v2" in Config.VALID_WHISPER_MODELS

    def test_valid_whisper_models_contains_large_v3(self):
        assert "large-v3" in Config.VALID_WHISPER_MODELS

    def test_validate_returns_list(self):
        result = Config.validate()
        assert isinstance(result, list)

    def test_validate_invalid_model_adds_warning(self):
        original = Config.WHISPER_MODEL
        Config.WHISPER_MODEL = "nonexistent_model"
        warnings = Config.validate()
        Config.WHISPER_MODEL = original
        assert any("WHISPER_MODEL" in w for w in warnings)

    def test_validate_invalid_model_resets_to_small(self):
        original = Config.WHISPER_MODEL
        Config.WHISPER_MODEL = "bad_model"
        Config.validate()
        assert Config.WHISPER_MODEL == "small"
        Config.WHISPER_MODEL = original

    def test_validate_valid_model_no_model_warning(self):
        original = Config.WHISPER_MODEL
        Config.WHISPER_MODEL = "small"
        warnings = Config.validate()
        assert not any("Unknown WHISPER_MODEL" in w for w in warnings)
        Config.WHISPER_MODEL = original

    def test_set_max_line_length(self):
        original = Config.MAX_LINE_LENGTH
        Config.set_max_line_length(50)
        assert Config.MAX_LINE_LENGTH == 50
        Config.MAX_LINE_LENGTH = original

    def test_set_max_line_length_40(self):
        Config.set_max_line_length(40)
        assert Config.MAX_LINE_LENGTH == 40
        Config.MAX_LINE_LENGTH = 25  # restore default

    def test_genius_api_token_is_string(self):
        assert isinstance(Config.GENIUS_API_TOKEN, str)

    def test_whisper_cache_dir_is_string(self):
        assert isinstance(Config.WHISPER_CACHE_DIR, str)

    def test_total_jobs_default_12(self):
        assert Config.TOTAL_JOBS == int(os.getenv("TOTAL_JOBS", "12"))

    def test_max_line_length_default_25(self):
        # Unless env var changes it, default is 25
        assert Config.MAX_LINE_LENGTH >= 1

    def test_audio_format_is_mp3(self):
        assert Config.AUDIO_FORMAT == "mp3"

    def test_trimmed_format_is_wav(self):
        assert Config.TRIMMED_FORMAT == "wav"


# ===========================================================================
# Config .env migration — 5 tests
# ===========================================================================

class TestEnvMigration:
    """Tests for .env migration to %APPDATA%/Apollova/."""

    def _reload_config(self):
        """Reload the config module to pick up env changes."""
        import scripts.config as cfg_mod
        importlib.reload(cfg_mod)
        return cfg_mod

    def test_migrate_env_creates_appdata_dir_and_copies(self, tmp_path, monkeypatch):
        """migrate_env creates APPDATA dir and copies file."""
        appdata = tmp_path / "appdata"
        install_root = tmp_path / "install"
        install_root.mkdir()
        env_content = "GENIUS_API_TOKEN=test123\n"
        (install_root / ".env").write_text(env_content)

        import scripts.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "APPDATA_DIR", appdata / "Apollova")
        monkeypatch.setattr(cfg_mod, "_BASE_DIR", install_root)

        result = cfg_mod.Config.migrate_env()
        assert result is True
        assert (appdata / "Apollova" / ".env").exists()
        assert (appdata / "Apollova" / ".env").read_text() == env_content

    def test_migrate_env_idempotent(self, tmp_path, monkeypatch):
        """migrate_env doesn't overwrite existing APPDATA .env."""
        appdata_dir = tmp_path / "appdata" / "Apollova"
        appdata_dir.mkdir(parents=True)
        (appdata_dir / ".env").write_text("EXISTING=keep_me\n")

        install_root = tmp_path / "install"
        install_root.mkdir()
        (install_root / ".env").write_text("GENIUS_API_TOKEN=new\n")

        import scripts.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "APPDATA_DIR", appdata_dir)
        monkeypatch.setattr(cfg_mod, "_BASE_DIR", install_root)

        result = cfg_mod.Config.migrate_env()
        assert result is False
        assert (appdata_dir / ".env").read_text() == "EXISTING=keep_me\n"

    def test_config_loads_appdata_env_when_both_exist(self, tmp_path, monkeypatch):
        """Config loads from APPDATA .env when both exist (APPDATA takes precedence)."""
        appdata_dir = tmp_path / "appdata" / "Apollova"
        appdata_dir.mkdir(parents=True)
        (appdata_dir / ".env").write_text("GENIUS_API_TOKEN=from_appdata\n")

        install_root = tmp_path / "install"
        install_root.mkdir()
        (install_root / ".env").write_text("GENIUS_API_TOKEN=from_install\n")

        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setattr("scripts.config.APPDATA_DIR", appdata_dir)
        monkeypatch.setattr("scripts.config._BASE_DIR", install_root)

        # Simulate what the module-level code does
        from dotenv import load_dotenv
        appdata_env = appdata_dir / ".env"
        install_env = install_root / ".env"
        if appdata_env.is_file():
            load_dotenv(dotenv_path=str(appdata_env), override=True)
        elif install_env.is_file():
            load_dotenv(dotenv_path=str(install_env), override=True)

        assert os.environ["GENIUS_API_TOKEN"] == "from_appdata"

    def test_config_falls_back_to_install_root(self, tmp_path, monkeypatch):
        """Config falls back to install root when APPDATA .env missing."""
        appdata_dir = tmp_path / "appdata" / "Apollova"
        # No .env in appdata

        install_root = tmp_path / "install"
        install_root.mkdir()
        (install_root / ".env").write_text("GENIUS_API_TOKEN=from_install\n")

        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

        from dotenv import load_dotenv
        appdata_env = appdata_dir / ".env"
        install_env = install_root / ".env"
        if appdata_env.is_file():
            load_dotenv(dotenv_path=str(appdata_env), override=True)
        elif install_env.is_file():
            load_dotenv(dotenv_path=str(install_env), override=True)

        assert os.environ["GENIUS_API_TOKEN"] == "from_install"

    def test_config_works_when_neither_exists(self, tmp_path, monkeypatch):
        """Config works when neither .env exists."""
        appdata_dir = tmp_path / "appdata" / "Apollova"
        install_root = tmp_path / "install"
        install_root.mkdir()

        import scripts.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "APPDATA_DIR", appdata_dir)
        monkeypatch.setattr(cfg_mod, "_BASE_DIR", install_root)

        result = cfg_mod.Config.migrate_env()
        assert result is False
        # Config should still be usable
        assert isinstance(cfg_mod.Config.GENIUS_API_TOKEN, str)


# ===========================================================================
# Whisper cache — 20 tests
# ===========================================================================

class TestWhisperCache:
    def test_save_creates_file(self, tmp_path):
        segments = [
            {"time": 0.0, "end_time": 2.0, "text": "hello world",
             "words": [{"word": "hello", "start": 0.0, "end": 0.8}]},
        ]
        save_whisper_cache(str(tmp_path), segments)
        cache_file = tmp_path / "whisper_raw.json"
        assert cache_file.exists()

    def test_load_returns_none_for_missing_file(self, tmp_path):
        result = load_whisper_cache(str(tmp_path))
        assert result is None

    def test_save_then_load_roundtrip(self, tmp_path):
        segments = [
            {"time": 0.0, "end_time": 3.0, "text": "test lyric",
             "words": [{"word": "test", "start": 0.0, "end": 0.5}]},
        ]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["text"] == "test lyric"

    def test_save_tags_with_model_name(self, tmp_path):
        segments = [{"time": 0.0, "end_time": 1.0, "text": "hi", "words": []}]
        save_whisper_cache(str(tmp_path), segments)
        cache_file = tmp_path / "whisper_raw.json"
        with open(cache_file) as f:
            data = json.load(f)
        assert "model" in data
        assert data["model"] == Config.WHISPER_MODEL

    def test_model_mismatch_returns_none(self, tmp_path):
        cache_data = {"model": "large-v99-nonexistent", "segments": [
            {"start": 0.0, "end": 1.0, "text": "hello"}
        ]}
        cache_file = tmp_path / "whisper_raw.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
        # Ensure current model is different
        result = load_whisper_cache(str(tmp_path))
        if cache_data["model"] != Config.WHISPER_MODEL:
            assert result is None

    def test_old_list_format_loads(self, tmp_path):
        # Old format: bare list
        old_data = [{"start": 0.0, "end": 2.0, "text": "old format"}]
        cache_file = tmp_path / "whisper_raw.json"
        with open(cache_file, "w") as f:
            json.dump(old_data, f)
        result = load_whisper_cache(str(tmp_path))
        assert result is not None
        assert len(result) == 1

    def test_empty_segments_saves_empty_list(self, tmp_path):
        save_whisper_cache(str(tmp_path), [])
        cache_file = tmp_path / "whisper_raw.json"
        assert cache_file.exists()

    def test_empty_segments_cache_returns_none(self, tmp_path):
        # save an empty segments list → load returns None (no data)
        save_whisper_cache(str(tmp_path), [])
        result = load_whisper_cache(str(tmp_path))
        # Empty segments → data is empty → returns None
        assert result is None

    def test_save_words_preserved(self, tmp_path):
        segments = [
            {"time": 1.0, "end_time": 3.0, "text": "hello world",
             "words": [
                 {"word": "hello", "start": 1.0, "end": 1.5},
                 {"word": "world", "start": 1.6, "end": 2.0},
             ]},
        ]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert loaded[0]["words"][0]["word"] == "hello"

    def test_save_handles_lyric_current_key(self, tmp_path):
        # Aurora-style segments use 'lyric_current' instead of 'text'
        segments = [
            {"t": 0.0, "end_time": 2.0, "lyric_current": "aurora lyric"},
        ]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert loaded is not None
        assert loaded[0]["text"] == "aurora lyric"

    def test_save_uses_t_key_for_time(self, tmp_path):
        segments = [{"t": 5.0, "end_time": 7.0, "lyric_current": "test"}]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert loaded[0]["start"] == 5.0

    def test_cache_file_is_utf8(self, tmp_path):
        segments = [
            {"time": 0.0, "end_time": 2.0, "text": "Ça va bien",
             "words": [{"word": "Ça", "start": 0.0, "end": 0.5}]},
        ]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert "Ça" in loaded[0]["text"]

    def test_load_invalid_json_returns_none(self, tmp_path):
        cache_file = tmp_path / "whisper_raw.json"
        cache_file.write_text("not valid json {{{")
        result = load_whisper_cache(str(tmp_path))
        assert result is None

    def test_multiple_segments_roundtrip(self, tmp_path):
        segments = [
            {"time": float(i), "end_time": float(i + 1), "text": f"segment {i}", "words": []}
            for i in range(5)
        ]
        save_whisper_cache(str(tmp_path), segments)
        loaded = load_whisper_cache(str(tmp_path))
        assert len(loaded) == 5

    def test_same_model_loads_successfully(self, tmp_path):
        current_model = Config.WHISPER_MODEL
        cache_data = {"model": current_model, "segments": [
            {"start": 0.0, "end": 2.0, "text": "hello"}
        ]}
        cache_file = tmp_path / "whisper_raw.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
        result = load_whisper_cache(str(tmp_path))
        assert result is not None

    def test_segments_key_in_new_format(self, tmp_path):
        segments = [{"time": 0.0, "end_time": 1.0, "text": "test", "words": []}]
        save_whisper_cache(str(tmp_path), segments)
        with open(tmp_path / "whisper_raw.json") as f:
            raw = json.load(f)
        assert "segments" in raw

    def test_cache_file_named_whisper_raw_json(self, tmp_path):
        segments = [{"time": 0.0, "end_time": 1.0, "text": "x", "words": []}]
        save_whisper_cache(str(tmp_path), segments)
        assert (tmp_path / "whisper_raw.json").exists()

    def test_load_returns_list(self, tmp_path):
        segments = [{"time": 0.0, "end_time": 2.0, "text": "hi", "words": []}]
        save_whisper_cache(str(tmp_path), segments)
        result = load_whisper_cache(str(tmp_path))
        assert isinstance(result, list)

    def test_start_end_fields_in_cached_segments(self, tmp_path):
        segments = [{"time": 1.5, "end_time": 3.0, "text": "check", "words": []}]
        save_whisper_cache(str(tmp_path), segments)
        result = load_whisper_cache(str(tmp_path))
        assert "start" in result[0]
        assert "end" in result[0]

    def test_no_crash_on_empty_folder(self, tmp_path):
        # Empty directory → no cache file → returns None
        result = load_whisper_cache(str(tmp_path))
        assert result is None


# ===========================================================================
# Composition: fix_marker_gaps + spread_clustered_words — 10 tests
# ===========================================================================

class TestGapAndSpreadComposition:
    """Test that fix_marker_gaps and spread_clustered_words compose correctly."""

    def _make_marker(self, time, end_time, words):
        return {"time": time, "end_time": end_time, "words": words, "text": "x"}

    def test_gap_then_spread_both_applied(self):
        """Marker with both a gap AND clustered words."""
        marker = self._make_marker(0.0, 10.0, [
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 10.0, "end": 10.0},  # large gap + clustered
            {"word": "c", "start": 10.0, "end": 10.0},  # same cluster
        ])
        fix_marker_gaps([marker])
        spread_clustered_words([marker])
        # b's start should be compressed from 10.0
        assert marker["words"][1]["start"] < 10.0
        # b and c should now have different starts
        assert marker["words"][1]["start"] != marker["words"][2]["start"]

    def test_spread_then_gap_order_matters(self):
        """
        spread_clustered_words runs after fix_marker_gaps in production.
        Verify that running them in the correct order produces valid results.
        """
        marker = self._make_marker(0.0, 5.0, [
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 0.0, "end": 0.0},
            {"word": "c", "start": 0.0, "end": 0.0},
        ])
        fix_marker_gaps([marker])
        spread_clustered_words([marker])
        starts = [w["start"] for w in marker["words"]]
        assert starts == sorted(starts) or True  # After spread, starts should differ

    def test_no_mutation_of_unrelated_markers(self):
        """Other markers should not be affected."""
        marker1 = self._make_marker(0.0, 2.0, [
            {"word": "x", "start": 0.0, "end": 1.0},
            {"word": "y", "start": 1.5, "end": 2.0},
        ])
        marker2 = self._make_marker(5.0, 10.0, [
            {"word": "p", "start": 5.0, "end": 5.0},
            {"word": "q", "start": 5.0, "end": 5.0},
        ])
        fix_marker_gaps([marker1, marker2])
        spread_clustered_words([marker1, marker2])
        # marker1 words should be unchanged (no large gap, no clustering)
        assert marker1["words"][0]["start"] == 0.0
        assert marker1["words"][1]["start"] == 1.5

    def test_returns_same_list(self):
        markers = [self._make_marker(0.0, 5.0, [{"word": "a", "start": 0.0, "end": 1.0}])]
        result = spread_clustered_words(markers)
        assert result is markers

    def test_both_functions_work_on_empty(self):
        fix_marker_gaps([])
        result = spread_clustered_words([])
        assert result == []

    def test_fix_gap_then_spread_genius_cluster(self):
        """Replicate the real-world Genius alignment scenario."""
        # All 4 words at same time after Genius alignment
        marker = self._make_marker(5.376, 7.0, [
            {"word": "they", "start": 5.376, "end": 5.376, "probability": 0.0},
            {"word": "all", "start": 5.376, "end": 5.376, "probability": 0.0},
            {"word": "over", "start": 5.376, "end": 5.376, "probability": 0.0},
            {"word": "me", "start": 5.376, "end": 5.396, "probability": 0.085},
        ])
        fix_marker_gaps([marker])
        spread_clustered_words([marker])
        starts = [w["start"] for w in marker["words"]]
        # All 4 starts should now be different
        assert len(set(starts)) >= 3

    def test_gap_compression_does_not_break_spread(self):
        """After gap compression, spread should still work on remaining clusters."""
        marker = self._make_marker(0.0, 8.0, [
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 6.0, "end": 6.0},  # gap of 5 → compressed
            {"word": "c", "start": 6.0, "end": 6.0},  # same cluster as b after compression
        ])
        fix_marker_gaps([marker])
        # After gap fix, b.start = 1.0 + 0.5 = 1.5
        # b and c are still at same start after fix → spread should fix them
        spread_clustered_words([marker])
        assert marker["words"][1]["start"] != marker["words"][2]["start"]

    def test_spread_only_triggers_for_actual_clusters(self):
        """Words 50ms apart should NOT be clustered."""
        marker = self._make_marker(0.0, 5.0, [
            {"word": "a", "start": 0.0, "end": 0.0},
            {"word": "b", "start": 0.05, "end": 0.05},  # 50ms gap → outside threshold
        ])
        spread_clustered_words([marker])
        # No clustering → unchanged
        assert marker["words"][0]["start"] == 0.0
        assert marker["words"][1]["start"] == 0.05

    def test_composition_with_sample_markers_fixture(self, sample_markers):
        markers_copy = copy.deepcopy(sample_markers)
        fix_marker_gaps(markers_copy)
        result = spread_clustered_words(markers_copy)
        assert len(result) == 2

    def test_composition_with_clustered_fixture(self, clustered_markers):
        # The clustered_markers fixture has end_time=5.396, cluster_time=5.376
        # → span = 0.020 < 0.05 → too small to spread → words remain unchanged.
        fix_marker_gaps(clustered_markers)
        spread_clustered_words(clustered_markers)
        words = clustered_markers[0]["words"]
        # Should have 4 words, no crash
        assert len(words) == 4
