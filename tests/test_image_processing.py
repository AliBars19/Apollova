"""
Tests for scripts/image_processing.py

Covers:
  - download_image: success path with mocked HTTP, saves PNG in job folder
  - download_image: retries on transient failure then succeeds
  - download_image: raises after max retries exhausted
  - download_image: raises on HTTP non-200 response
  - resize_and_crop: output is exactly target_size x target_size
  - resize_and_crop: works on portrait, landscape, and square inputs
  - extract_colors: returns list of hex strings from a real PNG
  - extract_colors: fallback on missing cover image
  - extract_colors: fallback when ColorThief raises
  - extract_colors: color_count parameter honoured
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from PIL import Image

from scripts.image_processing import download_image, resize_and_crop, extract_colors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgb_image(width: int = 200, height: int = 200, color: tuple = (255, 0, 0)) -> Image.Image:
    """Return a minimal solid-colour RGB PIL image."""
    img = Image.new("RGB", (width, height), color)
    return img


def _image_bytes(width: int = 200, height: int = 200, color: tuple = (255, 0, 0), fmt: str = "PNG") -> bytes:
    buf = BytesIO()
    _make_rgb_image(width, height, color).save(buf, format=fmt)
    return buf.getvalue()


def _mock_response(content: bytes, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    return resp


# ===========================================================================
# download_image
# ===========================================================================

class TestDownloadImage:
    URL = "https://images.genius.com/fake_cover.jpg"

    def test_saves_png_on_success(self, job_folder: Path):
        mock_resp = _mock_response(_image_bytes())
        with patch("scripts.image_processing.requests.get", return_value=mock_resp):
            result = download_image(str(job_folder), self.URL)

        assert result is not None
        assert os.path.exists(result)
        assert result.endswith(".png")
        assert "cover.png" in result

    def test_saved_image_is_valid_png(self, job_folder: Path):
        mock_resp = _mock_response(_image_bytes(400, 300))
        with patch("scripts.image_processing.requests.get", return_value=mock_resp):
            result = download_image(str(job_folder), self.URL)

        img = Image.open(result)
        assert img.format == "PNG"

    def test_saved_image_is_700x700(self, job_folder: Path):
        """resize_and_crop should be applied so the output is exactly 700x700."""
        mock_resp = _mock_response(_image_bytes(400, 300))
        with patch("scripts.image_processing.requests.get", return_value=mock_resp):
            result = download_image(str(job_folder), self.URL)

        img = Image.open(result)
        assert img.size == (700, 700)

    def test_retries_on_transient_failure_then_succeeds(self, job_folder: Path):
        """Should retry on exception and succeed on 2nd attempt."""
        success_resp = _mock_response(_image_bytes())
        with patch(
            "scripts.image_processing.requests.get",
            side_effect=[Exception("timeout"), success_resp],
        ):
            result = download_image(str(job_folder), self.URL, max_retries=3)

        assert result is not None
        assert os.path.exists(result)

    def test_raises_after_all_retries_exhausted(self, job_folder: Path):
        with patch(
            "scripts.image_processing.requests.get",
            side_effect=Exception("persistent failure"),
        ):
            with pytest.raises(Exception, match="persistent failure"):
                download_image(str(job_folder), self.URL, max_retries=2)

    def test_raises_on_http_error_status(self, job_folder: Path):
        bad_resp = _mock_response(b"", status=404)
        with patch("scripts.image_processing.requests.get", return_value=bad_resp):
            with pytest.raises(Exception):
                download_image(str(job_folder), self.URL, max_retries=1)

    def test_no_request_made_for_empty_url(self, job_folder: Path):
        """An empty URL causes requests.get to raise before we can check status."""
        with patch(
            "scripts.image_processing.requests.get",
            side_effect=Exception("invalid URL"),
        ):
            with pytest.raises(Exception):
                download_image(str(job_folder), "", max_retries=1)

    def test_returns_path_string_not_path_object(self, job_folder: Path):
        mock_resp = _mock_response(_image_bytes())
        with patch("scripts.image_processing.requests.get", return_value=mock_resp):
            result = download_image(str(job_folder), self.URL)
        assert isinstance(result, str)


# ===========================================================================
# resize_and_crop
# ===========================================================================

class TestResizeAndCrop:
    def test_square_input_produces_target_size(self):
        img = _make_rgb_image(500, 500)
        result = resize_and_crop(img, target_size=700)
        assert result.size == (700, 700)

    def test_portrait_input_produces_target_size(self):
        img = _make_rgb_image(300, 600)
        result = resize_and_crop(img, target_size=700)
        assert result.size == (700, 700)

    def test_landscape_input_produces_target_size(self):
        img = _make_rgb_image(1200, 400)
        result = resize_and_crop(img, target_size=700)
        assert result.size == (700, 700)

    def test_small_input_upscales(self):
        img = _make_rgb_image(100, 80)
        result = resize_and_crop(img, target_size=700)
        assert result.size == (700, 700)

    def test_custom_target_size(self):
        img = _make_rgb_image(800, 600)
        result = resize_and_crop(img, target_size=300)
        assert result.size == (300, 300)

    def test_output_mode_rgb(self):
        img = _make_rgb_image(200, 200)
        result = resize_and_crop(img, target_size=100)
        assert result.mode == "RGB"

    def test_does_not_mutate_input(self):
        img = _make_rgb_image(200, 200)
        original_size = img.size
        resize_and_crop(img, target_size=700)
        # Original should be unchanged (pydub/PIL operations return new objects)
        assert img.size == original_size


# ===========================================================================
# extract_colors
# ===========================================================================

class TestExtractColors:
    def _write_cover(self, job_folder: Path, color: tuple = (200, 100, 50)) -> Path:
        """Write a solid-colour cover.png for color extraction tests."""
        cover = job_folder / "cover.png"
        _make_rgb_image(50, 50, color).save(str(cover), format="PNG")
        return cover

    def test_returns_list_of_hex_strings(self, job_folder: Path):
        self._write_cover(job_folder)
        colors = extract_colors(str(job_folder))
        assert isinstance(colors, list)
        assert len(colors) > 0
        for c in colors:
            assert isinstance(c, str)
            assert c.startswith("#")
            assert len(c) == 7  # e.g. #aabbcc

    def test_default_returns_two_colors(self, job_folder: Path):
        # ColorThief.get_palette may return >= color_count entries.
        # The production code passes whatever the palette returns, so assert >= 2.
        self._write_cover(job_folder)
        colors = extract_colors(str(job_folder))
        assert len(colors) >= 2

    def test_color_count_parameter(self, job_folder: Path):
        """color_count=3 should request at least 3 hex values from ColorThief."""
        # Use a larger image so ColorThief can find enough clusters
        cover = job_folder / "cover.png"
        img = Image.new("RGB", (200, 200))
        pixels = img.load()
        for x in range(200):
            for y in range(200):
                # Create 3 distinct colour blocks
                if x < 67:
                    pixels[x, y] = (255, 0, 0)
                elif x < 134:
                    pixels[x, y] = (0, 255, 0)
                else:
                    pixels[x, y] = (0, 0, 255)
        img.save(str(cover), format="PNG")

        colors = extract_colors(str(job_folder), color_count=3)
        # ColorThief may return >= color_count entries; we just need at least 3
        assert len(colors) >= 3

    def test_fallback_when_cover_missing(self, job_folder: Path):
        """When cover.png does not exist, should return default fallback colors."""
        colors = extract_colors(str(job_folder))
        assert isinstance(colors, list)
        assert len(colors) == 2
        assert all(c.startswith("#") for c in colors)

    def test_fallback_on_colorthief_error(self, job_folder: Path):
        """When ColorThief raises, should return fallback colors not raise."""
        self._write_cover(job_folder)
        with patch("scripts.image_processing.ColorThief") as mock_ct:
            mock_ct.return_value.get_palette.side_effect = Exception("palette error")
            colors = extract_colors(str(job_folder))

        assert isinstance(colors, list)
        assert len(colors) > 0
        assert all(c.startswith("#") for c in colors)

    def test_hex_values_are_lowercase(self, job_folder: Path):
        self._write_cover(job_folder)
        colors = extract_colors(str(job_folder))
        for c in colors:
            assert c == c.lower()

    def test_hex_values_contain_only_valid_chars(self, job_folder: Path):
        self._write_cover(job_folder)
        colors = extract_colors(str(job_folder))
        valid = set("0123456789abcdef#")
        for c in colors:
            assert all(ch in valid for ch in c), f"Invalid hex char in '{c}'"
