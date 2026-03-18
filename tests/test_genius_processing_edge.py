"""
Tests for scripts/genius_processing.py — edge cases beyond existing coverage.

Covers:
  - _extract_from_preloaded_state: single-quote/double-quote JSON.parse, raw object, invalid JSON, short lyrics
  - _extract_text_recursive: string/br/p/nested/list/empty/non-standard nodes
  - fetch_genius_image_rotated: different URL picked, fallback when all match, no token, no hits, download fails
  - _request_with_retry: retries on 500, no retry on 404, retries on ConnectionError, exhaustion
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.genius_processing import (
    _extract_from_preloaded_state,
    _extract_text_recursive,
    fetch_genius_image_rotated,
    _request_with_retry,
)


# ---------------------------------------------------------------------------
# _extract_from_preloaded_state
# ---------------------------------------------------------------------------

class TestExtractFromPreloadedState:

    def test_single_quote_json_parse(self):
        """Pattern: JSON.parse('...')"""
        state = {
            "songPage": {
                "lyricsData": {
                    "body": {
                        "children": [
                            {"tag": "p", "children": ["Hello world line one"]},
                        ]
                    }
                }
            }
        }
        json_str = json.dumps(state).replace("'", "\\'")
        html = f"window.__PRELOADED_STATE__ = JSON.parse('{json_str}');"
        result = _extract_from_preloaded_state(html)
        assert result is not None
        assert "Hello world" in result

    def test_raw_object_pattern(self):
        """Pattern: window.__PRELOADED_STATE__ = {...};"""
        state = {
            "songPage": {
                "lyricsData": {
                    "body": {
                        "children": [
                            {"tag": "p", "children": ["These are lyrics text"]},
                        ]
                    }
                }
            }
        }
        html = f"window.__PRELOADED_STATE__ = {json.dumps(state)};"
        result = _extract_from_preloaded_state(html)
        assert result is not None
        assert "lyrics text" in result

    def test_invalid_json_returns_none(self):
        html = "window.__PRELOADED_STATE__ = JSON.parse('{invalid json}');"
        result = _extract_from_preloaded_state(html)
        assert result is None

    def test_short_lyrics_skipped(self):
        """Lyrics shorter than 10 chars should be skipped."""
        state = {
            "songPage": {
                "lyricsData": {
                    "body": {
                        "children": ["Hi"]
                    }
                }
            }
        }
        html = f"window.__PRELOADED_STATE__ = {json.dumps(state)};"
        result = _extract_from_preloaded_state(html)
        assert result is None

    def test_no_pattern_match_returns_none(self):
        html = "<html><body>No preloaded state here</body></html>"
        result = _extract_from_preloaded_state(html)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_text_recursive
# ---------------------------------------------------------------------------

class TestExtractTextRecursive:

    def test_plain_string(self):
        assert _extract_text_recursive("hello") == "hello"

    def test_br_tag(self):
        result = _extract_text_recursive({"tag": "br", "children": []})
        assert result == "\n"

    def test_p_tag(self):
        result = _extract_text_recursive({
            "tag": "p", "children": ["line one", "line two"]
        })
        assert "line one" in result
        assert "line two" in result

    def test_nested_nodes(self):
        result = _extract_text_recursive({
            "tag": "div", "children": [
                {"tag": "span", "children": ["inner text"]},
            ]
        })
        assert "inner text" in result

    def test_list_input(self):
        result = _extract_text_recursive(["line one", "line two"])
        assert "line one" in result
        assert "line two" in result

    def test_empty_dict(self):
        result = _extract_text_recursive({})
        assert result == ""

    def test_non_standard_tag(self):
        result = _extract_text_recursive({
            "tag": "custom", "children": ["text here"]
        })
        assert "text here" in result

    def test_none_returns_empty(self):
        result = _extract_text_recursive(None)
        assert result == ""

    def test_number_returns_empty(self):
        result = _extract_text_recursive(42)
        assert result == ""


# ---------------------------------------------------------------------------
# fetch_genius_image_rotated
# ---------------------------------------------------------------------------

class TestFetchGeniusImageRotated:

    @patch("scripts.genius_processing.Config")
    def test_no_token_returns_none(self, mock_config):
        mock_config.GENIUS_API_TOKEN = ""
        result = fetch_genius_image_rotated("Artist - Song", "/tmp")
        assert result == (None, None)

    @patch("scripts.genius_processing.Config")
    def test_no_title_returns_none(self, mock_config):
        mock_config.GENIUS_API_TOKEN = "token"
        result = fetch_genius_image_rotated(None, "/tmp")
        assert result == (None, None)

    @patch("scripts.genius_processing._request_with_retry")
    @patch("scripts.genius_processing.Config")
    def test_no_hits_returns_none(self, mock_config, mock_req):
        mock_config.GENIUS_API_TOKEN = "token"
        mock_config.GENIUS_BASE_URL = "https://api.genius.com"
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": {"hits": []}}
        resp.raise_for_status = MagicMock()
        mock_req.return_value = resp
        result = fetch_genius_image_rotated("Artist - Song", "/tmp")
        assert result == (None, None)

    @patch("scripts.image_processing.download_image")
    @patch("scripts.genius_processing._request_with_retry")
    @patch("scripts.genius_processing.Config")
    def test_picks_different_url(self, mock_config, mock_req, mock_dl):
        mock_config.GENIUS_API_TOKEN = "token"
        mock_config.GENIUS_BASE_URL = "https://api.genius.com"
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": {"hits": [
            {"result": {
                "song_art_image_url": "url_A",
                "header_image_url": "url_B",
                "song_art_image_thumbnail_url": "url_C",
            }}
        ]}}
        resp.raise_for_status = MagicMock()
        mock_req.return_value = resp
        mock_dl.return_value = "/tmp/img.png"

        img, chosen = fetch_genius_image_rotated("Artist - Song", "/tmp", current_url="url_A")
        assert chosen != "url_A"  # Should pick B or C

    @patch("scripts.image_processing.download_image")
    @patch("scripts.genius_processing._request_with_retry")
    @patch("scripts.genius_processing.Config")
    def test_fallback_when_all_match_current(self, mock_config, mock_req, mock_dl):
        mock_config.GENIUS_API_TOKEN = "token"
        mock_config.GENIUS_BASE_URL = "https://api.genius.com"
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": {"hits": [
            {"result": {
                "song_art_image_url": "url_A",
                "header_image_url": "url_A",
                "song_art_image_thumbnail_url": "url_A",
            }}
        ]}}
        resp.raise_for_status = MagicMock()
        mock_req.return_value = resp
        mock_dl.return_value = "/tmp/img.png"

        img, chosen = fetch_genius_image_rotated("Artist - Song", "/tmp", current_url="url_A")
        assert chosen == "url_A"  # All same, falls back to only candidate

    @patch("scripts.image_processing.download_image", side_effect=Exception("download failed"))
    @patch("scripts.genius_processing._request_with_retry")
    @patch("scripts.genius_processing.Config")
    def test_download_fails_returns_none(self, mock_config, mock_req, mock_dl):
        mock_config.GENIUS_API_TOKEN = "token"
        mock_config.GENIUS_BASE_URL = "https://api.genius.com"
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": {"hits": [
            {"result": {"song_art_image_url": "url_A"}}
        ]}}
        resp.raise_for_status = MagicMock()
        mock_req.return_value = resp

        img, chosen = fetch_genius_image_rotated("Artist - Song", "/tmp")
        assert img is None


# ---------------------------------------------------------------------------
# _request_with_retry
# ---------------------------------------------------------------------------

class TestRequestWithRetry:

    @patch("scripts.genius_processing.requests.request")
    @patch("scripts.genius_processing.time.sleep")
    def test_retries_on_500(self, mock_sleep, mock_req):
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_200 = MagicMock()
        resp_200.status_code = 200
        mock_req.side_effect = [resp_500, resp_200]
        result = _request_with_retry("GET", "https://example.com", retries=2)
        assert result.status_code == 200

    @patch("scripts.genius_processing.requests.request")
    def test_no_retry_on_404(self, mock_req):
        resp_404 = MagicMock()
        resp_404.status_code = 404
        mock_req.return_value = resp_404
        result = _request_with_retry("GET", "https://example.com", retries=2)
        assert result.status_code == 404
        assert mock_req.call_count == 1  # No retry

    @patch("scripts.genius_processing.requests.request")
    @patch("scripts.genius_processing.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep, mock_req):
        import requests
        resp_200 = MagicMock()
        resp_200.status_code = 200
        mock_req.side_effect = [requests.ConnectionError("failed"), resp_200]
        result = _request_with_retry("GET", "https://example.com", retries=2)
        assert result.status_code == 200

    @patch("scripts.genius_processing.requests.request")
    @patch("scripts.genius_processing.time.sleep")
    def test_exhaustion_raises(self, mock_sleep, mock_req):
        import requests
        mock_req.side_effect = requests.ConnectionError("always fails")
        with pytest.raises(requests.ConnectionError):
            _request_with_retry("GET", "https://example.com", retries=2)
        assert mock_req.call_count == 3  # initial + 2 retries
