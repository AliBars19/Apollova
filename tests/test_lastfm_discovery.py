"""
Tests for scripts/lastfm_discovery.py

Covers:
  - LastFMTrack dataclass: fields, duration_sec_safe, search_query, db_title
  - LastFMClient._get: happy path, HTTP error, API error code, rate-limit (code 29),
    network error retries, exhausted retries raise
  - LastFMClient.get_top_tracks_global: delegates to _get with correct params
  - LastFMClient.get_top_tracks_by_country: delegates to _get with correct params
  - LastFMClient.get_top_tracks_by_tag: delegates to _get with correct params
  - LastFMClient.get_track_info: happy path, error-6 returns None, other errors re-raise
  - get_api_key: present key returned, missing key raises ValueError
  - test_connection: success path, empty tracks, missing key, exception path
  - fetch_tracks: unknown source raises ValueError, chart method, geo method, tag method
  - fetch_tracks: skips tracks with empty title or empty artist
  - fetch_tracks: artist as plain string instead of dict
  - fetch_tracks: progress_cb is called
  - fetch_tracks: fetch_durations=False skips _enrich_durations
  - _enrich_durations: fills duration_sec from millisecond string, fills tags,
    handles None info, handles exception per track, calls progress_cb
  - _enrich_durations: duration "0" leaves duration_sec as 0
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest
import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_track(
    name: str = "Shape of You",
    artist_name: str = "Ed Sheeran",
    listeners: int = 5_000_000,
    playcount: int = 50_000_000,
    url: str = "https://www.last.fm/music/Ed+Sheeran/_/Shape+of+You",
    artist_as_dict: bool = True,
) -> dict:
    """Build a minimal raw track dict as the Last.fm API returns it."""
    artist: Any = {"name": artist_name} if artist_as_dict else artist_name
    return {
        "name": name,
        "artist": artist,
        "listeners": str(listeners),
        "playcount": str(playcount),
        "url": url,
    }


def _track_info_response(duration_ms: int = 225_000) -> dict:
    """Canned track.getInfo payload."""
    return {
        "track": {
            "name": "Shape of You",
            "artist": {"name": "Ed Sheeran"},
            "duration": str(duration_ms),
            "toptags": {
                "tag": [
                    {"name": "pop"},
                    {"name": "indie pop"},
                    {"name": "british"},
                ]
            },
        }
    }


# ===========================================================================
# LastFMTrack dataclass
# ===========================================================================

class TestLastFMTrack:
    def _make(self, duration_sec=225.0):
        from scripts.lastfm_discovery import LastFMTrack
        return LastFMTrack(
            title="Shape of You",
            artist="Ed Sheeran",
            duration_sec=duration_sec,
            listeners=5_000_000,
            playcount=50_000_000,
            lastfm_url="https://www.last.fm/music/Ed+Sheeran/_/Shape+of+You",
        )

    def test_fields_stored_correctly(self):
        t = self._make(225.0)
        assert t.title == "Shape of You"
        assert t.artist == "Ed Sheeran"
        assert t.duration_sec == 225.0
        assert t.listeners == 5_000_000
        assert t.playcount == 50_000_000

    def test_duration_sec_safe_returns_actual_when_positive(self):
        t = self._make(225.0)
        assert t.duration_sec_safe == 225.0

    def test_duration_sec_safe_returns_fallback_when_zero(self):
        from scripts.lastfm_discovery import FALLBACK_DURATION_SEC
        t = self._make(0.0)
        assert t.duration_sec_safe == FALLBACK_DURATION_SEC

    def test_search_query_combines_artist_and_title(self):
        t = self._make()
        assert t.search_query == "Ed Sheeran Shape of You"

    def test_db_title_format(self):
        t = self._make()
        assert t.db_title == "Ed Sheeran - Shape of You"

    def test_tags_default_to_empty_list(self):
        t = self._make()
        assert t.tags == []

    def test_tags_can_be_set(self):
        from scripts.lastfm_discovery import LastFMTrack
        t = LastFMTrack(
            title="Song",
            artist="Artist",
            duration_sec=200.0,
            listeners=1000,
            playcount=5000,
            lastfm_url="https://last.fm/x",
            tags=["pop", "indie"],
        )
        assert t.tags == ["pop", "indie"]


# ===========================================================================
# LastFMClient._get
# ===========================================================================

class TestLastFMClientGet:
    def _make_client(self):
        from scripts.lastfm_discovery import LastFMClient
        return LastFMClient(api_key="testkey123")

    def _mock_response(self, json_data: dict, status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    def test_happy_path_returns_json(self):
        client = self._make_client()
        payload = {"tracks": {"track": []}}
        mock_resp = self._mock_response(payload)

        with patch.object(client.session, "get", return_value=mock_resp):
            result = client._get({"method": "chart.getTopTracks"})

        assert result == payload

    def test_api_key_added_to_params(self):
        client = self._make_client()
        mock_resp = self._mock_response({"ok": True})

        with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
            client._get({"method": "chart.getTopTracks"})

        # session.get is called with (url, params=...) — extract params regardless
        # of whether they were passed positionally or as a keyword argument
        call_kwargs = mock_get.call_args.kwargs
        call_params = call_kwargs.get("params", {})
        assert call_params.get("api_key") == "testkey123"

    def test_format_json_added_to_params(self):
        client = self._make_client()
        mock_resp = self._mock_response({"ok": True})

        with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
            client._get({"method": "chart.getTopTracks"})

        call_kwargs = mock_get.call_args.kwargs
        call_params = call_kwargs.get("params", {})
        assert call_params.get("format") == "json"

    def test_api_error_non_rate_limit_raises_value_error(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error": 10, "message": "Invalid API key"})

        with patch.object(client.session, "get", return_value=mock_resp):
            with pytest.raises(ValueError, match="Last.fm API error 10"):
                client._get({"method": "chart.getTopTracks"})

    def test_rate_limit_error_29_retries(self):
        """Error 29 should sleep and retry, not immediately raise."""
        client = self._make_client()

        rate_limit_resp = self._mock_response({"error": 29, "message": "Rate limit exceeded"})
        success_resp = self._mock_response({"tracks": {"track": []}})

        with patch.object(
            client.session, "get", side_effect=[rate_limit_resp, success_resp]
        ):
            with patch("time.sleep"):   # avoid real sleep in tests
                result = client._get({"method": "chart.getTopTracks"}, retries=2)

        assert result == {"tracks": {"track": []}}

    def test_http_error_retries_then_raises(self):
        """A requests.RequestException should retry and eventually re-raise."""
        client = self._make_client()

        with patch.object(
            client.session,
            "get",
            side_effect=requests.RequestException("connection reset"),
        ):
            with patch("time.sleep"):
                with pytest.raises(requests.RequestException):
                    client._get({"method": "chart.getTopTracks"}, retries=2)

    def test_exhausted_rate_limit_raises_runtime_error(self):
        """After exhausting all retries on rate limit, RuntimeError is raised."""
        client = self._make_client()
        rate_limit_resp = self._mock_response({"error": 29, "message": "Rate limit"})

        with patch.object(
            client.session, "get", return_value=rate_limit_resp
        ):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError, match="failed after"):
                    client._get({"method": "chart.getTopTracks"}, retries=2)

    def test_http_error_first_attempt_retries_on_second(self):
        """Network error on first attempt but success on second."""
        client = self._make_client()
        success_resp = self._mock_response({"data": "ok"})

        with patch.object(
            client.session,
            "get",
            side_effect=[requests.RequestException("timeout"), success_resp],
        ):
            with patch("time.sleep"):
                result = client._get({"method": "chart.getTopTracks"}, retries=2)

        assert result == {"data": "ok"}


# ===========================================================================
# LastFMClient chart methods
# ===========================================================================

class TestLastFMClientChartMethods:
    def _make_client(self):
        from scripts.lastfm_discovery import LastFMClient
        return LastFMClient(api_key="testkey123")

    def test_get_top_tracks_global_returns_track_list(self):
        client = self._make_client()
        payload = {"tracks": {"track": [_raw_track()]}}
        with patch.object(client, "_get", return_value=payload) as mock_get:
            result = client.get_top_tracks_global(limit=10, page=1)

        mock_get.assert_called_once()
        called_params = mock_get.call_args[0][0]
        assert called_params["method"] == "chart.getTopTracks"
        assert called_params["limit"] == 10
        assert len(result) == 1

    def test_get_top_tracks_global_empty_response(self):
        client = self._make_client()
        with patch.object(client, "_get", return_value={}):
            result = client.get_top_tracks_global()
        assert result == []

    def test_get_top_tracks_by_country_passes_country(self):
        client = self._make_client()
        payload = {"tracks": {"track": [_raw_track()]}}
        with patch.object(client, "_get", return_value=payload) as mock_get:
            result = client.get_top_tracks_by_country("United Kingdom", limit=25)

        called_params = mock_get.call_args[0][0]
        assert called_params["method"] == "geo.getTopTracks"
        assert called_params["country"] == "United Kingdom"
        assert called_params["limit"] == 25

    def test_get_top_tracks_by_country_empty_response(self):
        client = self._make_client()
        with patch.object(client, "_get", return_value={}):
            result = client.get_top_tracks_by_country("France")
        assert result == []

    def test_get_top_tracks_by_tag_passes_tag(self):
        client = self._make_client()
        payload = {"tracks": {"track": [_raw_track()]}}
        with patch.object(client, "_get", return_value=payload) as mock_get:
            result = client.get_top_tracks_by_tag("hip-hop", limit=20)

        called_params = mock_get.call_args[0][0]
        assert called_params["method"] == "tag.getTopTracks"
        assert called_params["tag"] == "hip-hop"
        assert called_params["limit"] == 20

    def test_get_top_tracks_by_tag_empty_response(self):
        client = self._make_client()
        with patch.object(client, "_get", return_value={}):
            result = client.get_top_tracks_by_tag("jazz")
        assert result == []


# ===========================================================================
# LastFMClient.get_track_info
# ===========================================================================

class TestGetTrackInfo:
    def _make_client(self):
        from scripts.lastfm_discovery import LastFMClient
        return LastFMClient(api_key="testkey123")

    def test_happy_path_returns_track_dict(self):
        client = self._make_client()
        info_resp = _track_info_response()
        with patch.object(client, "_get", return_value=info_resp):
            result = client.get_track_info("Ed Sheeran", "Shape of You")

        assert result is not None
        assert result["name"] == "Shape of You"

    def test_error_6_not_found_returns_none(self):
        client = self._make_client()
        with patch.object(
            client, "_get", side_effect=ValueError("Last.fm API error 6: Track not found")
        ):
            result = client.get_track_info("Unknown Artist", "Nonexistent Song")

        assert result is None

    def test_other_value_error_re_raises(self):
        client = self._make_client()
        with patch.object(
            client, "_get", side_effect=ValueError("Last.fm API error 10: Invalid key")
        ):
            with pytest.raises(ValueError, match="error 10"):
                client.get_track_info("Artist", "Song")

    def test_autocorrect_param_sent(self):
        client = self._make_client()
        info_resp = _track_info_response()
        with patch.object(client, "_get", return_value=info_resp) as mock_get:
            client.get_track_info("Ed Sheeran", "Shape of You")

        called_params = mock_get.call_args[0][0]
        assert called_params.get("autocorrect") == "1"

    def test_missing_track_key_in_response_returns_none(self):
        client = self._make_client()
        with patch.object(client, "_get", return_value={"other": "data"}):
            result = client.get_track_info("Artist", "Song")
        assert result is None


# ===========================================================================
# get_api_key
# ===========================================================================

class TestGetApiKey:
    def test_returns_key_when_set(self):
        from scripts.lastfm_discovery import get_api_key
        with patch.dict("os.environ", {"LASTFM_API_KEY": "abc123"}):
            assert get_api_key() == "abc123"

    def test_raises_when_key_missing(self):
        from scripts.lastfm_discovery import get_api_key
        with patch.dict("os.environ", {}, clear=True):
            # Ensure the env var is absent
            import os
            os.environ.pop("LASTFM_API_KEY", None)
            with pytest.raises(ValueError, match="LASTFM_API_KEY"):
                get_api_key()

    def test_raises_when_key_is_empty_string(self):
        from scripts.lastfm_discovery import get_api_key
        with patch.dict("os.environ", {"LASTFM_API_KEY": "  "}):
            with pytest.raises(ValueError, match="LASTFM_API_KEY"):
                get_api_key()


# ===========================================================================
# test_connection
# ===========================================================================

class TestTestConnection:
    def test_success_returns_true_and_connected(self):
        from scripts.lastfm_discovery import test_connection

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient") as MockClient:
                MockClient.return_value.get_top_tracks_global.return_value = [_raw_track()]
                ok, msg = test_connection()

        assert ok is True
        assert msg == "Connected"

    def test_empty_track_list_returns_false(self):
        from scripts.lastfm_discovery import test_connection

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient") as MockClient:
                MockClient.return_value.get_top_tracks_global.return_value = []
                ok, msg = test_connection()

        assert ok is False
        assert "no tracks" in msg.lower()

    def test_missing_api_key_returns_false(self):
        from scripts.lastfm_discovery import test_connection

        with patch(
            "scripts.lastfm_discovery.get_api_key",
            side_effect=ValueError("LASTFM_API_KEY is not set"),
        ):
            ok, msg = test_connection()

        assert ok is False
        assert "LASTFM_API_KEY" in msg

    def test_network_exception_returns_false_with_message(self):
        from scripts.lastfm_discovery import test_connection

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient") as MockClient:
                MockClient.return_value.get_top_tracks_global.side_effect = (
                    requests.RequestException("timeout")
                )
                ok, msg = test_connection()

        assert ok is False
        assert "Connection failed" in msg


# ===========================================================================
# fetch_tracks
# ===========================================================================

class TestFetchTracks:
    def _patch_env_and_client(self, raw_tracks: list[dict], info_resp: dict | None = None):
        """Context manager patcher: patches api key + LastFMClient."""
        from scripts.lastfm_discovery import LastFMClient

        mock_client = MagicMock(spec=LastFMClient)
        mock_client.get_top_tracks_global.return_value = raw_tracks
        mock_client.get_top_tracks_by_country.return_value = raw_tracks
        mock_client.get_top_tracks_by_tag.return_value = raw_tracks

        if info_resp is not None:
            mock_client.get_track_info.return_value = info_resp.get("track")
        else:
            mock_client.get_track_info.return_value = _track_info_response().get("track")

        return mock_client

    def test_unknown_source_raises_value_error(self):
        from scripts.lastfm_discovery import fetch_tracks
        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with pytest.raises(ValueError, match="Unknown source"):
                fetch_tracks("Nonexistent Source")

    def test_global_chart_method_dispatched_correctly(self):
        from scripts.lastfm_discovery import fetch_tracks, CHART_SOURCES

        raw = [_raw_track()]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        mock_client.get_top_tracks_global.assert_called()
        assert len(tracks) == 1

    def test_geo_method_dispatched_correctly(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track()]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("United Kingdom", limit=1, fetch_durations=False)

        mock_client.get_top_tracks_by_country.assert_called()
        assert len(tracks) == 1

    def test_tag_method_dispatched_correctly(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track()]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Genre — Pop", limit=1, fetch_durations=False)

        mock_client.get_top_tracks_by_tag.assert_called()
        assert len(tracks) == 1

    def test_skips_track_with_empty_name(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track(name="")]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        assert tracks == []

    def test_skips_track_with_empty_artist(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track(artist_name="")]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        assert tracks == []

    def test_artist_as_plain_string_handled(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track(artist_as_dict=False)]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        assert len(tracks) == 1
        assert tracks[0].artist == "Ed Sheeran"

    def test_progress_cb_called_for_each_track(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track(), _raw_track(name="Thinking Out Loud")]
        mock_client = self._patch_env_and_client(raw)
        progress_calls: list[tuple] = []

        def on_progress(current, total, title):
            progress_calls.append((current, total, title))

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    fetch_tracks(
                        "Global Top 100",
                        limit=2,
                        fetch_durations=False,
                        progress_cb=on_progress,
                    )

        assert len(progress_calls) == 2
        assert progress_calls[0][0] == 1   # current=1
        assert progress_calls[1][0] == 2   # current=2

    def test_fetch_durations_false_skips_enrich(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track()]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("scripts.lastfm_discovery._enrich_durations") as mock_enrich:
                    with patch("time.sleep"):
                        fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        mock_enrich.assert_not_called()

    def test_fetch_durations_true_calls_enrich(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track()]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("scripts.lastfm_discovery._enrich_durations") as mock_enrich:
                    with patch("time.sleep"):
                        fetch_tracks("Global Top 100", limit=1, fetch_durations=True)

        mock_enrich.assert_called_once()

    def test_empty_raw_batch_stops_fetching(self):
        from scripts.lastfm_discovery import fetch_tracks

        mock_client = MagicMock()
        mock_client.get_top_tracks_global.return_value = []  # empty immediately

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=50, fetch_durations=False)

        assert tracks == []

    def test_track_listeners_and_playcount_parsed(self):
        from scripts.lastfm_discovery import fetch_tracks

        raw = [_raw_track(listeners=1_234_567, playcount=9_876_543)]
        mock_client = self._patch_env_and_client(raw)

        with patch("scripts.lastfm_discovery.get_api_key", return_value="key"):
            with patch("scripts.lastfm_discovery.LastFMClient", return_value=mock_client):
                with patch("time.sleep"):
                    tracks = fetch_tracks("Global Top 100", limit=1, fetch_durations=False)

        assert tracks[0].listeners == 1_234_567
        assert tracks[0].playcount == 9_876_543


# ===========================================================================
# _enrich_durations
# ===========================================================================

class TestEnrichDurations:
    def _make_track(self, title="Shape of You", artist="Ed Sheeran"):
        from scripts.lastfm_discovery import LastFMTrack
        return LastFMTrack(
            title=title,
            artist=artist,
            duration_sec=0.0,
            listeners=1_000,
            playcount=5_000,
            lastfm_url="https://last.fm/x",
        )

    def _make_client(self):
        from scripts.lastfm_discovery import LastFMClient
        return MagicMock(spec=LastFMClient)

    def test_fills_duration_sec_from_ms_string(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()
        client.get_track_info.return_value = _track_info_response(225_000)["track"]

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert track.duration_sec == pytest.approx(225.0)

    def test_duration_zero_leaves_duration_sec_zero(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()
        client.get_track_info.return_value = _track_info_response(0)["track"]

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert track.duration_sec == pytest.approx(0.0)

    def test_fills_tags_from_toptags(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()
        client.get_track_info.return_value = _track_info_response(200_000)["track"]

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert "pop" in track.tags
        assert len(track.tags) <= 5

    def test_tags_capped_at_five(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()

        many_tags = {"tag": [{"name": f"tag{i}"} for i in range(10)]}
        client.get_track_info.return_value = {
            "name": "Song",
            "duration": "200000",
            "toptags": many_tags,
        }

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert len(track.tags) == 5

    def test_none_info_leaves_duration_unchanged(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()
        client.get_track_info.return_value = None

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert track.duration_sec == 0.0

    def test_exception_per_track_does_not_stop_others(self):
        from scripts.lastfm_discovery import _enrich_durations, LastFMTrack

        track_a = self._make_track("Song A", "Artist A")
        track_b = self._make_track("Song B", "Artist B")
        client = self._make_client()

        # First call raises, second call succeeds
        client.get_track_info.side_effect = [
            Exception("network error"),
            _track_info_response(180_000)["track"],
        ]

        with patch("time.sleep"):
            _enrich_durations(client, [track_a, track_b])

        # track_a's duration stays 0 (exception was swallowed)
        assert track_a.duration_sec == 0.0
        # track_b got its duration filled
        assert track_b.duration_sec == pytest.approx(180.0)

    def test_progress_cb_called_for_each_track(self):
        from scripts.lastfm_discovery import _enrich_durations

        tracks = [self._make_track(f"Song {i}", "Artist") for i in range(3)]
        client = self._make_client()
        client.get_track_info.return_value = _track_info_response(200_000)["track"]

        calls: list[tuple] = []

        def on_progress(current, total, label):
            calls.append((current, total))

        with patch("time.sleep"):
            _enrich_durations(client, tracks, progress_cb=on_progress)

        assert len(calls) == 3
        assert calls[0] == (1, 3)
        assert calls[2] == (3, 3)

    def test_sleep_called_between_tracks(self):
        from scripts.lastfm_discovery import _enrich_durations, CALL_DELAY

        tracks = [self._make_track("Song A"), self._make_track("Song B")]
        client = self._make_client()
        client.get_track_info.return_value = _track_info_response(200_000)["track"]

        with patch("time.sleep") as mock_sleep:
            _enrich_durations(client, tracks)

        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(CALL_DELAY)

    def test_toptags_missing_gracefully(self):
        from scripts.lastfm_discovery import _enrich_durations

        track = self._make_track()
        client = self._make_client()
        client.get_track_info.return_value = {"name": "Song", "duration": "200000"}

        with patch("time.sleep"):
            _enrich_durations(client, [track])

        assert track.tags == []
