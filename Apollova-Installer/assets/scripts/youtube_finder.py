"""
youtube_finder.py
Finds YouTube URLs for songs using pytubefix search.
Scores results for quality and confidence.
"""

import re
import math
import logging
from dataclasses import dataclass
from typing import Optional

try:
    from pytubefix import Search
    PYTUBEFIX_AVAILABLE = True
except ImportError:
    PYTUBEFIX_AVAILABLE = False

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

logger = logging.getLogger(__name__)

# Patterns that strongly suggest wrong video type
_LIVE_PATTERNS = re.compile(
    r'\b(live|concert|tour|festival|perform|acoustic|cover|remix|karaoke|instrumental)\b',
    re.IGNORECASE
)

# Patterns that boost confidence (official sources)
_OFFICIAL_PATTERNS = re.compile(
    r'\b(official|vevo|lyrics|audio|video)\b',
    re.IGNORECASE
)


@dataclass
class YouTubeResult:
    url: str
    video_id: str
    title: str
    channel: str
    views: int
    duration_sec: int
    score: float             # 0-100
    confidence: str          # "high", "medium", "low"


def _score_result(
    video,
    expected_title: str,
    expected_artist: str,
    expected_duration_sec: float
) -> float:
    score = 0.0

    title = getattr(video, 'title', '') or ''
    channel = getattr(video, 'author', '') or ''
    views = getattr(video, 'views', 0) or 0
    duration = getattr(video, 'length', 0) or 0

    # 1. Title fuzzy match (35 pts)
    if RAPIDFUZZ_AVAILABLE:
        target = f"{expected_artist} {expected_title}".lower()
        ratio = fuzz.token_set_ratio(title.lower(), target) / 100.0
        score += ratio * 35
    else:
        # Fallback: check if both artist and title appear in video title
        if expected_title.lower() in title.lower():
            score += 20
        if expected_artist.lower() in title.lower():
            score += 10

    # 2. View count score (25 pts)
    if views > 0:
        view_score = min(math.log10(max(views, 1)) / math.log10(1_000_000_000) * 25, 25)
        score += view_score

    # 3. Official channel boost (15 pts)
    channel_lower = channel.lower()
    title_lower = title.lower()
    if 'vevo' in channel_lower or 'official' in channel_lower:
        score += 15
    elif _OFFICIAL_PATTERNS.search(title_lower):
        score += 8

    # 4. Duration match (20 pts)
    if expected_duration_sec > 0 and duration > 0:
        diff = abs(duration - expected_duration_sec)
        if diff <= 10:
            score += 20
        elif diff <= 30:
            score += 20 * (1 - (diff - 10) / 20)
        # > 30s off = 0 pts

    # 5. Not live penalty
    if _LIVE_PATTERNS.search(title_lower):
        score -= 20

    return max(0.0, min(100.0, score))


def find_youtube_url(
    title: str,
    artist: str,
    duration_sec: float = 0,
    max_results: int = 5
) -> Optional[YouTubeResult]:
    """
    Search YouTube for a song, score all results, return the best.
    Returns None if no results found.
    """
    if not PYTUBEFIX_AVAILABLE:
        raise ImportError("pytubefix is not installed")

    queries = [
        f"{artist} {title} lyrics",
        f"{artist} {title} official",
        f"{artist} {title}",
    ]

    best: Optional[YouTubeResult] = None

    for query in queries:
        try:
            results = Search(query)
            videos = results.videos[:max_results] if results.videos else []
        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            continue

        for video in videos:
            try:
                score = _score_result(video, title, artist, duration_sec)
                vid_url = f"https://www.youtube.com/watch?v={video.video_id}"

                if best is None or score > best.score:
                    confidence = (
                        "high"   if score >= 70 else
                        "medium" if score >= 50 else
                        "low"
                    )
                    best = YouTubeResult(
                        url=vid_url,
                        video_id=video.video_id,
                        title=getattr(video, 'title', ''),
                        channel=getattr(video, 'author', ''),
                        views=getattr(video, 'views', 0) or 0,
                        duration_sec=getattr(video, 'length', 0) or 0,
                        score=score,
                        confidence=confidence,
                    )
            except Exception as e:
                logger.debug(f"Error scoring result: {e}")
                continue

        # If we already have a high-confidence result, don't bother
        # with fallback queries
        if best and best.score >= 70:
            break

    return best
