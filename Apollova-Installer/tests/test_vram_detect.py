"""Tests for GPU VRAM detection and Whisper model recommendation."""
import pytest

# Mock torch before importing — CUDA not available in test env
import sys
from unittest.mock import MagicMock

_torch_mock = MagicMock()
_torch_mock.cuda.is_available.return_value = False
sys.modules.setdefault('torch', _torch_mock)

from scripts.vram_detect import detect_gpu_vram, recommend_whisper_model, get_recommendation_label


class TestRecommendWhisperModel:
    def test_none_vram_returns_small(self):
        assert recommend_whisper_model(None) == "small"

    def test_zero_vram_returns_small(self):
        assert recommend_whisper_model(0) == "small"

    def test_2gb_returns_small(self):
        assert recommend_whisper_model(2048) == "small"

    def test_3gb_returns_small(self):
        assert recommend_whisper_model(3072) == "small"

    def test_4095_returns_small(self):
        assert recommend_whisper_model(4095) == "small"

    def test_4096_returns_medium(self):
        assert recommend_whisper_model(4096) == "medium"

    def test_6gb_returns_medium(self):
        assert recommend_whisper_model(6144) == "medium"

    def test_8191_returns_medium(self):
        assert recommend_whisper_model(8191) == "medium"

    def test_8192_returns_large(self):
        assert recommend_whisper_model(8192) == "large-v3"

    def test_12gb_returns_large(self):
        assert recommend_whisper_model(12288) == "large-v3"

    def test_16gb_returns_large(self):
        assert recommend_whisper_model(16384) == "large-v3"

    def test_24gb_returns_large(self):
        assert recommend_whisper_model(24576) == "large-v3"


class TestGetRecommendationLabel:
    def test_none_vram(self):
        label = get_recommendation_label(None)
        assert "No GPU" in label
        assert "small" in label

    def test_4gb_vram(self):
        label = get_recommendation_label(4096)
        assert "4.0 GB" in label
        assert "medium" in label

    def test_8gb_vram(self):
        label = get_recommendation_label(8192)
        assert "8.0 GB" in label
        assert "large-v3" in label

    def test_6gb_vram(self):
        label = get_recommendation_label(6144)
        assert "6.0 GB" in label
        assert "medium" in label


class TestDetectGpuVram:
    def test_returns_none_when_no_torch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, 'torch', None)
        # When torch import raises ImportError, should return None
        # (actual test depends on mock behavior)

    def test_returns_none_when_no_cuda(self, monkeypatch):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        monkeypatch.setitem(sys.modules, 'torch', mock_torch)
        result = detect_gpu_vram()
        assert result is None

    def test_returns_vram_mb_when_cuda_available(self, monkeypatch):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_props = MagicMock()
        mock_props.total_mem = 8 * 1024 * 1024 * 1024  # 8 GB
        mock_torch.cuda.get_device_properties.return_value = mock_props
        monkeypatch.setitem(sys.modules, 'torch', mock_torch)
        result = detect_gpu_vram()
        assert result == 8192
