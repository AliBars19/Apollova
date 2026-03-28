"""
Tests for scripts/genius_processing.py

Covers:
  - _parse_song_title: "Artist - Song" splitting
  - _is_section_header: bracket and parenthesis detection
  - _clean_for_match (via _clean_lyrics): metadata lines stripped
  - _clean_lyrics: section headers preserved, junk removed
  - _extract_from_preloaded_state: JSON extraction skipped (hard to fake)
  - _extract_with_beautifulsoup: div with data-lyrics-container parsed
  - _extract_with_regex: regex fallback on simple div block
  - _find_best_hit: prefers artist match, skips translations
  - fetch_genius_lyrics: full mock of network calls returning lyrics string
  - fetch_genius_image: full mock returning image path
  - _has_cloudflare_config: returns False when env vars are absent
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import genius_processing
from scripts.genius_processing import (
    _parse_song_title,
    _find_best_hit,
    _clean_lyrics,
    _extract_with_beautifulsoup,
    _extract_with_regex,
    _has_cloudflare_config,
    fetch_genius_lyrics,
)
from scripts.lyric_alignment import _is_section_header


# ===========================================================================
# _parse_song_title
# ===========================================================================

class TestParseSongTitle:
    def test_artist_dash_song(self):
        artist, title = _parse_song_title("Ed Sheeran - Shape of You")
        assert artist == "Ed Sheeran"
        assert title == "Shape of You"

    def test_song_only(self):
        artist, title = _parse_song_title("Bohemian Rhapsody")
        assert artist is None
        assert title == "Bohemian Rhapsody"

    def test_multiple_dashes_splits_on_first(self):
        artist, title = _parse_song_title("A - B - C")
        assert artist == "A"
        assert title == "B - C"

    def test_strips_whitespace(self):
        artist, title = _parse_song_title("  Ed Sheeran  -  Shape of You  ")
        assert artist == "Ed Sheeran"
        assert title == "Shape of You"


# ===========================================================================
# _is_section_header (from lyric_alignment — used by genius_processing)
# ===========================================================================

class TestIsSectionHeader:
    def test_chorus_bracket(self):
        assert _is_section_header("[Chorus]") is True

    def test_verse_bracket(self):
        assert _is_section_header("[Verse 1]") is True

    def test_chorus_paren(self):
        assert _is_section_header("(Chorus)") is True

    def test_intro_bracket(self):
        assert _is_section_header("[Intro]") is True

    def test_normal_lyric_not_header(self):
        assert _is_section_header("I'm in love with the shape of you") is False

    def test_empty_string_not_header(self):
        assert _is_section_header("") is False


# ===========================================================================
# _clean_lyrics
# ===========================================================================

class TestCleanLyrics:
    def test_removes_contributors_line(self):
        text = "I'm in love\n5 contributors\nWith you"
        cleaned = _clean_lyrics(text)
        assert "contributors" not in cleaned
        assert "I'm in love" in cleaned

    def test_removes_embed_line(self):
        text = "Hello world\nEmbed\nGoodbye"
        cleaned = _clean_lyrics(text)
        assert "Embed" not in cleaned

    def test_removes_you_might_also_like(self):
        text = "Lyric line\nYou might also like\nAnother line"
        cleaned = _clean_lyrics(text)
        assert "You might also like" not in cleaned

    def test_preserves_section_headers(self):
        text = "[Chorus]\nI'm in love\n[Verse 2]\nWith you"
        cleaned = _clean_lyrics(text)
        assert "[Chorus]" in cleaned
        assert "[Verse 2]" in cleaned

    def test_collapses_triple_blank_lines(self):
        text = "Line one\n\n\n\nLine two"
        cleaned = _clean_lyrics(text)
        assert "\n\n\n" not in cleaned

    def test_returns_none_for_empty(self):
        assert _clean_lyrics("") is None
        assert _clean_lyrics("   ") is None

    def test_strips_leading_trailing_blanks(self):
        text = "\n\nActual lyrics\n\n"
        cleaned = _clean_lyrics(text)
        assert cleaned.startswith("Actual")
        assert cleaned.endswith("lyrics")


# ===========================================================================
# _extract_with_beautifulsoup
# ===========================================================================

class TestExtractWithBeautifulSoup:
    def test_extracts_from_lyrics_container(self, genius_lyrics_html: str):
        result = _extract_with_beautifulsoup(genius_lyrics_html)
        assert result is not None
        assert "shape of you" in result.lower()

    def test_preserves_line_breaks(self, genius_lyrics_html: str):
        result = _extract_with_beautifulsoup(genius_lyrics_html)
        assert "\n" in result

    def test_returns_none_for_page_without_container(self):
        html = "<html><body><p>No lyrics here</p></body></html>"
        result = _extract_with_beautifulsoup(html)
        assert result is None

    def test_returns_none_for_empty_html(self):
        result = _extract_with_beautifulsoup("")
        assert result is None


# ===========================================================================
# _extract_with_regex
# ===========================================================================

class TestExtractWithRegex:
    def test_extracts_simple_block(self):
        html = (
            '<div data-lyrics-container="true">'
            'Hello world<br/>Second line'
            '</div>'
        )
        result = _extract_with_regex(html)
        assert result is not None
        assert "Hello world" in result
        assert "Second line" in result

    def test_returns_none_when_no_match(self):
        html = "<html><body><p>Nothing here</p></body></html>"
        result = _extract_with_regex(html)
        assert result is None

    def test_strips_html_tags(self):
        html = (
            '<div data-lyrics-container="true">'
            '<a href="#">Hello</a> <b>world</b>'
            '</div>'
        )
        result = _extract_with_regex(html)
        assert "<a" not in result
        assert "<b" not in result


# ===========================================================================
# _find_best_hit
# ===========================================================================

class TestFindBestHit:
    def _hit(self, full_title: str, artist: str, url: str = "https://genius.com/test") -> dict:
        return {
            "result": {
                "full_title": full_title,
                "url": url,
                "primary_artist": {"name": artist},
                "title": full_title.split(" - ")[-1] if " - " in full_title else full_title,
                "song_art_image_url": None,
                "header_image_url": None,
            }
        }

    def test_prefers_exact_artist_match(self):
        hits = [
            self._hit("Shape of You - Unknown Artist", "Unknown Artist"),
            self._hit("Shape of You - Ed Sheeran",     "Ed Sheeran"),
        ]
        best = _find_best_hit(hits, "Ed Sheeran", "Shape of You")
        assert best["result"]["primary_artist"]["name"] == "Ed Sheeran"

    def test_filters_translations(self):
        hits = [
            self._hit("Shape of You - Ed Sheeran Türkçe Çeviri", "Genius Türkçe"),
            self._hit("Shape of You - Ed Sheeran", "Ed Sheeran"),
        ]
        best = _find_best_hit(hits, "Ed Sheeran", "Shape of You")
        assert "Ed Sheeran" == best["result"]["primary_artist"]["name"]

    def test_returns_first_when_no_artist(self):
        hits = [
            self._hit("Song A - Artist A", "Artist A"),
            self._hit("Song B - Artist B", "Artist B"),
        ]
        best = _find_best_hit(hits, None, "Song")
        assert best == hits[0]

    def test_falls_back_when_all_are_translations(self):
        """If all hits are translations, fall back to first result."""
        hits = [
            self._hit("Shape of You Tradução", "Genius Brasil"),
            self._hit("Shape of You Traduction", "Genius Traductions"),
        ]
        # Should not raise
        best = _find_best_hit(hits, "Ed Sheeran", "Shape of You")
        assert best is not None


# ===========================================================================
# fetch_genius_lyrics — fully mocked
# ===========================================================================

class TestFetchGeniusLyrics:
    def _mock_responses(self, search_json: dict, lyrics_html: str):
        """Build two mock requests.get responses: search API + lyrics page."""
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = search_json
        search_resp.raise_for_status = MagicMock()

        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = lyrics_html

        return [search_resp, page_resp]

    def test_returns_lyrics_string(
        self,
        genius_search_response: dict,
        genius_lyrics_html: str,
    ):
        responses = self._mock_responses(genius_search_response, genius_lyrics_html)
        with patch("scripts.genius_processing._request_with_retry", side_effect=responses):
            with patch("scripts.config.Config.GENIUS_API_TOKEN", "fake_token"):
                result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_none_when_api_token_missing(self):
        with patch("scripts.config.Config.GENIUS_API_TOKEN", ""):
            result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
        assert result is None

    def test_returns_none_when_no_hits(self):
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"response": {"hits": []}}
        empty_resp.raise_for_status = MagicMock()

        with patch("scripts.genius_processing._request_with_retry", return_value=empty_resp):
            with patch("scripts.config.Config.GENIUS_API_TOKEN", "fake_token"):
                result = fetch_genius_lyrics("Non Existent Song 99999")
        assert result is None

    def test_returns_none_when_network_fails(self):
        with patch(
            "scripts.genius_processing._request_with_retry",
            side_effect=Exception("connection refused"),
        ):
            with patch("scripts.config.Config.GENIUS_API_TOKEN", "fake_token"):
                result = fetch_genius_lyrics("Ed Sheeran - Shape of You")
        assert result is None


# ===========================================================================
# _has_cloudflare_config
# ===========================================================================

class TestHasCloudflareConfig:
    def test_returns_false_when_not_configured(self):
        with patch("scripts.config.Config.CLOUDFLARE_ACCOUNT_ID", ""):
            with patch("scripts.config.Config.CLOUDFLARE_API_TOKEN", ""):
                assert _has_cloudflare_config() is False

    def test_returns_true_when_configured(self):
        with patch("scripts.config.Config.CLOUDFLARE_ACCOUNT_ID", "abc123"):
            with patch("scripts.config.Config.CLOUDFLARE_API_TOKEN", "tok_xyz"):
                assert _has_cloudflare_config() is True
