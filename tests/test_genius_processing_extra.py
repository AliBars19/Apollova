"""
Additional tests for scripts/genius_processing.py to push coverage past 80%.

Targets the uncovered lines:
  22-25   HAS_BS4=False print path
  81-119  fetch_genius_image() full flow
  152-154 fetch_genius_image_rotated() exception path
  172-173 fetch_genius_image_rotated() no candidates
  250-252 fetch_genius_lyrics() page fetch failure
  262-263 BS4 fails → regex
  266-267 regex fails → cloudflare
  270-271 all methods fail → return None
  390     BS4: no containers at all returns None
  420, 424-426 BS4: empty lyrics_parts / exception
  464     regex: blocks found but all empty after cleaning
  486-547 _extract_with_cloudflare() full flow
  553-558 _cloudflare_html_to_text()
  691     _find_best_hit(): no artist → pool[0]
  703     _find_best_hit(): falls through to pool[0] (default)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.genius_processing import (
    fetch_genius_image,
    fetch_genius_image_rotated,
    fetch_genius_lyrics,
    _extract_with_cloudflare,
    _has_cloudflare_config,
    _cloudflare_html_to_text,
    _find_best_hit,
    _extract_with_beautifulsoup,
    _extract_with_regex,
)
from scripts.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hit(
    full_title="Shape of You - Ed Sheeran",
    artist_name="Ed Sheeran",
    url="https://genius.com/ed-sheeran-shape-of-you-lyrics",
    song_art="https://images.genius.com/fake.jpg",
):
    return {
        "result": {
            "full_title": full_title,
            "url": url,
            "song_art_image_url": song_art,
            "header_image_url": song_art,
            "song_art_image_thumbnail_url": song_art,
            "primary_artist": {"name": artist_name},
            "title": full_title.split(" - ")[-1] if " - " in full_title else full_title,
        }
    }


def _search_response(hits):
    return {"response": {"hits": hits}}


# ===========================================================================
# fetch_genius_image — full flow
# ===========================================================================

class TestFetchGeniusImage:
    def test_no_token_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = ""
        try:
            result = fetch_genius_image("Ed Sheeran - Shape of You", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_empty_song_title_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            result = fetch_genius_image("", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_api_exception_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            with patch("scripts.genius_processing._request_with_retry", side_effect=Exception("timeout")):
                result = fetch_genius_image("Ed Sheeran - Shape of You", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_no_hits_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                result = fetch_genius_image("Unknown Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_no_image_url_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            hit["result"]["song_art_image_url"] = None
            hit["result"]["header_image_url"] = None
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([hit])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                result = fetch_genius_image("Ed Sheeran - Shape of You", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_download_exception_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([hit])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                with patch("scripts.image_processing.download_image", side_effect=Exception("net err")):
                    result = fetch_genius_image("Ed Sheeran - Shape of You", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_successful_download_returns_path(self, tmp_path):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        expected_path = tmp_path / "cover.png"
        try:
            hit = _make_hit()
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([hit])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                with patch("scripts.image_processing.download_image", return_value=str(expected_path)):
                    result = fetch_genius_image("Ed Sheeran - Shape of You", str(tmp_path))
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result == str(expected_path)


# ===========================================================================
# fetch_genius_image_rotated — exception and edge paths
# ===========================================================================

class TestFetchGeniusImageRotated:
    def test_no_token_returns_none_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = ""
        try:
            path, url = fetch_genius_image_rotated("Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert path is None
        assert url is None

    def test_api_exception_returns_none_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            with patch("scripts.genius_processing._request_with_retry", side_effect=Exception("err")):
                path, url = fetch_genius_image_rotated("Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert path is None
        assert url is None

    def test_no_hits_returns_none_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                path, url = fetch_genius_image_rotated("Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert path is None

    def test_no_image_candidates_returns_none_none(self):
        """All hits have None image URLs → no candidates."""
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = {
                "result": {
                    "full_title": "Song",
                    "primary_artist": {"name": "Artist"},
                    "song_art_image_url": None,
                    "header_image_url": None,
                    "song_art_image_thumbnail_url": None,
                }
            }
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([hit])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                path, url = fetch_genius_image_rotated("Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert path is None
        assert url is None

    def test_download_failure_returns_none_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            mock_resp = MagicMock()
            mock_resp.json.return_value = _search_response([hit])
            with patch("scripts.genius_processing._request_with_retry", return_value=mock_resp):
                with patch("scripts.image_processing.download_image", side_effect=Exception("dl err")):
                    path, url = fetch_genius_image_rotated("Song", "/tmp")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert path is None


# ===========================================================================
# fetch_genius_lyrics — failure branches
# ===========================================================================

class TestFetchGeniusLyricsFailurePaths:
    def test_page_fetch_fails_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            search_resp = MagicMock()
            search_resp.json.return_value = _search_response([hit])

            call_count = {"n": 0}

            def fake_request(method, url, **kwargs):
                call_count["n"] += 1
                if "search" in url:
                    return search_resp
                # Lyrics page fetch
                raise Exception("connection refused")

            with patch("scripts.genius_processing._request_with_retry", side_effect=fake_request):
                result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_all_extraction_methods_fail_returns_none(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            search_resp = MagicMock()
            search_resp.json.return_value = _search_response([hit])

            page_resp = MagicMock()
            page_resp.text = "<html><body>No lyrics here</body></html>"

            def fake_request(method, url, **kwargs):
                if "search" in url:
                    return search_resp
                return page_resp

            with patch("scripts.genius_processing._request_with_retry", side_effect=fake_request):
                with patch("scripts.genius_processing._extract_from_preloaded_state", return_value=None):
                    with patch("scripts.genius_processing._extract_with_beautifulsoup", return_value=None):
                        with patch("scripts.genius_processing._extract_with_regex", return_value=None):
                            with patch("scripts.genius_processing._has_cloudflare_config", return_value=False):
                                result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
        finally:
            Config.GENIUS_API_TOKEN = original
        assert result is None

    def test_falls_through_to_cloudflare_method(self):
        original = Config.GENIUS_API_TOKEN
        Config.GENIUS_API_TOKEN = "token"
        try:
            hit = _make_hit()
            search_resp = MagicMock()
            search_resp.json.return_value = _search_response([hit])

            page_resp = MagicMock()
            page_resp.text = "<html><body>No lyrics</body></html>"

            def fake_request(method, url, **kwargs):
                if "search" in url:
                    return search_resp
                return page_resp

            with patch("scripts.genius_processing._request_with_retry", side_effect=fake_request):
                with patch("scripts.genius_processing._extract_from_preloaded_state", return_value=None):
                    with patch("scripts.genius_processing._extract_with_beautifulsoup", return_value=None):
                        with patch("scripts.genius_processing._extract_with_regex", return_value=None):
                            with patch("scripts.genius_processing._has_cloudflare_config", return_value=True):
                                with patch("scripts.genius_processing._extract_with_cloudflare", return_value="Some lyrics") as mock_cf:
                                    result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
            mock_cf.assert_called_once()
        finally:
            Config.GENIUS_API_TOKEN = original


# ===========================================================================
# _extract_with_beautifulsoup — no containers path
# ===========================================================================

class TestExtractWithBeautifulsoupExtra:
    def test_no_containers_returns_none(self):
        html = "<html><body><p>no lyrics divs here</p></body></html>"
        result = _extract_with_beautifulsoup(html)
        assert result is None

    def test_empty_container_text_returns_none(self):
        html = '<html><body><div data-lyrics-container="true">   </div></body></html>'
        result = _extract_with_beautifulsoup(html)
        assert result is None

    def test_bs4_exception_returns_none(self):
        with patch("scripts.genius_processing.BeautifulSoup", side_effect=Exception("bs4 broken")):
            result = _extract_with_beautifulsoup("<html></html>")
        assert result is None


# ===========================================================================
# _extract_with_regex — edge paths
# ===========================================================================

class TestExtractWithRegexExtra:
    def test_blocks_all_whitespace_returns_none(self):
        html = '<div data-lyrics-container="true">   <br/>  </div>'
        result = _extract_with_regex(html)
        assert result is None

    def test_class_based_fallback(self):
        html = '<div class="Lyrics__Container">Hello world lyrics</div>'
        result = _extract_with_regex(html)
        assert result is not None
        assert "Hello world" in result


# ===========================================================================
# _extract_with_cloudflare — full flow
# ===========================================================================

class TestExtractWithCloudflare:
    def _setup_cloudflare(self):
        orig_id = Config.CLOUDFLARE_ACCOUNT_ID
        orig_token = Config.CLOUDFLARE_API_TOKEN
        Config.CLOUDFLARE_ACCOUNT_ID = "test_account_id"
        Config.CLOUDFLARE_API_TOKEN = "test_cf_token"
        return orig_id, orig_token

    def _teardown_cloudflare(self, orig_id, orig_token):
        Config.CLOUDFLARE_ACCOUNT_ID = orig_id
        Config.CLOUDFLARE_API_TOKEN = orig_token

    def test_returns_none_when_no_config(self):
        orig_id = Config.CLOUDFLARE_ACCOUNT_ID
        orig_token = Config.CLOUDFLARE_API_TOKEN
        Config.CLOUDFLARE_ACCOUNT_ID = ""
        Config.CLOUDFLARE_API_TOKEN = ""
        try:
            result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            Config.CLOUDFLARE_ACCOUNT_ID = orig_id
            Config.CLOUDFLARE_API_TOKEN = orig_token
        assert result is None

    def test_request_exception_returns_none(self):
        orig = self._setup_cloudflare()
        try:
            with patch("requests.post", side_effect=Exception("CF timeout")):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is None

    def test_api_returns_success_false_returns_none(self):
        orig = self._setup_cloudflare()
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"success": False, "errors": ["blocked"]}
            with patch("requests.post", return_value=mock_resp):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is None

    def test_no_elements_returns_none(self):
        orig = self._setup_cloudflare()
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "success": True,
                "result": {"elements": []},
            }
            with patch("requests.post", return_value=mock_resp):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is None

    def test_elements_with_text_returns_lyrics(self):
        orig = self._setup_cloudflare()
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "success": True,
                "result": {
                    "elements": [
                        {
                            "results": [
                                {"text": "I'm in love with the shape of you"},
                                {"text": "We push and pull like a magnet do"},
                            ]
                        }
                    ]
                },
            }
            with patch("requests.post", return_value=mock_resp):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is not None
        assert "shape of you" in result.lower()

    def test_elements_with_html_fallback(self):
        orig = self._setup_cloudflare()
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "success": True,
                "result": {
                    "elements": [
                        {
                            "results": [
                                {
                                    "text": "",
                                    "html": '<br/>Hello<br/>World<br/>',
                                }
                            ]
                        }
                    ]
                },
            }
            with patch("requests.post", return_value=mock_resp):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is not None
        assert "Hello" in result

    def test_elements_with_all_empty_text_returns_none(self):
        orig = self._setup_cloudflare()
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "success": True,
                "result": {
                    "elements": [
                        {"results": [{"text": "   ", "html": ""}]}
                    ]
                },
            }
            with patch("requests.post", return_value=mock_resp):
                result = _extract_with_cloudflare("https://genius.com/test")
        finally:
            self._teardown_cloudflare(*orig)
        assert result is None


# ===========================================================================
# _cloudflare_html_to_text
# ===========================================================================

class TestCloudflareHtmlToText:
    def test_br_replaced_with_newline(self):
        html = "Hello<br/>World"
        result = _cloudflare_html_to_text(html)
        assert "\n" in result
        assert "Hello" in result
        assert "World" in result

    def test_tags_stripped(self):
        html = "<span>Hello</span> <b>World</b>"
        result = _cloudflare_html_to_text(html)
        assert "<" not in result
        assert "Hello" in result
        assert "World" in result

    def test_html_entities_unescaped(self):
        html = "I&apos;m in love &amp; you"
        result = _cloudflare_html_to_text(html)
        assert "&amp;" not in result
        assert "love" in result

    def test_br_variants(self):
        html = "A<br>B<br />C"
        result = _cloudflare_html_to_text(html)
        assert result.count("\n") >= 2


# ===========================================================================
# _find_best_hit — edge paths
# ===========================================================================

class TestFindBestHitExtra:
    def test_no_artist_returns_first_pool_entry(self):
        hits = [
            _make_hit("Song A", "Artist A", "https://genius.com/a"),
            _make_hit("Song B", "Artist B", "https://genius.com/b"),
        ]
        result = _find_best_hit(hits, None, "Song A")
        # With no artist, should return pool[0]
        assert result["result"]["url"] == "https://genius.com/a"

    def test_all_translations_uses_full_pool(self):
        """If every hit is a translation, fall back to using all hits."""
        hits = [
            _make_hit("Song - Genius Traductions", "Genius Traductions", "https://genius.com/t"),
        ]
        result = _find_best_hit(hits, "Ed Sheeran", "Song")
        # Falls back to translations pool since no originals
        assert result is not None

    def test_no_artist_match_returns_pool_first(self):
        """When artist not found in any hit, default to first pool entry."""
        hits = [
            _make_hit("Song A", "Completely Different Artist", "https://genius.com/a"),
            _make_hit("Song B", "Another Artist", "https://genius.com/b"),
        ]
        result = _find_best_hit(hits, "NonExistent Artist", "Unknown Song")
        assert result is not None
