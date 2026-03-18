"""
conftest.py — Shared pytest fixtures for the Apollova test suite.

Provides:
  - Isolated temporary directories for every test.
  - Minimal WAV audio files synthesised with pydub (no network or real models).
  - Canned Genius API response payloads.
  - Whisper segment/result mock factories.
  - A real in-memory SongDatabase backed by a temp SQLite file.
  - Upload StateManager backed by a temp SQLite file.
"""
from __future__ import annotations

import json
import os
import sys
import struct
import wave
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Make the project root importable regardless of where pytest is invoked.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Directory helpers
# ===========================================================================

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Isolated temporary directory; auto-removed after each test."""
    return tmp_path


@pytest.fixture()
def job_folder(tmp_path: Path) -> Path:
    """A pre-created job folder inside the temp directory."""
    jf = tmp_path / "job_001"
    jf.mkdir()
    return jf


# ===========================================================================
# Audio helpers
# ===========================================================================

def _write_silent_wav(path: Path, duration_ms: int = 3000, sample_rate: int = 44100) -> Path:
    """Write a valid (silent) WAV file without external dependencies."""
    n_frames = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def _write_silent_mp3(path: Path, duration_ms: int = 3000) -> Path:
    """Write a minimal-enough MP3 stub using pydub so pydub can read it back."""
    from pydub import AudioSegment
    silence = AudioSegment.silent(duration=duration_ms)
    silence.export(str(path), format="mp3")
    return path


@pytest.fixture()
def silent_wav(job_folder: Path) -> Path:
    """3-second silent WAV file placed inside job_folder."""
    return _write_silent_wav(job_folder / "audio_trimmed.wav")


@pytest.fixture()
def silent_mp3(job_folder: Path) -> Path:
    """3-second silent MP3 file placed inside job_folder."""
    return _write_silent_mp3(job_folder / "audio_source.mp3")


@pytest.fixture()
def job_with_audio(job_folder: Path, silent_mp3: Path, silent_wav: Path) -> Path:
    """job_folder pre-populated with both audio_source.mp3 and audio_trimmed.wav."""
    return job_folder


# ===========================================================================
# Genius API mock helpers
# ===========================================================================

def _make_genius_hit(
    full_title: str = "Shape of You - Ed Sheeran",
    artist_name: str = "Ed Sheeran",
    song_url: str = "https://genius.com/Ed-sheeran-shape-of-you-lyrics",
    song_art_url: str = "https://images.genius.com/fake.jpg",
) -> dict:
    return {
        "result": {
            "full_title": full_title,
            "url": song_url,
            "song_art_image_url": song_art_url,
            "header_image_url": song_art_url,
            "song_art_image_thumbnail_url": song_art_url,
            "primary_artist": {"name": artist_name},
            "title": full_title.split(" - ")[-1] if " - " in full_title else full_title,
        }
    }


@pytest.fixture()
def genius_search_response() -> dict:
    """Canned Genius /search API response for 'Shape of You - Ed Sheeran'."""
    return {
        "response": {
            "hits": [_make_genius_hit()]
        }
    }


@pytest.fixture()
def genius_lyrics_html() -> str:
    """Minimal Genius-style HTML page containing a lyrics container."""
    return (
        '<html><body>'
        '<div data-lyrics-container="true">'
        'I\'m in love with the shape of you<br/>'
        'We push and pull like a magnet do<br/>'
        'Although my heart is falling too<br/>'
        '</div>'
        '</body></html>'
    )


SAMPLE_LYRICS = (
    "I'm in love with the shape of you\n"
    "We push and pull like a magnet do\n"
    "Although my heart is falling too\n"
    "I'm in love with your body\n"
)


# ===========================================================================
# Whisper / transcription mock helpers
# ===========================================================================

def _make_whisper_word(word: str, start: float, end: float) -> MagicMock:
    w = MagicMock()
    w.word = word
    w.start = start
    w.end = end
    return w


def _make_whisper_segment(
    text: str,
    start: float,
    end: float,
    words: list[tuple[str, float, float]] | None = None,
) -> MagicMock:
    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end
    if words:
        seg.words = [_make_whisper_word(w, s, e) for w, s, e in words]
    else:
        # Build uniform word timings automatically
        token_list = text.split()
        if token_list:
            dur = end - start
            wd = dur / len(token_list)
            seg.words = [
                _make_whisper_word(tok, start + i * wd, start + (i + 1) * wd)
                for i, tok in enumerate(token_list)
            ]
        else:
            seg.words = []
    return seg


def _make_whisper_result(segments_data: list[dict]) -> MagicMock:
    """
    Build a fake stable_whisper result object.

    Each entry in segments_data: {"text": str, "start": float, "end": float}
    """
    result = MagicMock()
    result.segments = [
        _make_whisper_segment(d["text"], d["start"], d["end"])
        for d in segments_data
    ]
    return result


@pytest.fixture()
def sample_whisper_result() -> MagicMock:
    """A realistic 4-segment Whisper result for 'Shape of You'."""
    return _make_whisper_result([
        {"text": "I'm in love with the shape of you", "start": 0.5,  "end": 3.2},
        {"text": "We push and pull like a magnet do",  "start": 3.4,  "end": 6.1},
        {"text": "Although my heart is falling too",   "start": 6.3,  "end": 8.8},
        {"text": "I'm in love with your body",          "start": 9.0,  "end": 11.5},
    ])


# Aurora-format segments (lyric_current key)
@pytest.fixture()
def aurora_segments() -> list[dict]:
    return [
        {"t": 0.5,  "end_time": 3.2,  "lyric_prev": "", "lyric_current": "Im in love with the shape of you",  "lyric_next1": "", "lyric_next2": ""},
        {"t": 3.4,  "end_time": 6.1,  "lyric_prev": "", "lyric_current": "We push and pull like a magnet do", "lyric_next1": "", "lyric_next2": ""},
        {"t": 6.3,  "end_time": 8.8,  "lyric_prev": "", "lyric_current": "Although my heart is falling too",  "lyric_next1": "", "lyric_next2": ""},
        {"t": 9.0,  "end_time": 11.5, "lyric_prev": "", "lyric_current": "Im in love with your body",          "lyric_next1": "", "lyric_next2": ""},
    ]


# Mono/Onyx-format markers (text key, words array)
@pytest.fixture()
def mono_markers() -> list[dict]:
    return [
        {
            "time": 0.5, "end_time": 3.2, "text": "I'm in love with the shape of you",
            "words": [
                {"word": "I'm",    "start": 0.5,  "end": 0.9},
                {"word": "in",     "start": 0.9,  "end": 1.2},
                {"word": "love",   "start": 1.2,  "end": 1.6},
                {"word": "with",   "start": 1.6,  "end": 1.9},
                {"word": "the",    "start": 1.9,  "end": 2.1},
                {"word": "shape",  "start": 2.1,  "end": 2.5},
                {"word": "of",     "start": 2.5,  "end": 2.7},
                {"word": "you",    "start": 2.7,  "end": 3.2},
            ],
            "color": "white",
        },
        {
            "time": 3.4, "end_time": 6.1, "text": "We push and pull like a magnet do",
            "words": [
                {"word": "We",     "start": 3.4,  "end": 3.7},
                {"word": "push",   "start": 3.7,  "end": 4.0},
                {"word": "and",    "start": 4.0,  "end": 4.2},
                {"word": "pull",   "start": 4.2,  "end": 4.6},
                {"word": "like",   "start": 4.6,  "end": 4.9},
                {"word": "a",      "start": 4.9,  "end": 5.0},
                {"word": "magnet", "start": 5.0,  "end": 5.5},
                {"word": "do",     "start": 5.5,  "end": 6.1},
            ],
            "color": "black",
        },
    ]


# ===========================================================================
# Song Database fixture
# ===========================================================================

@pytest.fixture()
def song_db(tmp_path: Path):
    """Isolated SongDatabase backed by a temp SQLite file."""
    from scripts.song_database import SongDatabase
    db_path = str(tmp_path / "test_songs.db")
    return SongDatabase(db_path=db_path)


@pytest.fixture()
def populated_song_db(song_db):
    """SongDatabase with one pre-existing song."""
    song_db.add_song(
        song_title="Ed Sheeran - Shape of You",
        youtube_url="https://www.youtube.com/watch?v=JGwWNGJdvx8",
        start_time="01:00",
        end_time="02:00",
        genius_image_url="https://images.genius.com/fake.jpg",
        transcribed_lyrics=[{"t": 0.5, "lyric_current": "I'm in love"}],
        colors=["#ff5733", "#33ff57"],
        beats=[0.5, 1.0, 1.5],
    )
    return song_db


# ===========================================================================
# Upload StateManager fixture
# ===========================================================================

@pytest.fixture()
def upload_state(tmp_path: Path):
    """Isolated upload StateManager backed by a temp SQLite file."""
    # Import here — upload/ uses its own module layout
    sys.path.insert(0, str(PROJECT_ROOT / "upload"))
    from upload_state import StateManager
    return StateManager(db_path=str(tmp_path / "upload_state.db"))


def _make_result_with_n_segments(n: int, valid: bool = True) -> MagicMock:
    """Build a fake Whisper result with *n* segments.

    If *valid* is True, each segment has >1 char text; otherwise text is empty.
    """
    segments_data = []
    for i in range(n):
        text = f"word{i} another" if valid else ""
        segments_data.append({"text": text, "start": float(i * 3), "end": float(i * 3 + 2.5)})
    return _make_whisper_result(segments_data)


def _write_wav_with_volume(path: Path, duration_ms: int = 3000,
                           loud_ranges: list[tuple[int, int]] | None = None,
                           sample_rate: int = 44100, amplitude: int = 20000) -> Path:
    """Write a WAV where specified ranges are loud and the rest is silent.

    *loud_ranges*: list of (start_ms, end_ms) that should be loud.
    Everything else is silence.
    """
    n_frames = int(sample_rate * duration_ms / 1000)
    if loud_ranges is None:
        loud_ranges = []

    samples = bytearray(n_frames * 2)  # 16-bit mono
    for start_ms, end_ms in loud_ranges:
        start_frame = int(sample_rate * start_ms / 1000)
        end_frame = min(int(sample_rate * end_ms / 1000), n_frames)
        for f in range(start_frame, end_frame):
            # Simple square wave
            val = amplitude if (f % 100) < 50 else -amplitude
            struct.pack_into("<h", samples, f * 2, val)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(samples))
    return path


@pytest.fixture()
def upload_config(tmp_path: Path):
    """Minimal upload Config with no real credentials."""
    sys.path.insert(0, str(PROJECT_ROOT / "upload"))
    from config import Config
    return Config(
        gate_password="test_secret",
        apollova_root=str(tmp_path),
        state_db_path=str(tmp_path / "data" / "upload_state.db"),
        log_dir=str(tmp_path / "logs"),
        file_stable_wait=0.0,
        file_stable_extra_wait=0.0,
        file_stable_checks=1,
    )
