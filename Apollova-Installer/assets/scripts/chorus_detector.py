"""
chorus_detector.py
Detects the chorus/hook of a song using librosa's recurrence matrix.
No external API required — runs entirely on the local audio file.
"""

import logging
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

logger = logging.getLogger(__name__)

# Analysis parameters
_SR          = 11025   # Sample rate for analysis (low = fast, sufficient for structure)
_HOP_LENGTH  = 512     # Frames per hop
_N_STEPS     = 10      # Memory embedding steps
_DELAY       = 3       # Delay between embedded steps
_INTRO_SKIP  = 0.15    # Skip first 15% of song (intro avoidance)
_TARGET_DURATION = 60  # Desired clip length in seconds


@dataclass
class ChorusResult:
    start_sec: float
    end_sec: float
    confidence: float    # 0.0-1.0
    method: str          # "recurrence", "rms_fallback", or "heuristic"

    @property
    def start_mmss(self) -> str:
        return _sec_to_mmss(self.start_sec)

    @property
    def end_mmss(self) -> str:
        return _sec_to_mmss(self.end_sec)


def _sec_to_mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _snap_to_beat(time_sec: float, beat_times: np.ndarray) -> float:
    """Round time_sec to the nearest detected beat."""
    if len(beat_times) == 0:
        return time_sec
    idx = int(np.argmin(np.abs(beat_times - time_sec)))
    return float(beat_times[idx])


def detect_chorus(
    audio_path: str,
    target_duration: int = _TARGET_DURATION,
    intro_skip_ratio: float = _INTRO_SKIP,
) -> ChorusResult:
    """
    Detect the chorus/hook of a song from its audio file.

    Args:
        audio_path: Path to the audio file (mp3, wav, m4a etc.)
        target_duration: Desired clip length in seconds (default 60)
        intro_skip_ratio: Skip this fraction of the song from the start (default 0.15)

    Returns:
        ChorusResult with start/end times in seconds and MM:SS format
    """
    if not LIBROSA_AVAILABLE:
        raise ImportError("librosa is not installed")

    # --- Load audio ---
    y, sr = librosa.load(audio_path, sr=_SR, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    logger.info(f"Loaded {Path(audio_path).name}: {duration:.1f}s at {sr}Hz")

    # Minimum duration check
    if duration < 20:
        return _heuristic_fallback(duration, target_duration, "too_short")

    # --- Beat tracking ---
    # Run at normal sr for better beat accuracy, then use for snapping
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP_LENGTH)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=_HOP_LENGTH)

    # --- Chroma features ---
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=_HOP_LENGTH, bins_per_octave=36)

    # --- Memory embedding (time-delay embedding for noise reduction) ---
    chroma_stack = librosa.feature.stack_memory(
        chroma, n_steps=_N_STEPS, delay=_DELAY, mode='edge'
    )

    # --- Recurrence matrix ---
    # Affinity mode gives similarity values 0-1; cosine metric works well for chroma
    try:
        R = librosa.segment.recurrence_matrix(
            chroma_stack,
            mode='affinity',
            metric='cosine',
            sym=True,
        )
    except Exception as e:
        logger.warning(f"Recurrence matrix failed: {e}. Falling back to RMS method.")
        return _rms_fallback(y, sr, duration, target_duration, beat_times)

    # --- Row-sum score = how much does each frame repeat elsewhere? ---
    row_sums = np.array(R.sum(axis=1)).flatten()

    # Normalise
    if row_sums.max() > 0:
        row_sums = row_sums / row_sums.max()

    # --- RMS energy envelope ---
    rms = librosa.feature.rms(y=y, hop_length=_HOP_LENGTH)[0]
    # Align rms to row_sums length
    if len(rms) > len(row_sums):
        rms = rms[:len(row_sums)]
    elif len(rms) < len(row_sums):
        rms = np.pad(rms, (0, len(row_sums) - len(rms)))

    # Normalise RMS
    if rms.max() > 0:
        rms_norm = rms / rms.max()
    else:
        rms_norm = rms

    # --- Combined score ---
    # Recurrence score weighted 70%, energy 30%
    combined = 0.70 * row_sums + 0.30 * rms_norm

    # Smooth with a ~3 second window to avoid single-frame spikes
    smooth_frames = int(3.0 * sr / _HOP_LENGTH)
    kernel = np.ones(smooth_frames) / smooth_frames
    combined_smooth = np.convolve(combined, kernel, mode='same')

    # --- Apply intro skip ---
    skip_frames = int(intro_skip_ratio * len(combined_smooth))
    combined_smooth[:skip_frames] = 0.0

    # Also zero out last 15% (outro avoidance)
    outro_skip = int(0.85 * len(combined_smooth))
    combined_smooth[outro_skip:] = 0.0

    if combined_smooth.max() == 0:
        logger.warning("No usable region found after masking. Using RMS fallback.")
        return _rms_fallback(y, sr, duration, target_duration, beat_times)

    # --- Find peak ---
    peak_frame = int(np.argmax(combined_smooth))
    peak_time = librosa.frames_to_time(peak_frame, sr=sr, hop_length=_HOP_LENGTH)

    # Confidence: how much higher is the peak vs mean?
    mean_score = combined_smooth[combined_smooth > 0].mean()
    peak_score = combined_smooth[peak_frame]
    confidence = float(min((peak_score / mean_score - 1.0) / 2.0, 1.0)) if mean_score > 0 else 0.5

    # --- Snap to nearest beat ---
    start_sec = _snap_to_beat(peak_time, beat_times)

    # --- Set end time ---
    end_sec = min(start_sec + target_duration, duration - 5.0)

    # Edge case: end is too close to start
    if end_sec - start_sec < 20:
        start_sec = max(0, duration * 0.25)
        start_sec = _snap_to_beat(start_sec, beat_times)
        end_sec = min(start_sec + target_duration, duration - 5.0)

    logger.info(
        f"Chorus detected: {_sec_to_mmss(start_sec)} -> {_sec_to_mmss(end_sec)} "
        f"(confidence={confidence:.2f}, peak_time={peak_time:.1f}s)"
    )

    return ChorusResult(
        start_sec=start_sec,
        end_sec=end_sec,
        confidence=confidence,
        method="recurrence"
    )


def _rms_fallback(y, sr, duration, target_duration, beat_times) -> ChorusResult:
    """
    Fallback when recurrence matrix fails.
    Finds the loudest sustained section using RMS energy.
    This is simpler but still gets the hook right for most pop songs.
    """
    rms = librosa.feature.rms(y=y, hop_length=_HOP_LENGTH)[0]
    smooth = np.convolve(rms, np.ones(200) / 200, mode='same')

    skip = int(0.15 * len(smooth))
    outro = int(0.85 * len(smooth))
    smooth[:skip] = 0
    smooth[outro:] = 0

    peak = int(np.argmax(smooth))
    peak_time = librosa.frames_to_time(peak, sr=sr, hop_length=_HOP_LENGTH)
    start_sec = _snap_to_beat(peak_time, beat_times)
    end_sec = min(start_sec + target_duration, duration - 5.0)

    return ChorusResult(
        start_sec=start_sec,
        end_sec=end_sec,
        confidence=0.5,
        method="rms_fallback"
    )


def _heuristic_fallback(duration, target_duration, reason) -> ChorusResult:
    """
    Last-resort fallback. Skips 20% of song, takes target_duration seconds.
    No audio analysis required.
    """
    start_sec = duration * 0.20
    end_sec = min(start_sec + target_duration, duration - 5.0)

    return ChorusResult(
        start_sec=start_sec,
        end_sec=end_sec,
        confidence=0.2,
        method="heuristic"
    )
