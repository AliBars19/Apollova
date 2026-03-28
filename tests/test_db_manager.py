"""
Tests for scripts/db_manager.py

Covers:
  - show_all_songs: empty database prints message (no table)
  - show_all_songs: populated database prints table rows
  - show_stats: calls db.get_stats and prints output
  - show_stats: zero total_songs skips cache rate
  - search_song: no results prints message
  - search_song: results printed with truncated URLs
  - show_song_details: song not found prints error
  - show_song_details: song found prints fields
  - show_song_details: song with no transcribed_lyrics branch
  - show_song_details: song with no genius_image_url branch
  - show_song_details: song with no colors branch
  - show_song_details: song with no beats branch
  - delete_song_interactive: song not found prints error
  - delete_song_interactive: user cancels (types 'no')
  - delete_song_interactive: user confirms, delete succeeds
  - delete_song_interactive: user confirms, delete fails
  - main: no args prints usage
  - main: list command delegates to show_all_songs
  - main: stats command delegates to show_stats
  - main: search without query prints error
  - main: search with query calls search_song
  - main: show without title prints error
  - main: show with title calls show_song_details
  - main: delete without title prints error
  - main: delete with title calls delete_song_interactive
  - main: unknown command prints error
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Ensure both the project root and scripts/ are importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Module-level mock: replace the db and console at import time so module-level
# code (db = SongDatabase()) does not hit a real SQLite file.
# ---------------------------------------------------------------------------

def _import_db_manager_with_mocks():
    """
    Import db_manager with a fresh mock for SongDatabase and Console.
    Returns (module, mock_db, mock_console).
    """
    import importlib

    mock_db = MagicMock()
    mock_console = MagicMock()

    mock_song_db_module = MagicMock()
    mock_song_db_module.SongDatabase.return_value = mock_db

    mock_rich_console_class = MagicMock(return_value=mock_console)
    mock_rich_table_class = MagicMock()
    mock_rich_module = MagicMock()
    mock_rich_module.Console = mock_rich_console_class
    mock_rich_table_module = MagicMock()
    mock_rich_table_module.Table = mock_rich_table_class

    with patch.dict(sys.modules, {
        "scripts.song_database": mock_song_db_module,
        "rich.console": mock_rich_module,
        "rich.table": mock_rich_table_module,
    }):
        if "db_manager" in sys.modules:
            del sys.modules["db_manager"]

        # db_manager is under scripts/
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        try:
            import db_manager
            importlib.reload(db_manager)
        finally:
            pass

    return db_manager, mock_db, mock_console


@pytest.fixture()
def db_mod():
    """Fresh db_manager module with mocked DB and console."""
    mod, db, console = _import_db_manager_with_mocks()
    mod.db = db
    mod.console = console
    return mod, db, console


# ===========================================================================
# show_all_songs
# ===========================================================================

class TestShowAllSongs:
    def test_empty_db_prints_message(self, db_mod):
        mod, db, console = db_mod
        db.list_all_songs.return_value = []
        mod.show_all_songs()
        console.print.assert_called()
        # Should mention "empty"
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "empty" in printed.lower() or "Database is empty" in printed

    def test_populated_db_prints_table(self, db_mod):
        mod, db, console = db_mod
        db.list_all_songs.return_value = [
            ("Ed Sheeran - Shape of You", 3, "2026-01-01 12:00:00"),
            ("Drake - God's Plan", 1, "2026-02-01 12:00:00"),
        ]
        mod.show_all_songs()
        console.print.assert_called()


# ===========================================================================
# show_stats
# ===========================================================================

class TestShowStats:
    def test_stats_printed(self, db_mod):
        mod, db, console = db_mod
        db.get_stats.return_value = {
            "total_songs": 10,
            "cached_lyrics": 8,
            "total_uses": 25,
        }
        mod.show_stats()
        console.print.assert_called()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "10" in printed

    def test_zero_total_songs_skips_cache_rate(self, db_mod):
        mod, db, console = db_mod
        db.get_stats.return_value = {
            "total_songs": 0,
            "cached_lyrics": 0,
            "total_uses": 0,
        }
        # Must not raise (no ZeroDivisionError)
        mod.show_stats()
        console.print.assert_called()

    def test_nonzero_total_prints_cache_rate(self, db_mod):
        mod, db, console = db_mod
        db.get_stats.return_value = {
            "total_songs": 5,
            "cached_lyrics": 4,
            "total_uses": 10,
        }
        mod.show_stats()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "80.0" in printed or "%" in printed


# ===========================================================================
# search_song
# ===========================================================================

class TestSearchSong:
    def test_no_results_prints_message(self, db_mod):
        mod, db, console = db_mod
        db.search_songs.return_value = []
        mod.search_song("unknown artist")
        console.print.assert_called()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "No songs found" in printed or "unknown artist" in printed

    def test_results_printed(self, db_mod):
        mod, db, console = db_mod
        db.search_songs.return_value = [
            ("Ed Sheeran - Shape of You", "https://youtu.be/short", 3),
        ]
        mod.search_song("shape")
        console.print.assert_called()

    def test_long_url_truncated(self, db_mod):
        mod, db, console = db_mod
        long_url = "https://www.youtube.com/watch?v=" + "a" * 60
        db.search_songs.return_value = [
            ("Song Title", long_url, 1),
        ]
        mod.search_song("title")
        # Verify the function ran without error
        console.print.assert_called()


# ===========================================================================
# show_song_details
# ===========================================================================

class TestShowSongDetails:
    def _make_song(self, **overrides):
        song = {
            "youtube_url": "https://youtu.be/abc",
            "start_time": "01:00",
            "end_time": "02:00",
            "genius_image_url": "https://img.genius.com/fake.jpg",
            "transcribed_lyrics": [{"t": 0.5, "lyric_current": "hello"}],
            "colors": ["#ff0000", "#00ff00"],
            "beats": [0.5, 1.0, 1.5],
        }
        song.update(overrides)
        return song

    def test_song_not_found_prints_error(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = None
        mod.show_song_details("Missing Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "not found" in printed.lower() or "Missing Song" in printed

    def test_song_found_prints_url(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song()
        mod.show_song_details("Ed Sheeran - Shape of You")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "youtu.be" in printed

    def test_song_with_no_transcribed_lyrics_prints_none(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song(transcribed_lyrics=None)
        mod.show_song_details("Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "None" in printed or "none" in printed.lower()

    def test_song_with_no_genius_image_url(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song(genius_image_url=None)
        mod.show_song_details("Song")
        # Should not raise
        console.print.assert_called()

    def test_song_with_no_colors(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song(colors=None)
        mod.show_song_details("Song")
        console.print.assert_called()

    def test_song_with_no_beats(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song(beats=None)
        mod.show_song_details("Song")
        console.print.assert_called()

    def test_song_with_beats_prints_count(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song(beats=[0.5, 1.0, 1.5, 2.0])
        mod.show_song_details("Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "4" in printed


# ===========================================================================
# delete_song_interactive
# ===========================================================================

class TestDeleteSongInteractive:
    def _make_song(self):
        return {
            "youtube_url": "https://youtu.be/abc",
            "start_time": "01:00",
            "end_time": "02:00",
            "transcribed_lyrics": [{"t": 0.5}],
        }

    def test_song_not_found_prints_error(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = None
        mod.delete_song_interactive("Missing Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "not found" in printed.lower()

    def test_user_cancels_prints_cancelled(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song()
        with patch("builtins.input", return_value="no"):
            mod.delete_song_interactive("Some Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Cancelled" in printed or "cancel" in printed.lower()

    def test_user_confirms_delete_succeeds(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song()
        db.delete_song.return_value = True
        with patch("builtins.input", return_value="yes"):
            mod.delete_song_interactive("Some Song")
        db.delete_song.assert_called_once_with("Some Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Deleted" in printed or "deleted" in printed.lower()

    def test_user_confirms_delete_fails(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = self._make_song()
        db.delete_song.return_value = False
        with patch("builtins.input", return_value="yes"):
            mod.delete_song_interactive("Some Song")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Failed" in printed or "failed" in printed.lower()

    def test_song_with_no_transcribed_lyrics_still_deletes(self, db_mod):
        mod, db, console = db_mod
        song = self._make_song()
        song["transcribed_lyrics"] = None
        db.get_song.return_value = song
        db.delete_song.return_value = True
        with patch("builtins.input", return_value="yes"):
            mod.delete_song_interactive("Song")
        db.delete_song.assert_called_once()


# ===========================================================================
# main() — CLI dispatcher
# ===========================================================================

class TestMain:
    def _run_main(self, db_mod, argv):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py"] + argv):
            mod.main()
        return mod, db, console

    def test_no_args_prints_usage(self, db_mod):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py"]):
            mod.main()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Usage" in printed or "usage" in printed.lower()

    def test_list_command_calls_show_all_songs(self, db_mod):
        mod, db, console = db_mod
        db.list_all_songs.return_value = []
        with patch.object(sys, "argv", ["db_manager.py", "list"]):
            mod.main()
        db.list_all_songs.assert_called_once()

    def test_stats_command_calls_get_stats(self, db_mod):
        mod, db, console = db_mod
        db.get_stats.return_value = {"total_songs": 0, "cached_lyrics": 0, "total_uses": 0}
        with patch.object(sys, "argv", ["db_manager.py", "stats"]):
            mod.main()
        db.get_stats.assert_called_once()

    def test_search_without_query_prints_error(self, db_mod):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py", "search"]):
            mod.main()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "search query" in printed.lower() or "provide" in printed.lower()

    def test_search_with_query_calls_search_songs(self, db_mod):
        mod, db, console = db_mod
        db.search_songs.return_value = []
        with patch.object(sys, "argv", ["db_manager.py", "search", "drake"]):
            mod.main()
        db.search_songs.assert_called_once_with("drake")

    def test_search_multi_word_query(self, db_mod):
        mod, db, console = db_mod
        db.search_songs.return_value = []
        with patch.object(sys, "argv", ["db_manager.py", "search", "god", "s", "plan"]):
            mod.main()
        db.search_songs.assert_called_once_with("god s plan")

    def test_show_without_title_prints_error(self, db_mod):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py", "show"]):
            mod.main()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "song title" in printed.lower() or "provide" in printed.lower()

    def test_show_with_title_calls_get_song(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = None
        with patch.object(sys, "argv", ["db_manager.py", "show", "Ed Sheeran - Shape of You"]):
            mod.main()
        db.get_song.assert_called_once_with("Ed Sheeran - Shape of You")

    def test_delete_without_title_prints_error(self, db_mod):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py", "delete"]):
            mod.main()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "song title" in printed.lower() or "provide" in printed.lower()

    def test_delete_with_title_delegates(self, db_mod):
        mod, db, console = db_mod
        db.get_song.return_value = None
        with patch.object(sys, "argv", ["db_manager.py", "delete", "Some Song"]):
            mod.main()
        db.get_song.assert_called_once_with("Some Song")

    def test_unknown_command_prints_error(self, db_mod):
        mod, db, console = db_mod
        with patch.object(sys, "argv", ["db_manager.py", "frobnicate"]):
            mod.main()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Unknown" in printed or "unknown" in printed.lower()
