"""
Tests for upload/config.py (render watcher Config dataclass)

Covers:
  - Config defaults: api_base_url, videos_per_day_per_account, etc.
  - Config.validate: passes with gate_password set
  - Config.validate: fails without gate_password
  - Config.validate: fails on invalid API URL
  - Config.validate: fails when videos_per_day_per_account < 1
  - Config.validate: fails when schedule_interval_minutes < 5
  - Config.validate: fails when folder_account_map is empty
  - Config.from_env: reads values from environment variables
  - Config.from_env: FOLDER_ACCOUNT_MAP JSON override
  - Config.from_env: invalid FOLDER_ACCOUNT_MAP JSON is silently ignored
  - Config.from_env: loads .env file via env_path argument
  - Config.get_watch_paths: returns {folder_name: (path, account)} dict
  - Config.get_template_from_path: infers template name from file path
  - Config.get_template_from_path: returns 'unknown' for unrecognised path
  - _load_dotenv: parses KEY=VALUE, ignores comments and blank lines
  - _load_dotenv: does not raise on missing file
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "upload"))

from config import Config, _load_dotenv


# ===========================================================================
# Config defaults
# ===========================================================================

class TestConfigDefaults:
    def test_default_api_base_url(self):
        cfg = Config()
        assert cfg.api_base_url.startswith("https://")

    def test_default_videos_per_day(self):
        cfg = Config()
        assert cfg.videos_per_day_per_account == 12

    def test_default_schedule_interval_minutes(self):
        cfg = Config()
        assert cfg.schedule_interval_minutes == 60

    def test_default_folder_account_map_has_three_entries(self):
        cfg = Config()
        assert len(cfg.folder_account_map) == 3

    def test_default_folder_account_map_keys(self):
        cfg = Config()
        keys = set(cfg.folder_account_map.keys())
        assert "Apollova-Aurora" in keys
        assert "Apollova-Mono" in keys
        assert "Apollova-Onyx" in keys

    def test_default_folder_account_map_values(self):
        cfg = Config()
        values = set(cfg.folder_account_map.values())
        assert "aurora" in values
        assert "mono" in values
        assert "onyx" in values

    def test_default_max_upload_retries(self):
        cfg = Config()
        assert cfg.max_upload_retries >= 1

    def test_default_video_extensions(self):
        cfg = Config()
        assert ".mp4" in cfg.video_extensions

    def test_default_renders_subfolder(self):
        cfg = Config()
        assert cfg.renders_subfolder != ""


# ===========================================================================
# Config.validate
# ===========================================================================

class TestConfigValidate:
    def test_passes_with_gate_password(self):
        cfg = Config(gate_password="secret123")
        errors = cfg.validate()
        assert errors == []

    def test_fails_without_gate_password(self):
        cfg = Config(gate_password="")
        errors = cfg.validate()
        assert any("GATE_PASSWORD" in e for e in errors)

    def test_fails_with_invalid_api_url(self):
        cfg = Config(gate_password="x", api_base_url="not-a-url")
        errors = cfg.validate()
        assert any("API URL" in e or "Invalid" in e for e in errors)

    def test_fails_when_videos_per_day_zero(self):
        cfg = Config(gate_password="x", videos_per_day_per_account=0)
        errors = cfg.validate()
        assert any("VIDEOS_PER_DAY" in e or "at least 1" in e for e in errors)

    def test_fails_when_schedule_interval_too_small(self):
        cfg = Config(gate_password="x", schedule_interval_minutes=1)
        errors = cfg.validate()
        assert any("interval" in e.lower() or "5 minute" in e for e in errors)

    def test_fails_when_no_folder_mappings(self):
        cfg = Config(gate_password="x", folder_account_map={})
        errors = cfg.validate()
        assert any("folder" in e.lower() or "mapping" in e.lower() for e in errors)

    def test_multiple_errors_accumulated(self):
        cfg = Config(gate_password="", api_base_url="bad-url", videos_per_day_per_account=0)
        errors = cfg.validate()
        assert len(errors) >= 2

    def test_returns_list_type(self):
        cfg = Config(gate_password="ok")
        assert isinstance(cfg.validate(), list)


# ===========================================================================
# Config.from_env — environment variable loading
# ===========================================================================

class TestConfigFromEnv:
    def test_reads_gate_password_from_env(self, monkeypatch):
        monkeypatch.setenv("GATE_PASSWORD", "env_secret")
        cfg = Config.from_env()
        assert cfg.gate_password == "env_secret"

    def test_reads_api_url_from_env(self, monkeypatch):
        monkeypatch.setenv("APOLLOVA_API_URL", "https://test.example.com")
        cfg = Config.from_env()
        assert cfg.api_base_url == "https://test.example.com"

    def test_reads_videos_per_day_from_env(self, monkeypatch):
        monkeypatch.setenv("VIDEOS_PER_DAY", "5")
        cfg = Config.from_env()
        assert cfg.videos_per_day_per_account == 5

    def test_reads_schedule_interval_from_env(self, monkeypatch):
        monkeypatch.setenv("SCHEDULE_INTERVAL", "30")
        cfg = Config.from_env()
        assert cfg.schedule_interval_minutes == 30

    def test_reads_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        cfg = Config.from_env()
        assert cfg.log_level == "DEBUG"

    def test_reads_notifications_false_from_env(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATIONS", "false")
        cfg = Config.from_env()
        assert cfg.notifications_enabled is False

    def test_reads_notifications_true_from_env(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATIONS", "true")
        cfg = Config.from_env()
        assert cfg.notifications_enabled is True

    def test_folder_account_map_json_override(self, monkeypatch):
        mapping = {"Apollova-Test": "test_account"}
        monkeypatch.setenv("FOLDER_ACCOUNT_MAP", json.dumps(mapping))
        cfg = Config.from_env()
        assert cfg.folder_account_map == mapping

    def test_invalid_folder_account_map_json_silently_ignored(self, monkeypatch):
        monkeypatch.setenv("FOLDER_ACCOUNT_MAP", "not-valid-json{{")
        # Should not raise — falls back to defaults
        cfg = Config.from_env()
        assert isinstance(cfg.folder_account_map, dict)
        assert len(cfg.folder_account_map) > 0

    def test_from_env_with_dotenv_file(self, tmp_path: Path, monkeypatch):
        """Config.from_env loads values from a .env file when env_path is provided."""
        env_file = tmp_path / "test.env"
        env_file.write_text("GATE_PASSWORD=from_dotenv_file\n")
        # Remove the env var if set, so the file wins
        monkeypatch.delenv("GATE_PASSWORD", raising=False)
        cfg = Config.from_env(env_path=str(env_file))
        assert cfg.gate_password == "from_dotenv_file"

    def test_from_env_missing_dotenv_does_not_raise(self, tmp_path: Path):
        """Passing a non-existent env_path should not raise."""
        cfg = Config.from_env(env_path=str(tmp_path / "nonexistent.env"))
        assert isinstance(cfg, Config)


# ===========================================================================
# Config.get_watch_paths
# ===========================================================================

class TestGetWatchPaths:
    def test_returns_dict(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        assert isinstance(paths, dict)

    def test_keys_are_folder_names(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        for key in paths:
            assert key.startswith("Apollova-")

    def test_values_are_path_account_tuples(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        for folder_name, (renders_path, account) in paths.items():
            assert isinstance(renders_path, Path)
            assert isinstance(account, str)
            assert account in ("aurora", "mono", "onyx")

    def test_aurora_folder_maps_to_aurora_account(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        assert paths["Apollova-Aurora"][1] == "aurora"

    def test_mono_folder_maps_to_mono_account(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        assert paths["Apollova-Mono"][1] == "mono"

    def test_renders_subfolder_included_in_path(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        # Normalise separators for cross-platform comparison
        subfolder_parts = upload_config.renders_subfolder.replace("\\", "/").split("/")
        for folder_name, (renders_path, _) in paths.items():
            path_str = str(renders_path).replace("\\", "/")
            for part in subfolder_parts:
                assert part in path_str, f"Expected '{part}' in path '{path_str}'"

    def test_three_watch_paths_by_default(self, upload_config: Config):
        paths = upload_config.get_watch_paths()
        assert len(paths) == 3


# ===========================================================================
# Config.get_template_from_path
# ===========================================================================

class TestGetTemplateFromPath:
    def test_aurora_path_returns_aurora(self):
        cfg = Config()
        t = cfg.get_template_from_path("/some/Apollova-Aurora/jobs/renders/video.mp4")
        assert t == "aurora"

    def test_mono_path_returns_mono(self):
        cfg = Config()
        t = cfg.get_template_from_path("/some/Apollova-Mono/jobs/renders/video.mp4")
        assert t == "mono"

    def test_onyx_path_returns_onyx(self):
        cfg = Config()
        t = cfg.get_template_from_path("/some/Apollova-Onyx/jobs/renders/video.mp4")
        assert t == "onyx"

    def test_unrecognised_path_returns_unknown(self):
        cfg = Config()
        t = cfg.get_template_from_path("/completely/different/path/video.mp4")
        assert t == "unknown"

    def test_case_insensitive_match(self):
        cfg = Config()
        t = cfg.get_template_from_path("/some/apollova-aurora/jobs/renders/video.mp4")
        assert t == "aurora"


# ===========================================================================
# _load_dotenv
# ===========================================================================

class TestLoadDotenv:
    def test_loads_simple_key_value(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_KEY=my_value\n")
        monkeypatch.delenv("MY_KEY", raising=False)
        _load_dotenv(str(env_file))
        assert os.environ.get("MY_KEY") == "my_value"
        # Cleanup
        monkeypatch.delenv("MY_KEY", raising=False)

    def test_ignores_comments(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nACTUAL_KEY=actual_value\n")
        monkeypatch.delenv("ACTUAL_KEY", raising=False)
        _load_dotenv(str(env_file))
        assert os.environ.get("ACTUAL_KEY") == "actual_value"
        monkeypatch.delenv("ACTUAL_KEY", raising=False)

    def test_ignores_blank_lines(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nBLANK_TEST=ok\n\n")
        monkeypatch.delenv("BLANK_TEST", raising=False)
        _load_dotenv(str(env_file))
        assert os.environ.get("BLANK_TEST") == "ok"
        monkeypatch.delenv("BLANK_TEST", raising=False)

    def test_strips_quotes_from_values(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="my quoted value"\n')
        monkeypatch.delenv("QUOTED_KEY", raising=False)
        _load_dotenv(str(env_file))
        assert os.environ.get("QUOTED_KEY") == "my quoted value"
        monkeypatch.delenv("QUOTED_KEY", raising=False)

    def test_does_not_overwrite_existing_env_var(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_KEY=from_file\n")
        monkeypatch.setenv("EXISTING_KEY", "already_set")
        _load_dotenv(str(env_file))
        assert os.environ.get("EXISTING_KEY") == "already_set"

    def test_does_not_raise_on_missing_file(self):
        """Should silently do nothing if the file does not exist."""
        _load_dotenv("/this/path/does/not/exist/.env")  # must not raise

    def test_value_with_equals_sign(self, tmp_path: Path, monkeypatch):
        """Values that contain '=' should be treated as part of the value."""
        env_file = tmp_path / ".env"
        env_file.write_text("CONN_STR=host=localhost;port=5432\n")
        monkeypatch.delenv("CONN_STR", raising=False)
        _load_dotenv(str(env_file))
        assert os.environ.get("CONN_STR") == "host=localhost;port=5432"
        monkeypatch.delenv("CONN_STR", raising=False)
