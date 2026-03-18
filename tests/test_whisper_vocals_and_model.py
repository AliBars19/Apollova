"""
Tests for whisper_common vocal separation and model lifecycle.

Covers:
  - separate_vocals: cached vocals reuse, Demucs subprocess, failure fallbacks
  - load_whisper_model: caching, force_cpu env manipulation, config change reload
  - unload_model: clears globals, calls clear_vram, noop when nothing loaded
  - clear_vram: gc.collect, torch.cuda paths, no-torch/no-cuda branches
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from scripts import whisper_common
from scripts.whisper_common import (
    separate_vocals,
    load_whisper_model,
    unload_model,
    clear_vram,
)


# ---------------------------------------------------------------------------
# separate_vocals
# ---------------------------------------------------------------------------

class TestSeparateVocals:

    def test_cached_vocals_reuse(self, job_folder):
        """If vocals.wav already exists, return it without running Demucs."""
        vocals = job_folder / "vocals.wav"
        vocals.write_bytes(b"fake")
        result = separate_vocals(str(job_folder / "audio.wav"), str(job_folder))
        assert result == str(vocals)

    @patch("subprocess.run")
    def test_demucs_success(self, mock_run, job_folder, silent_wav):
        """Successful Demucs run copies vocals.wav to job folder."""
        audio_path = str(silent_wav)

        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            stem = os.path.splitext(os.path.basename(audio_path))[0]
            out_dir = os.path.join(tmpdir, "htdemucs", stem)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "vocals.wav"), "wb") as f:
                f.write(b"vocals_data")
            r = MagicMock()
            r.returncode = 0
            return r

        mock_run.side_effect = fake_run
        result = separate_vocals(audio_path, str(job_folder))
        assert result == str(job_folder / "vocals.wav")
        assert (job_folder / "vocals.wav").exists()

    @patch("subprocess.run")
    def test_demucs_nonzero_returncode_fallback(self, mock_run, job_folder, silent_wav):
        r = MagicMock()
        r.returncode = 1
        r.stderr = "some error"
        mock_run.return_value = r
        result = separate_vocals(str(silent_wav), str(job_folder))
        assert result == str(silent_wav)

    @patch("subprocess.run")
    def test_demucs_output_missing_fallback(self, mock_run, job_folder, silent_wav):
        r = MagicMock()
        r.returncode = 0
        mock_run.return_value = r
        result = separate_vocals(str(silent_wav), str(job_folder))
        assert result == str(silent_wav)

    @patch("subprocess.run", side_effect=Exception("boom"))
    def test_generic_exception_fallback(self, mock_run, job_folder, silent_wav):
        result = separate_vocals(str(silent_wav), str(job_folder))
        assert result == str(silent_wav)

    @patch("subprocess.run")
    def test_timeout_fallback(self, mock_run, job_folder, silent_wav):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="demucs", timeout=300)
        result = separate_vocals(str(silent_wav), str(job_folder))
        assert result == str(silent_wav)


# ---------------------------------------------------------------------------
# load_whisper_model
# ---------------------------------------------------------------------------

class TestLoadWhisperModel:

    def setup_method(self):
        """Reset cached model state before each test."""
        whisper_common._cached_model = None
        whisper_common._cached_on_cpu = None

    def teardown_method(self):
        whisper_common._cached_model = None
        whisper_common._cached_on_cpu = None

    @patch("scripts.whisper_common.load_model")
    def test_loads_and_caches_model(self, mock_load_model):
        fake_model = MagicMock()
        mock_load_model.return_value = fake_model
        result = load_whisper_model()
        assert result is fake_model
        assert whisper_common._cached_model is fake_model
        assert whisper_common._cached_on_cpu is False

    @patch("scripts.whisper_common.load_model")
    def test_returns_cached_model_on_second_call(self, mock_load_model):
        fake_model = MagicMock()
        mock_load_model.return_value = fake_model
        m1 = load_whisper_model()
        m2 = load_whisper_model()
        assert m1 is m2
        assert mock_load_model.call_count == 1  # Only loaded once

    @patch("scripts.whisper_common.load_model")
    def test_force_cpu_sets_cuda_env(self, mock_load_model):
        fake_model = MagicMock()
        mock_load_model.return_value = fake_model

        original_env = os.environ.get("CUDA_VISIBLE_DEVICES")
        load_whisper_model(force_cpu=True)

        # After the call, the env var should be restored
        current = os.environ.get("CUDA_VISIBLE_DEVICES")
        assert current == original_env
        assert whisper_common._cached_on_cpu is True

    @patch("scripts.whisper_common.load_model")
    def test_config_change_triggers_reload(self, mock_load_model):
        """Switching from GPU to CPU should unload and reload."""
        gpu_model = MagicMock()
        cpu_model = MagicMock()
        mock_load_model.side_effect = [gpu_model, cpu_model]

        m1 = load_whisper_model(force_cpu=False)
        assert m1 is gpu_model

        m2 = load_whisper_model(force_cpu=True)
        assert m2 is cpu_model
        assert mock_load_model.call_count == 2

    @patch("scripts.whisper_common.load_model")
    def test_force_cpu_restores_env_on_error(self, mock_load_model):
        mock_load_model.side_effect = Exception("model load failed")
        original_env = os.environ.get("CUDA_VISIBLE_DEVICES")
        with pytest.raises(Exception, match="model load failed"):
            load_whisper_model(force_cpu=True)
        # Env should be restored even on error
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == original_env


# ---------------------------------------------------------------------------
# unload_model
# ---------------------------------------------------------------------------

class TestUnloadModel:

    def setup_method(self):
        whisper_common._cached_model = None
        whisper_common._cached_on_cpu = None

    def teardown_method(self):
        whisper_common._cached_model = None
        whisper_common._cached_on_cpu = None

    @patch("scripts.whisper_common.clear_vram")
    def test_clears_globals_and_calls_clear_vram(self, mock_clear):
        whisper_common._cached_model = MagicMock()
        whisper_common._cached_on_cpu = True
        unload_model()
        assert whisper_common._cached_model is None
        assert whisper_common._cached_on_cpu is None
        mock_clear.assert_called_once()

    @patch("scripts.whisper_common.clear_vram")
    def test_noop_when_nothing_loaded(self, mock_clear):
        whisper_common._cached_model = None
        unload_model()
        mock_clear.assert_not_called()


# ---------------------------------------------------------------------------
# clear_vram
# ---------------------------------------------------------------------------

class TestClearVram:

    @patch("scripts.whisper_common.gc.collect")
    def test_always_calls_gc_collect(self, mock_gc):
        with patch.object(whisper_common, "HAS_TORCH", False):
            clear_vram()
        mock_gc.assert_called_once()

    @patch("scripts.whisper_common.gc.collect")
    def test_torch_cuda_path(self, mock_gc):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.object(whisper_common, "HAS_TORCH", True):
            with patch.object(whisper_common, "torch", mock_torch):
                clear_vram()
        mock_torch.cuda.empty_cache.assert_called_once()
        mock_torch.cuda.synchronize.assert_called_once()

    @patch("scripts.whisper_common.gc.collect")
    def test_no_torch_branch(self, mock_gc):
        with patch.object(whisper_common, "HAS_TORCH", False):
            clear_vram()
        # Should not crash, only gc.collect called
        mock_gc.assert_called_once()

    @patch("scripts.whisper_common.gc.collect")
    def test_cuda_not_available(self, mock_gc):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.object(whisper_common, "HAS_TORCH", True):
            with patch.object(whisper_common, "torch", mock_torch):
                clear_vram()
        mock_torch.cuda.empty_cache.assert_not_called()
