"""
Tests for scripts/config.py

Covers the missed lines:
  - 15-16: dotenv import error silently ignored (ImportError on `from dotenv import load_dotenv`)
  - 59: set_max_line_length classmethod
  - 64-72: validate() branches:
      - warns when GENIUS_API_TOKEN is empty
      - warns (and resets) when WHISPER_MODEL is invalid
      - returns empty list when config is valid
      - multiple warnings accumulate
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _fresh_config_class():
    """Re-import Config with a clean module state."""
    import importlib
    if "scripts.config" in sys.modules:
        del sys.modules["scripts.config"]
    from scripts import config as cfg_module
    importlib.reload(cfg_module)
    return cfg_module.Config


# ===========================================================================
# dotenv import failure (lines 15-16)
# ===========================================================================

class TestDotenvImportFailure:
    def test_import_error_on_dotenv_is_silently_ignored(self):
        """If dotenv is not installed, Config should still import cleanly."""
        original = sys.modules.get("dotenv")
        # Simulate dotenv not being installed by temporarily removing it
        sys.modules["dotenv"] = None  # type: ignore[assignment]
        try:
            if "scripts.config" in sys.modules:
                del sys.modules["scripts.config"]
            # This should not raise even without dotenv
            import importlib
            import scripts.config as cfg_mod
            importlib.reload(cfg_mod)
            assert hasattr(cfg_mod.Config, "GENIUS_API_TOKEN")
        finally:
            if original is None:
                sys.modules.pop("dotenv", None)
            else:
                sys.modules["dotenv"] = original


# ===========================================================================
# set_max_line_length (line 59)
# ===========================================================================

class TestSetMaxLineLength:
    def test_sets_class_attribute(self):
        from scripts.config import Config
        original = Config.MAX_LINE_LENGTH
        try:
            Config.set_max_line_length(40)
            assert Config.MAX_LINE_LENGTH == 40
        finally:
            Config.MAX_LINE_LENGTH = original

    def test_sets_small_value(self):
        from scripts.config import Config
        original = Config.MAX_LINE_LENGTH
        try:
            Config.set_max_line_length(10)
            assert Config.MAX_LINE_LENGTH == 10
        finally:
            Config.MAX_LINE_LENGTH = original


# ===========================================================================
# validate() (lines 64-72)
# ===========================================================================

class TestConfigValidate:
    def setup_method(self):
        """Store original class attributes before each test."""
        from scripts.config import Config
        self._orig_token = Config.GENIUS_API_TOKEN
        self._orig_model = Config.WHISPER_MODEL

    def teardown_method(self):
        """Restore class attributes after each test."""
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = self._orig_token
        Config.WHISPER_MODEL = self._orig_model

    def test_warns_when_genius_token_empty(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = ""
        Config.WHISPER_MODEL = "small"
        warnings = Config.validate()
        assert any("GENIUS_API_TOKEN" in w for w in warnings)

    def test_no_warning_when_genius_token_set(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "test_token_123"
        Config.WHISPER_MODEL = "small"
        warnings = Config.validate()
        assert not any("GENIUS_API_TOKEN" in w for w in warnings)

    def test_warns_on_invalid_whisper_model(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "token"
        Config.WHISPER_MODEL = "not_a_real_model"
        warnings = Config.validate()
        assert any("WHISPER_MODEL" in w or "not_a_real_model" in w for w in warnings)

    def test_invalid_model_reset_to_small(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "token"
        Config.WHISPER_MODEL = "invalid_model"
        Config.validate()
        assert Config.WHISPER_MODEL == "small"

    def test_returns_empty_when_valid(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "some_token"
        Config.WHISPER_MODEL = "small"
        warnings = Config.validate()
        assert warnings == []

    def test_multiple_warnings_accumulated(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = ""
        Config.WHISPER_MODEL = "bad_model"
        warnings = Config.validate()
        assert len(warnings) >= 2

    def test_all_valid_models_accepted(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "token"
        valid_models = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
        for model in valid_models:
            Config.WHISPER_MODEL = model
            warnings = Config.validate()
            assert not any("WHISPER_MODEL" in w for w in warnings), (
                f"Model '{model}' should be valid but got warning"
            )

    def test_returns_list_type(self):
        from scripts.config import Config
        Config.GENIUS_API_TOKEN = "token"
        Config.WHISPER_MODEL = "small"
        result = Config.validate()
        assert isinstance(result, list)
