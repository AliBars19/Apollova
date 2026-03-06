"""
Onyx Lyric Processing - Word-level timestamp extraction
For hybrid template: word-by-word lyrics + spinning disc.
Uses the shared whisper_common module.

Output: markers with {time, text, words[], color, end_time}
"""
import os
import json
import copy

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics
from scripts.lyric_alignment import align_genius_to_whisper
from scripts import whisper_common


def transcribe_audio_onyx(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Onyx style videos.

    Returns dict with:
        - markers: list of marker objects for JSX
        - total_markers: count of markers
    """
    print(f"\n\u270e Onyx Transcription ({Config.WHISPER_MODEL})...")

    audio_path = os.path.join(job_folder, "audio_trimmed.wav")

    if not os.path.exists(audio_path):
        print("\u274c Trimmed audio not found")
        return {"markers": [], "total_markers": 0}

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
            markers = []
            for seg in cached:
                text = seg.get("text", "").strip()
                if not text:
                    continue
                markers.append({
                    "time": float(seg["start"]),
                    "text": text,
                    "words": seg.get("words", []),
                    "color": "",
                    "end_time": float(seg["end"])
                })
        else:
            # ============================================================
            # VOCAL SEPARATION (Demucs) + MULTI-PASS TRANSCRIPTION
            # ============================================================
            transcribe_path = whisper_common.separate_vocals(audio_path, job_folder)
            result, pass_idx = whisper_common.multi_pass_transcribe(
                transcribe_path, initial_prompt, audio_duration, language,
                word_timestamps=True,
                regroup_passes=[False, False, False, True]
            )

            if not result or not result.segments:
                print("\u274c Whisper returned no segments after all attempts")
                return {"markers": [], "total_markers": 0}

            # Manual regrouping (Onyx benefits from shorter segments)
            try:
                result = result.split_by_gap(0.5)
                result = result.split_by_punctuation(['.', '?', '!', ','])
                result = result.split_by_length(max_chars=50)
            except Exception as e:
                print(f"  \u26a0 Regrouping failed (using defaults): {e}")

            markers = whisper_common.build_markers_from_segments(result.segments)

            if markers:
                whisper_common.save_whisper_cache(job_folder, markers)

        if not markers:
            print("\u274c No valid markers generated")
            return {"markers": [], "total_markers": 0}

        print(f"  Raw Whisper output: {len(markers)} markers")

        # ============================================================
        # CLEANUP PIPELINE
        # ============================================================
        markers = whisper_common.remove_hallucinations(markers, "text", initial_prompt)
        markers = whisper_common.remove_junk(markers, "text")
        markers = whisper_common.remove_stutter_duplicates(markers, "text")
        markers = whisper_common.remove_repetition_loops(markers, "text")
        markers = whisper_common.remove_instrumental_hallucinations(
            markers, "text", audio_path
        )

        if not markers:
            print("\u274c No markers remain after cleanup")
            return {"markers": [], "total_markers": 0}

        print(f"  After cleanup: {len(markers)} markers")

        # ============================================================
        # GENIUS ALIGNMENT (#10: validate match ratio)
        # ============================================================
        if song_title and Config.GENIUS_API_TOKEN:
            print("\u270e Fetching Genius lyrics for alignment...")
            genius_text = fetch_genius_lyrics(song_title)

            if genius_text:
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)

                print("\u270e Aligning lyrics (sliding window)...")
                markers_backup = copy.deepcopy(markers)
                markers, match_ratio = align_genius_to_whisper(
                    markers, genius_text, segment_text_key="text"
                )

                if match_ratio < 0.3:
                    print(f"  \u26a0 Low match ratio ({match_ratio:.2f}) \u2014 reverting to Whisper text")
                    markers = markers_backup
                else:
                    markers = whisper_common.rebuild_words_after_alignment(markers)

        # ============================================================
        # FINAL CLEANUP
        # ============================================================
        markers = [m for m in markers if m["text"].strip()]
        markers = whisper_common.remove_non_target_script(markers, "text", song_title)
        whisper_common.assign_colors(markers)
        whisper_common.fix_marker_gaps(markers)

        if markers and audio_duration and audio_duration > 0:
            ratio = len(markers) / audio_duration * 10
            if ratio < 1.0:
                print(f"  \u26a0 LOW QUALITY: only {len(markers)} markers for {audio_duration:.0f}s")

        print(f"\u2713 Onyx transcription complete: {len(markers)} markers")

        return {
            "markers": markers,
            "total_markers": len(markers)
        }

    except Exception as e:
        print(f"\u274c Onyx transcription failed: {e}")
        raise
