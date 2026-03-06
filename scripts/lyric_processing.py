"""
Aurora Lyric Processing - Line-level transcription with Genius alignment
Uses the shared whisper_common module and sliding window alignment engine.

Output format: segments with {t, end_time, lyric_prev, lyric_current, lyric_next1, lyric_next2}
  - lyric_prev, lyric_next1, lyric_next2 are ALWAYS empty strings
  - Only lyric_current is populated with the actual line
  - #12: end_time is now preserved in output
"""
import os
import json
import copy

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics
from scripts.lyric_alignment import align_genius_to_whisper
from scripts import whisper_common


def transcribe_audio(job_folder, song_title=None):
    """
    Transcribe audio and align with Genius lyrics for Aurora template.
    Returns path to saved lyrics.txt file, or None on failure.
    """
    print(f"\n\u270e Aurora Transcription ({Config.WHISPER_MODEL})...")

    audio_path = os.path.join(job_folder, "audio_trimmed.wav")

    if not os.path.exists(audio_path):
        print("\u274c Trimmed audio not found")
        return None

    try:
        audio_duration = whisper_common.get_audio_duration(audio_path)
        if audio_duration is not None:
            print(f"  Audio duration: {audio_duration:.1f}s")
        else:
            print("  \u26a0 Could not determine audio duration")

        initial_prompt = whisper_common.build_initial_prompt(song_title)
        language = whisper_common.detect_language(song_title)

        # ============================================================
        # CHECK WHISPER CACHE (#11)
        # ============================================================
        cached = whisper_common.load_whisper_cache(job_folder)
        if cached:
            segments = []
            for seg in cached:
                text = seg.get("text", "").strip()
                if not text:
                    continue
                segments.append({
                    "t": float(seg["start"]),
                    "end_time": float(seg["end"]),
                    "lyric_prev": "",
                    "lyric_current": text,
                    "lyric_next1": "",
                    "lyric_next2": ""
                })
        else:
            # ============================================================
            # VOCAL SEPARATION (Demucs) + MULTI-PASS TRANSCRIPTION
            # ============================================================
            transcribe_path = whisper_common.separate_vocals(audio_path, job_folder)
            result, pass_idx = whisper_common.multi_pass_transcribe(
                transcribe_path, initial_prompt, audio_duration, language,
                word_timestamps=True,
            )

            if not result or not result.segments:
                print("\u274c Whisper returned no segments after all attempts")
                return None

            segments = []
            for seg in result.segments:
                text = seg.text.strip()
                if not text:
                    continue
                segments.append({
                    "t": float(seg.start),
                    "end_time": float(seg.end),
                    "lyric_prev": "",
                    "lyric_current": text,
                    "lyric_next1": "",
                    "lyric_next2": ""
                })

            if segments:
                whisper_common.save_whisper_cache(job_folder, segments)

        if not segments:
            print("\u274c No valid segments after extraction")
            return None

        print(f"  Raw Whisper output: {len(segments)} segments")

        # ============================================================
        # CLEANUP PIPELINE
        # ============================================================
        segments = whisper_common.remove_hallucinations(segments, "lyric_current", initial_prompt)
        segments = whisper_common.remove_junk(segments, "lyric_current")
        segments = whisper_common.remove_stutter_duplicates(segments, "lyric_current")
        segments = whisper_common.remove_repetition_loops(segments, "lyric_current")
        segments = whisper_common.remove_instrumental_hallucinations(
            segments, "lyric_current", audio_path
        )

        if not segments:
            print("\u274c No segments remain after cleanup")
            return None

        print(f"  After cleanup: {len(segments)} segments")

        # ============================================================
        # GENIUS ALIGNMENT (#10: validate match ratio)
        # ============================================================
        if song_title and Config.GENIUS_API_TOKEN:
            print("\u270e Fetching Genius lyrics...")
            genius_text = fetch_genius_lyrics(song_title)

            if genius_text:
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)

                print("\u270e Aligning lyrics (sliding window)...")
                segments_backup = copy.deepcopy(segments)
                segments, match_ratio = align_genius_to_whisper(
                    segments, genius_text, segment_text_key="lyric_current"
                )

                if match_ratio < 0.3:
                    print(f"  \u26a0 Low match ratio ({match_ratio:.2f}) \u2014 reverting to Whisper text")
                    segments = segments_backup
            else:
                print("  \u26a0 Using Whisper text only (Genius unavailable)")

        # ============================================================
        # FINAL CLEANUP & OUTPUT
        # ============================================================
        segments = [s for s in segments if s["lyric_current"].strip()]
        segments = whisper_common.remove_non_target_script(segments, "lyric_current", song_title)

        for seg in segments:
            seg["lyric_current"] = _wrap_line(seg["lyric_current"])
            seg["lyric_prev"] = ""
            seg["lyric_next1"] = ""
            seg["lyric_next2"] = ""
            # #12: end_time is preserved (no longer removed)

        # Quality warning
        if segments and audio_duration and audio_duration > 0:
            ratio = len(segments) / audio_duration * 10
            if ratio < 1.0:
                print(f"  \u26a0 LOW QUALITY: only {len(segments)} segments for {audio_duration:.0f}s")

        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=4, ensure_ascii=False)

        print(f"\u2713 Transcription complete: {len(segments)} segments")
        return lyrics_path

    except Exception as e:
        print(f"\u274c Transcription failed: {e}")
        raise


# ============================================================================
# AURORA-SPECIFIC: Line wrapping for After Effects
# ============================================================================

def _wrap_line(text, limit=None):
    """Wrap long lines for After Effects text display."""
    if limit is None:
        limit = Config.MAX_LINE_LENGTH
    text = text.strip()
    if not text or "\\r" in text:
        return text
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut == -1:
        cut = limit
    first = text[:cut].strip()
    rest = text[cut:].strip()
    return f"{first} \\r {rest}"
