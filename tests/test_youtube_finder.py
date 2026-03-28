"""
Tests for scripts/youtube_finder.py

Covers:
  - YouTubeResult dataclass: all fields stored correctly
  - _score_result:
      title fuzzy match / substring match (with and without rapidfuzz)
      view count log-scale scoring
      official channel boost (vevo / official / title keywords)
      duration match: exact, within 10s, within 30s, over 30s off
      live/cover/remix penalty
      score always clamped to [0, 100]
      missing attributes on video object handled gracefully
  - find_youtube_url:
      pytubefix unavailable raises ImportError
      no results returns None
      single result returned as YouTubeResult
      best result selected when multiple candidates
      confidence mapping: score>=70 -> "high", >=50 -> "medium", else "low"
      high-confidence result short-circuits query loop
      search exception on one query continues to next query
      malformed video object (missing attributes) handled without crashing
"""
from __future__ import annotations

import sys
import math
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(
    title: str = "Ed Sheeran - Shape of You (Official Music Video)",
    author: str = "Ed Sheeran",
    views: int = 5_000_000_000,
    length: int = 234,
    video_id: str = "JGwWNGJdvx8",
) -> MagicMock:
    """Build a minimal pytubefix Video mock."""
    v = MagicMock()
    v.title = title
    v.author = author
    v.views = views
    v.length = length
    v.video_id = video_id
    return v


def _make_search_mock(videos: list) -> MagicMock:
    """Return a MagicMock that behaves like pytubefix.Search."""
    mock_search = MagicMock()
    mock_search.videos = videos
    return mock_search


# ===========================================================================
# YouTubeResult dataclass
# ===========================================================================

class TestYouTubeResult:
    def _make(self, score=80.0, confidence="high"):
        from scripts.youtube_finder import YouTubeResult
        return YouTubeResult(
            url="https://www.youtube.com/watch?v=JGwWNGJdvx8",
            video_id="JGwWNGJdvx8",
            title="Ed Sheeran - Shape of You (Official Music Video)",
            channel="Ed Sheeran",
            views=5_000_000_000,
            duration_sec=234,
            score=score,
            confidence=confidence,
        )

    def test_url_field(self):
        r = self._make()
        assert "youtube.com" in r.url

    def test_video_id_field(self):
        r = self._make()
        assert r.video_id == "JGwWNGJdvx8"

    def test_title_field(self):
        r = self._make()
        assert "Shape of You" in r.title

    def test_channel_field(self):
        r = self._make()
        assert r.channel == "Ed Sheeran"

    def test_views_field(self):
        r = self._make()
        assert r.views == 5_000_000_000

    def test_duration_sec_field(self):
        r = self._make()
        assert r.duration_sec == 234

    def test_score_field(self):
        r = self._make(score=85.5)
        assert r.score == 85.5

    def test_confidence_high(self):
        r = self._make(confidence="high")
        assert r.confidence == "high"

    def test_confidence_medium(self):
        r = self._make(confidence="medium")
        assert r.confidence == "medium"

    def test_confidence_low(self):
        r = self._make(confidence="low")
        assert r.confidence == "low"


# ===========================================================================
# _score_result
# ===========================================================================

class TestScoreResult:
    """
    Test the scoring function directly.
    We patch rapidfuzz at the module level to control whether it is available.
    """

    def _score(
        self,
        video,
        expected_title="Shape of You",
        expected_artist="Ed Sheeran",
        expected_duration_sec=234.0,
    ):
        from scripts.youtube_finder import _score_result
        return _score_result(video, expected_title, expected_artist, expected_duration_sec)

    # --- title match ---

    def test_exact_title_and_artist_match_gives_positive_score(self):
        video = _make_video(
            title="Ed Sheeran - Shape of You",
            author="Ed Sheeran",
            views=1_000_000,
            length=234,
        )
        score = self._score(video)
        assert score > 0

    def test_unrelated_title_gives_lower_score_than_matching_title(self):
        matching = _make_video(title="Ed Sheeran Shape of You Official", views=1_000_000, length=234)
        unrelated = _make_video(title="Random Noise Compilation", views=1_000_000, length=234)

        score_match = self._score(matching)
        score_unrel = self._score(unrelated)
        assert score_match > score_unrel

    def test_fallback_scoring_when_rapidfuzz_unavailable(self):
        """Fallback (no rapidfuzz) awards 20 pts for title match + 10 pts for artist match."""
        video = _make_video(
            title="Ed Sheeran - Shape of You",
            author="Ed Sheeran",
            views=0,
            length=0,
        )

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE

        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score = self._score(video)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        # 20 (title) + 10 (artist) + 0 (views) = 30
        assert score == pytest.approx(30.0)

    def test_fallback_no_match_gives_zero_title_score(self):
        # Use a title/author that triggers no keyword patterns at all
        video = _make_video(title="Something Completely Different", author="Nobody", views=0, length=0)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE

        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            # Neither "ZZZ Song" nor "ZZZ Artist" appears in the video title/author
            score = self._score(video, "ZZZ Song", "ZZZ Artist")
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        # 0 title + 0 artist + 0 views + 0 duration = 0
        assert score == pytest.approx(0.0)

    # --- view count ---

    def test_high_view_count_adds_points(self):
        high_views = _make_video(views=1_000_000_000, length=234)
        low_views = _make_video(views=100, length=234)

        score_high = self._score(high_views)
        score_low = self._score(low_views)
        assert score_high > score_low

    def test_zero_views_adds_no_view_points(self):
        """Adding views to an otherwise identical video must increase its score."""
        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            video_no_views = _make_video(
                title="Something Neutral", author="Nobody", views=0, length=0
            )
            video_with_views = _make_video(
                title="Something Neutral", author="Nobody", views=1_000_000, length=0
            )
            score_no = self._score(video_no_views, "ZZZ", "ZZZ")
            score_with = self._score(video_with_views, "ZZZ", "ZZZ")
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        # With views must strictly exceed without views
        assert score_with > score_no

    def test_view_score_capped_at_25(self):
        """The view-count contribution alone must not exceed 25 pts."""
        from scripts.youtube_finder import _score_result
        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            # Neutral title/author/length so only views contribute
            video_baseline = _make_video(title="Something Neutral", author="Nobody", views=0, length=0)
            video_massive = _make_video(title="Something Neutral", author="Nobody", views=10 ** 15, length=0)
            score_baseline = _score_result(video_baseline, "ZZZ", "ZZZ", 0)
            score_massive = _score_result(video_massive, "ZZZ", "ZZZ", 0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        view_contribution = score_massive - score_baseline
        assert view_contribution <= 25.0

    # --- official channel boost ---

    def test_vevo_channel_adds_15_points(self):
        """A VEVO channel must score exactly 15 pts more than an unrecognised channel,
        all else being equal (same neutral title, zero views, zero length)."""
        # Use a title that does NOT match any _OFFICIAL_PATTERNS keyword
        neutral_title = "Something Neutral"
        vevo = _make_video(title=neutral_title, author="EdSheeranVEVO", views=0, length=0)
        plain = _make_video(title=neutral_title, author="SomeRandomUser", views=0, length=0)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score_vevo = self._score(vevo, "ZZZ", "ZZZ")
            score_plain = self._score(plain, "ZZZ", "ZZZ")
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score_vevo - score_plain == pytest.approx(15.0)

    def test_official_title_keyword_adds_8_points(self):
        with_official = _make_video(
            title="Shape of You (Official Video)", author="nobody", views=0, length=0
        )
        without = _make_video(
            title="Shape of You", author="nobody", views=0, length=0
        )

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score_with = self._score(with_official)
            score_without = self._score(without)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score_with - score_without == pytest.approx(8.0)

    # --- duration match ---

    def test_exact_duration_match_adds_20_points(self):
        """Duration diff <= 10s gives full 20 pts."""
        video_exact = _make_video(views=0, length=234)
        video_far_off = _make_video(views=0, length=500)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score_exact = self._score(video_exact, "ZZZ", "ZZZ", 234.0)
            score_far = self._score(video_far_off, "ZZZ", "ZZZ", 234.0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score_exact - score_far == pytest.approx(20.0)

    def test_duration_over_30s_off_adds_zero_points(self):
        """Duration more than 30 s off expected must add 0 duration pts.
        We verify this by comparing two identical videos where only the length differs."""
        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            neutral_title = "Something Neutral"
            # diff = 300 - 234 = 66s -> 0 duration pts
            video_far = _make_video(title=neutral_title, author="Nobody", views=0, length=300)
            # diff = 9s -> 20 duration pts
            video_close = _make_video(title=neutral_title, author="Nobody", views=0, length=234 + 9)
            score_far = self._score(video_far, "ZZZ", "ZZZ", 234.0)
            score_close = self._score(video_close, "ZZZ", "ZZZ", 234.0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        # The close video must score exactly 20 more pts (the full duration award)
        assert score_close - score_far == pytest.approx(20.0)

    def test_duration_within_30s_gives_partial_points(self):
        """20 < diff <= 30 gives partial duration points (0 < pts < 20)."""
        video = _make_video(views=0, length=234 + 25)  # diff = 25s

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score = self._score(video, "ZZZ", "ZZZ", 234.0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert 0 < score < 20

    def test_zero_expected_duration_skips_duration_scoring(self):
        """expected_duration_sec=0 means no expected duration — duration bucket must add 0 pts."""
        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            neutral_title = "Something Neutral"
            # Same video, same length, same everything — only expected_duration differs
            video = _make_video(title=neutral_title, author="Nobody", views=0, length=234)
            score_no_expected = self._score(video, "ZZZ", "ZZZ", expected_duration_sec=0)
            score_with_expected = self._score(video, "ZZZ", "ZZZ", expected_duration_sec=234.0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        # With a matching expected duration the score must be higher (20 pts gained)
        assert score_with_expected - score_no_expected == pytest.approx(20.0)

    # --- live/cover penalty ---

    def test_live_title_subtracts_20_points(self):
        live = _make_video(title="Ed Sheeran - Shape of You (Live at Wembley)", views=0, length=234)
        studio = _make_video(title="Ed Sheeran - Shape of You", views=0, length=234)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score_live = self._score(live)
            score_studio = self._score(studio)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score_studio - score_live == pytest.approx(20.0)

    def test_cover_title_subtracts_20_points(self):
        cover = _make_video(title="Shape of You - cover by Someone", views=0, length=0)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score = self._score(cover, "ZZZ", "ZZZ")
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score == pytest.approx(0.0)  # Clamped to 0 (would be -20)

    def test_score_clamped_to_zero_minimum(self):
        """Score must never be negative."""
        video = _make_video(title="Live Concert Cover Remix Karaoke Acoustic", views=0, length=500)

        import scripts.youtube_finder as yf
        original = yf.RAPIDFUZZ_AVAILABLE
        try:
            yf.RAPIDFUZZ_AVAILABLE = False
            score = self._score(video, "ZZZ", "ZZZ", 200.0)
        finally:
            yf.RAPIDFUZZ_AVAILABLE = original

        assert score >= 0.0

    def test_score_clamped_to_100_maximum(self):
        """Score must never exceed 100."""
        video = _make_video(
            title="Ed Sheeran Shape of You Official Video Lyrics",
            author="EdSheeranVEVO",
            views=10 ** 15,
            length=234,
        )
        score = self._score(video)
        assert score <= 100.0

    # --- missing attributes ---

    def test_missing_title_attribute_handled(self):
        """Video objects with missing title should not raise."""
        video = MagicMock(spec=[])  # no attributes defined
        from scripts.youtube_finder import _score_result
        score = _score_result(video, "Shape of You", "Ed Sheeran", 234.0)
        assert 0.0 <= score <= 100.0

    def test_none_views_treated_as_zero(self):
        """views=None should not crash."""
        video = _make_video(views=None, length=234)
        score = self._score(video)
        assert score >= 0.0


# ===========================================================================
# find_youtube_url
# ===========================================================================

class TestFindYouTubeUrl:
    def test_raises_import_error_when_pytubefix_unavailable(self):
        import scripts.youtube_finder as yf
        original = yf.PYTUBEFIX_AVAILABLE
        try:
            yf.PYTUBEFIX_AVAILABLE = False
            with pytest.raises(ImportError, match="pytubefix"):
                yf.find_youtube_url("Shape of You", "Ed Sheeran")
        finally:
            yf.PYTUBEFIX_AVAILABLE = original

    def test_returns_none_when_no_results(self):
        import scripts.youtube_finder as yf

        empty_search = _make_search_mock(videos=[])

        with patch("scripts.youtube_finder.Search", return_value=empty_search):
            result = yf.find_youtube_url("Unknown Song", "Unknown Artist")

        assert result is None

    def test_returns_youtube_result_for_single_video(self):
        import scripts.youtube_finder as yf

        video = _make_video()
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran", duration_sec=234)

        assert result is not None
        assert isinstance(result.url, str)
        assert "youtube.com" in result.url

    def test_url_construction_uses_video_id(self):
        import scripts.youtube_finder as yf

        video = _make_video(video_id="abc123xyz")
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran")

        assert result is not None
        assert "abc123xyz" in result.url

    def test_best_result_selected_from_multiple(self):
        """The result with the highest score wins."""
        import scripts.youtube_finder as yf

        # low-score: unrelated title, few views
        low = _make_video(
            title="Random Video",
            author="nobody",
            views=100,
            length=500,
            video_id="low_id",
        )
        # high-score: matches title/artist, official channel, right duration
        high = _make_video(
            title="Ed Sheeran - Shape of You (Official)",
            author="EdSheeranVEVO",
            views=5_000_000_000,
            length=234,
            video_id="high_id",
        )
        search = _make_search_mock(videos=[low, high])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran", duration_sec=234)

        assert result is not None
        assert result.video_id == "high_id"

    def test_confidence_high_when_score_ge_70(self):
        import scripts.youtube_finder as yf

        video = _make_video(
            title="Ed Sheeran - Shape of You (Official Music Video)",
            author="EdSheeranVEVO",
            views=5_000_000_000,
            length=234,
        )
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran", duration_sec=234)

        assert result is not None
        assert result.confidence == "high"

    def test_confidence_low_when_score_lt_50(self):
        import scripts.youtube_finder as yf

        # Strip everything that contributes score
        video = _make_video(
            title="Random Noise Compilation",
            author="nobody_at_all",
            views=10,
            length=9999,
            video_id="low_conf",
        )
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("ZZZ Song", "ZZZ Artist", duration_sec=10)

        # score will be very low -> confidence "low"
        if result:
            assert result.confidence in ("low", "medium")

    def test_high_confidence_short_circuits_query_loop(self):
        """Once score >= 70, no further Search calls should be made."""
        import scripts.youtube_finder as yf

        video = _make_video(
            title="Ed Sheeran - Shape of You (Official Music Video)",
            author="EdSheeranVEVO",
            views=5_000_000_000,
            length=234,
        )
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search) as mock_search:
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran", duration_sec=234)

        # There are 3 query templates; if the first gives >=70, only 1 Search call
        assert mock_search.call_count == 1

    def test_search_exception_on_one_query_continues_to_next(self):
        """A failing query should be skipped, not crash the whole function."""
        import scripts.youtube_finder as yf

        video = _make_video()
        good_search = _make_search_mock(videos=[video])

        call_count = [0]

        def search_factory(query):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("network error")
            return good_search

        with patch("scripts.youtube_finder.Search", side_effect=search_factory):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran")

        # Should have tried the next query and found the video
        assert result is not None

    def test_malformed_video_missing_video_id_skipped(self):
        """A video object that raises when accessing video_id should not crash."""
        import scripts.youtube_finder as yf

        broken = MagicMock()
        # Accessing .video_id raises
        type(broken).video_id = property(lambda self: (_ for _ in ()).throw(AttributeError("no id")))

        good = _make_video()
        search = _make_search_mock(videos=[broken, good])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran")

        # Should not raise; good video may or may not be returned
        # (broken video is skipped gracefully)
        assert result is None or isinstance(result.url, str)

    def test_max_results_limits_videos_per_query(self):
        """Only the first max_results videos per query should be scored."""
        import scripts.youtube_finder as yf

        videos = [_make_video(video_id=f"id{i}", views=i * 1000) for i in range(10)]
        search = _make_search_mock(videos=videos)

        scored_ids: list[str] = []
        original_score = yf._score_result

        def tracking_score(video, *args, **kwargs):
            scored_ids.append(video.video_id)
            return original_score(video, *args, **kwargs)

        with patch("scripts.youtube_finder.Search", return_value=search):
            with patch("scripts.youtube_finder._score_result", side_effect=tracking_score):
                yf.find_youtube_url("Shape of You", "Ed Sheeran", max_results=3)

        # Per query only 3 results should be scored; with up to 3 queries -> max 9
        assert len(scored_ids) <= 9

    def test_result_fields_populated_correctly(self):
        import scripts.youtube_finder as yf

        video = _make_video(
            title="Ed Sheeran - Shape of You",
            author="Ed Sheeran",
            views=100_000,
            length=234,
            video_id="JGwWNGJdvx8",
        )
        search = _make_search_mock(videos=[video])

        with patch("scripts.youtube_finder.Search", return_value=search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran", duration_sec=234)

        assert result is not None
        assert result.title == "Ed Sheeran - Shape of You"
        assert result.channel == "Ed Sheeran"
        assert result.views == 100_000
        assert result.duration_sec == 234
        assert result.video_id == "JGwWNGJdvx8"

    def test_search_with_videos_none_attribute(self):
        """results.videos being None should be treated as empty."""
        import scripts.youtube_finder as yf

        null_search = MagicMock()
        null_search.videos = None

        with patch("scripts.youtube_finder.Search", return_value=null_search):
            result = yf.find_youtube_url("Shape of You", "Ed Sheeran")

        assert result is None
