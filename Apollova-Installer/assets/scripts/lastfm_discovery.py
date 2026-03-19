"""
lastfm_discovery.py
Fetches track lists from Last.fm charts.
Replaces spotify_discovery.py — no Premium subscription required.

API docs: https://www.last.fm/api
Credentials: Free API key from https://www.last.fm/api/account/create
"""

import os
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
import requests
from dotenv import load_dotenv

# Load .env from install root (scripts/ -> assets/ -> install root)
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

BASE_URL   = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "Apollova/1.0 (lyric video generator; contact@apollova.co.uk)"

# Delay between API calls — keeps us well under the 5 req/sec rate limit
CALL_DELAY = 0.25   # seconds

# Available chart sources shown in the GUI dropdown
CHART_SOURCES = {
    "Global Top 100":         {"method": "chart",  "param": None},
    "United Kingdom":         {"method": "geo",    "param": "United Kingdom"},
    "United States":          {"method": "geo",    "param": "United States"},
    "Australia":              {"method": "geo",    "param": "Australia"},
    "Genre — Pop":            {"method": "tag",    "param": "pop"},
    "Genre — Hip-Hop":        {"method": "tag",    "param": "hip-hop"},
    "Genre — R&B":            {"method": "tag",    "param": "r-n-b"},
    "Genre — Dance":          {"method": "tag",    "param": "dance"},
}

# Default duration to assume if track.getInfo returns 0 (in seconds)
FALLBACK_DURATION_SEC = 210   # 3:30 — average pop song


# ─── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class LastFMTrack:
    title: str
    artist: str
    duration_sec: float        # 0 if unavailable from API
    listeners: int             # total unique listeners on Last.fm
    playcount: int             # total scrobbles on Last.fm
    lastfm_url: str
    tags: list[str] = field(default_factory=list)

    @property
    def duration_sec_safe(self) -> float:
        """Returns duration, substituting fallback if 0."""
        return self.duration_sec if self.duration_sec > 0 else FALLBACK_DURATION_SEC

    @property
    def search_query(self) -> str:
        return f"{self.artist} {self.title}"

    @property
    def db_title(self) -> str:
        """Formatted as 'Artist - Title' for songs.db song_title column."""
        return f"{self.artist} - {self.title}"


# ─── API Client ───────────────────────────────────────────────────────────────

class LastFMClient:
    """
    Thin wrapper around the Last.fm REST API.
    Uses requests directly — no third-party Last.fm library needed.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, params: dict, retries: int = 3) -> dict:
        """
        Make a GET request to the Last.fm API.
        Retries on network errors with exponential backoff.
        Raises on persistent failure or API error responses.
        """
        params["api_key"] = self.api_key
        params["format"]  = "json"

        for attempt in range(retries):
            try:
                resp = self.session.get(BASE_URL, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                # Last.fm returns errors as JSON with an 'error' key
                if "error" in data:
                    code = data.get("error")
                    msg  = data.get("message", "Unknown Last.fm error")
                    # Error 29 = rate limit exceeded
                    if code == 29:
                        wait = 5 * (attempt + 1)
                        logger.warning(f"Last.fm rate limit hit. Waiting {wait}s...")
                        time.sleep(wait)
                        continue
                    raise ValueError(f"Last.fm API error {code}: {msg}")

                return data

            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Request failed (attempt {attempt+1}): {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Last.fm request failed after {retries} attempts")

    def get_top_tracks_global(self, limit: int = 50, page: int = 1) -> list[dict]:
        """Fetch global chart top tracks."""
        data = self._get({
            "method": "chart.getTopTracks",
            "limit":  limit,
            "page":   page,
        })
        return data.get("tracks", {}).get("track", [])

    def get_top_tracks_by_country(self, country: str, limit: int = 50, page: int = 1) -> list[dict]:
        """Fetch top tracks for a specific country."""
        data = self._get({
            "method":  "geo.getTopTracks",
            "country": country,
            "limit":   limit,
            "page":    page,
        })
        return data.get("tracks", {}).get("track", [])

    def get_top_tracks_by_tag(self, tag: str, limit: int = 50, page: int = 1) -> list[dict]:
        """Fetch top tracks for a genre tag."""
        data = self._get({
            "method": "tag.getTopTracks",
            "tag":    tag,
            "limit":  limit,
            "page":   page,
        })
        return data.get("tracks", {}).get("track", [])

    def get_track_info(self, artist: str, title: str) -> Optional[dict]:
        """
        Fetch detailed track info including duration.
        Returns None if the track is not found (Last.fm error 6).
        autocorrect=1 silently fixes minor misspellings.
        """
        try:
            data = self._get({
                "method":      "track.getInfo",
                "artist":      artist,
                "track":       title,
                "autocorrect": "1",
            })
            return data.get("track")
        except ValueError as e:
            if "error 6" in str(e).lower() or "not found" in str(e).lower():
                return None
            raise


# ─── Public Interface ─────────────────────────────────────────────────────────

def get_api_key() -> str:
    """
    Load Last.fm API key from .env.
    Raises ValueError with a helpful message if not set.
    """
    key = os.getenv("LASTFM_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "LASTFM_API_KEY is not set in .env\n"
            "Get a free key at: https://www.last.fm/api/account/create\n"
            "Then add LASTFM_API_KEY=yourkey to your .env file"
        )
    return key


def test_connection() -> tuple[bool, str]:
    """
    Test the Last.fm API connection.
    Returns (success: bool, message: str).
    Used by the Settings tab "Test Connection" button.
    """
    try:
        key = get_api_key()
        client = LastFMClient(key)
        # Fetch just 1 track to verify credentials work
        tracks = client.get_top_tracks_global(limit=1)
        if tracks:
            return True, "Connected"
        return False, "API responded but returned no tracks"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_tracks(
    source_name: str,
    limit: int = 100,
    fetch_durations: bool = True,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[LastFMTrack]:
    """
    Fetch tracks from a named chart source.

    Args:
        source_name:     Key from CHART_SOURCES dict, e.g. "Global Top 100"
        limit:           Number of tracks to fetch
        fetch_durations: If True, calls track.getInfo for each song to get duration.
        progress_cb:     Optional callback(current, total, song_title)

    Returns:
        List of LastFMTrack objects sorted by chart position (index 0 = #1).
    """
    if source_name not in CHART_SOURCES:
        raise ValueError(f"Unknown source '{source_name}'. Valid sources: {list(CHART_SOURCES)}")

    key = get_api_key()
    client = LastFMClient(key)
    config = CHART_SOURCES[source_name]

    # ── Fetch raw chart data ──────────────────────────────────────────────────
    raw_tracks = []
    page = 1

    while len(raw_tracks) < limit:
        remaining = limit - len(raw_tracks)
        batch_size = min(remaining, 50)

        if config["method"] == "chart":
            batch = client.get_top_tracks_global(limit=batch_size, page=page)
        elif config["method"] == "geo":
            batch = client.get_top_tracks_by_country(
                config["param"], limit=batch_size, page=page
            )
        elif config["method"] == "tag":
            batch = client.get_top_tracks_by_tag(
                config["param"], limit=batch_size, page=page
            )
        else:
            raise ValueError(f"Unknown method: {config['method']}")

        if not batch:
            break   # No more results

        raw_tracks.extend(batch)
        page += 1
        time.sleep(CALL_DELAY)

    # ── Parse raw tracks into LastFMTrack objects ─────────────────────────────
    tracks = []
    total = len(raw_tracks)

    for i, raw in enumerate(raw_tracks):
        title  = raw.get("name", "").strip()
        artist = raw.get("artist", {})
        if isinstance(artist, dict):
            artist_name = artist.get("name", "").strip()
        else:
            artist_name = str(artist).strip()

        if not title or not artist_name:
            continue

        listeners = int(raw.get("listeners", 0) or 0)
        playcount = int(raw.get("playcount", 0) or 0)
        url       = raw.get("url", "")

        track = LastFMTrack(
            title=title,
            artist=artist_name,
            duration_sec=0.0,    # filled in below if fetch_durations=True
            listeners=listeners,
            playcount=playcount,
            lastfm_url=url,
        )
        tracks.append(track)

        if progress_cb:
            progress_cb(i + 1, total, f"{artist_name} - {title}")

    # ── Optionally fetch durations via track.getInfo ──────────────────────────
    if fetch_durations:
        _enrich_durations(client, tracks, progress_cb)

    return tracks


def _enrich_durations(
    client: LastFMClient,
    tracks: list[LastFMTrack],
    progress_cb: Optional[Callable] = None,
) -> None:
    """
    Calls track.getInfo for each track to fill in duration_sec.
    Mutates tracks in place.

    Duration comes back as milliseconds in a string field ("duration": "354000").
    A value of "0" means Last.fm doesn't have this track's metadata — we leave
    duration_sec as 0 and the chorus detector's FALLBACK_DURATION_SEC handles it.
    """
    total = len(tracks)

    for i, track in enumerate(tracks):
        if progress_cb:
            progress_cb(i + 1, total, f"Getting duration: {track.artist} - {track.title}")

        try:
            info = client.get_track_info(track.artist, track.title)
            if info:
                duration_ms = int(info.get("duration", 0) or 0)
                track.duration_sec = duration_ms / 1000.0

                # Also pull tags while we're here
                toptags = info.get("toptags", {}).get("tag", [])
                track.tags = [t["name"] for t in toptags[:5] if isinstance(t, dict)]

        except Exception as e:
            logger.debug(f"Could not get duration for {track.title}: {e}")

        time.sleep(CALL_DELAY)
