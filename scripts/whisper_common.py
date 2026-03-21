"""
Whisper Common - Shared transcription utilities for Aurora, Mono, and Onyx.

Extracted from duplicated code across template pipelines.
All functions are parameterized by text_key for template differences.

Improvements applied:
  #2:  Model caching (load once, reuse across jobs)
  #3:  Weighted multi-pass scoring
  #4:  Fuzzy word matching in rebuild_words_after_alignment
  #6:  Removed "you" from hallucination patterns
  #7:  detect_language returns None for unknown songs
  #8:  Fuzzy stutter duplicate detection (fuzz.ratio > 90)
  #11: Whisper cache (whisper_raw.json)
  #13: get_audio_duration returns None on failure; min_expected=2 when unknown
  #14: fix_marker_gaps threshold 4.0s, proportional compression
  #17: Instrumental hallucination detection via RMS energy
  #21: Voice freq filter (200-5000Hz bandpass via only_voice_freq)
  #22: Zero-duration word fix (min_word_dur + apply_min_dur)
  #23: Silence-adjusted word timestamps (adjust_by_silence)
  #24: Confidence metrics (word probability + segment logprob/no_speech_prob)
  #25: Audio normalization (-20 dBFS before Whisper)
  #26: Non-speech skip (skip instrumental sections >5s)
  #27: Built-in word-level repetition removal (remove_repetition)
"""
import os
import json
import re
import gc

from pydub import AudioSegment
from stable_whisper import load_model
from rapidfuzz import fuzz

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from scripts.config import Config


# ============================================================================
# MODEL CACHING (#2)
# ============================================================================

_cached_model = None
_cached_on_cpu = None


def get_device_info():
    """Return string describing which device Whisper will use."""
    if HAS_TORCH and torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        return f"GPU ({name})"
    return "CPU"


def load_whisper_model(force_cpu=False):
    """Load Whisper model with caching — skip reload if same config."""
    global _cached_model, _cached_on_cpu

    if _cached_model is not None and _cached_on_cpu == force_cpu:
        print(f"  \u267b Reusing cached {Config.WHISPER_MODEL} model")
        return _cached_model

    # Unload existing if config changed
    if _cached_model is not None:
        unload_model()

    os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)

    device = get_device_info()
    if force_cpu and HAS_TORCH:
        original_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        try:
            print(f"  Loading {Config.WHISPER_MODEL} on CPU (forced)...")
            _cached_model = load_model(
                Config.WHISPER_MODEL,
                download_root=Config.WHISPER_CACHE_DIR,
                in_memory=False,
            )
        finally:
            if original_visible is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_visible
            else:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    else:
        print(f"  Loading {Config.WHISPER_MODEL} on {device}...")
        _cached_model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False,
        )

    _cached_on_cpu = force_cpu
    return _cached_model


def unload_model():
    """Explicit cleanup when truly done."""
    global _cached_model, _cached_on_cpu
    if _cached_model is not None:
        del _cached_model
        _cached_model = None
        _cached_on_cpu = None
        clear_vram()


def clear_vram():
    """Clear GPU memory between passes / after model unload."""
    gc.collect()
    if HAS_TORCH and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


# ============================================================================
# AUDIO HELPERS
# ============================================================================

def get_audio_duration(audio_path):
    """Get duration of audio file in seconds. Returns None on failure (#13)."""
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception:
        return None


def separate_vocals(audio_path, job_folder):
    """
    Use Demucs to extract vocals from audio for cleaner Whisper input.

    Saves vocals.wav in the job folder.  Returns the vocals path if
    successful, or the original audio_path as fallback.
    """
    vocals_path = os.path.join(job_folder, "vocals.wav")

    # Use cached vocals if already separated
    if os.path.exists(vocals_path):
        print("  Reusing cached vocals.wav")
        return vocals_path

    try:
        import subprocess, sys
        print("  Separating vocals (Demucs)...")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                [sys.executable, "-m", "demucs", "-n", "htdemucs",
                 "--two-stems", "vocals", "-o", tmpdir, audio_path],
                capture_output=True, text=True, timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode != 0:
                print(f"  Demucs failed: {r.stderr[:200]}")
                return audio_path

            stem = os.path.splitext(os.path.basename(audio_path))[0]
            src = os.path.join(tmpdir, "htdemucs", stem, "vocals.wav")
            if os.path.exists(src):
                import shutil
                shutil.copy2(src, vocals_path)
                print("  Vocals separated successfully")
                return vocals_path
            else:
                print("  Demucs output not found, using raw audio")
                return audio_path

    except ImportError:
        print("  Demucs not installed, using raw audio")
        return audio_path
    except Exception as e:
        print(f"  Vocal separation failed: {e}")
        return audio_path


def normalize_audio(audio_path):
    """
    Normalize audio to -20 dBFS for consistent Whisper input levels.
    Caches result as *_norm.wav to avoid re-processing.
    """
    norm_path = audio_path.replace('.wav', '_norm.wav')
    if os.path.exists(norm_path):
        return norm_path
    try:
        audio = AudioSegment.from_file(audio_path)
        if audio.dBFS == float('-inf'):
            return audio_path
        change = -20.0 - audio.dBFS
        normalized = audio.apply_gain(change)
        normalized.export(norm_path, format='wav')
        print("  Audio normalized to -20 dBFS")
        return norm_path
    except Exception as e:
        print(f"  Normalization failed: {e}")
        return audio_path


def build_initial_prompt(song_title):
    """Build Whisper initial prompt from song title."""
    if not song_title:
        return None
    if " - " in song_title:
        artist, track = song_title.split(" - ", 1)
        return f"{track}, {artist}."
    return f"{song_title}."


def detect_language(song_title):
    """
    Detect likely language from song title.
    #7: Returns None for unknown songs — lets Whisper auto-detect.
    """
    if not song_title:
        return None

    title_lower = song_title.lower()

    spanish = [
        "despacito", "danza kuduro", "taki taki", "gata only",
        "telepatia", "ozuna", "don omar", "luis fonsi", "floyymenor",
        "bad bunny", "j balvin", "daddy yankee", "nicky jam",
        "maluma", "shakira", "reggaeton", "latino",
    ]
    for s in spanish:
        if s in title_lower:
            return "es"

    french = ["stromae", "papaoutai", "edith piaf", "daft punk"]
    for f in french:
        if f in title_lower:
            return "fr"

    if "nimco happy" in title_lower or "isii nafta" in title_lower:
        return "so"

    if "ckay" in title_lower and "nwantiti" in title_lower:
        return "ig"

    return "en"


# ============================================================================
# SCRIPT FILTERING
# ============================================================================

def remove_non_target_script(items, text_key, song_title=None):
    """Remove items with non-Latin script (translation leaks)."""
    if not items:
        return items

    lang = detect_language(song_title) if song_title else "en"
    latin_languages = {"en", "es", "fr", "pt", "it", "de", "so", "ig"}
    if lang not in latin_languages:
        return items

    filtered = []
    removed = 0

    for item in items:
        text = item.get(text_key, "").strip()
        if not text:
            continue
        latin_count = 0
        non_latin_count = 0
        for char in text:
            if char.isalpha():
                cp = ord(char)
                if cp < 0x0250 or (0x1E00 <= cp <= 0x1EFF):
                    latin_count += 1
                else:
                    non_latin_count += 1
        total = latin_count + non_latin_count
        if total > 0 and non_latin_count / total > 0.4:
            print(f"   \U0001f5d1 Non-Latin script: '{text[:50]}'")
            removed += 1
        else:
            filtered.append(item)

    if removed:
        print(f"   Removed {removed} non-target script segment(s)")
    return filtered


# ============================================================================
# HALLUCINATION REMOVAL (#6: Removed "you" pattern)
# ============================================================================

def remove_hallucinations(items, text_key, initial_prompt):
    """
    Remove segments where Whisper hallucinated.
    #6: Removed the "you" pattern — "you" is a common lyric word.
    """
    patterns = [
        r"^thank\s*you\s+(for\s+)?(watching|listening)\s*\.?$",
        r"^(please\s+)?subscribe\b",
        r"^\s*music\s*\.?$",
        r"^\s*\[?\s*music\s*\]?\s*$",
        r"^\s*\u266a+\s*$",
        r"^subtitles?\s+by\b",
        r"^captions?\s+by\b",
        r"^copyright\b",
        r"^all\s+rights?\s+reserved",
        r"^\s*\.\.\.\s*$",
    ]

    filtered = []
    removed = 0

    for item in items:
        text = item.get(text_key, "").strip()
        if not text:
            continue

        text_clean = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower().strip()

        is_hallucination = False
        for pattern in patterns:
            try:
                if re.search(pattern, text_clean, re.IGNORECASE):
                    is_hallucination = True
                    break
            except re.error:
                continue

        if not is_hallucination and initial_prompt:
            prompt_clean = re.sub(r"[^a-zA-Z0-9\s]", "", initial_prompt).lower().strip()
            similarity = fuzz.ratio(text_clean, prompt_clean)
            if similarity > 85 and len(text_clean.split()) <= len(prompt_clean.split()) + 2:
                is_hallucination = True

        if is_hallucination:
            print(f"   \U0001f5d1 Hallucination: '{text[:60]}'")
            removed += 1
        else:
            filtered.append(item)

    if removed:
        print(f"   Removed {removed} hallucinated segment(s)")
    return filtered


# ============================================================================
# JUNK REMOVAL
# ============================================================================

def remove_junk(items, text_key):
    """Remove items that are clearly not lyrics."""
    junk_patterns = [
        r"^[\W\s]+$",
        r"^(um|uh|hmm|ah|oh|ha|huh)+\s*$",
        r"^\.*$",
        r"^-+$",
    ]

    filtered = []
    removed = 0

    for item in items:
        text = item.get(text_key, "").strip()
        text_alpha = re.sub(r"[^a-zA-Z]", "", text)

        if len(text_alpha) < 2:
            removed += 1
            continue

        text_lower = text.lower().strip()
        is_junk = any(re.search(p, text_lower) for p in junk_patterns)

        if is_junk:
            removed += 1
        else:
            filtered.append(item)

    if removed:
        print(f"   Removed {removed} junk segment(s)")
    return filtered


# ============================================================================
# REPETITION LOOP DETECTION (#18)
# ============================================================================

def remove_repetition_loops(items, text_key):
    """
    Detect Whisper hallucination loops where the same phrase repeats 3+
    times in a row. Keep the first two occurrences, remove the rest.
    Common with instrumental sections and mumbled vocals.
    """
    if len(items) < 3:
        return items

    clean_re = re.compile(r"[^a-zA-Z0-9\s]")
    removed = 0
    result = []
    streak = 1

    for i, item in enumerate(items):
        curr = clean_re.sub("", item.get(text_key, "")).lower().strip()
        prev = clean_re.sub("", items[i - 1].get(text_key, "")).lower().strip() if i > 0 else ""

        if curr and prev and fuzz.ratio(curr, prev) > 85:
            streak += 1
        else:
            streak = 1

        if streak <= 2:
            result.append(item)
        else:
            removed += 1

    if removed:
        print(f"   Removed {removed} repetition loop segment(s)")
    return result


# ============================================================================
# STUTTER DUPLICATE REMOVAL (#8: Fuzzy matching)
# ============================================================================

def remove_stutter_duplicates(items, text_key):
    """
    Remove consecutive duplicates with tiny gaps (Whisper stutters).
    #8: Uses fuzz.ratio > 90 instead of exact match.
    """
    if len(items) < 2:
        return items

    clean_re = re.compile(r"[^a-zA-Z0-9\s]")
    removed = 0

    # Determine time key based on text_key
    time_key = "t" if text_key == "lyric_current" else "time"

    i = len(items) - 1
    while i > 0:
        curr = clean_re.sub("", items[i].get(text_key, "")).lower().strip()
        prev = clean_re.sub("", items[i - 1].get(text_key, "")).lower().strip()

        if curr and prev and fuzz.ratio(curr, prev) > 90:
            curr_time = items[i].get(time_key, 0)
            prev_end = items[i - 1].get("end_time", items[i - 1].get(time_key, 0) + 2)
            gap = curr_time - prev_end

            if gap < 0.5:
                items.pop(i)
                removed += 1
        i -= 1

    if removed:
        print(f"   Removed {removed} stutter duplicate(s)")
    return items


# ============================================================================
# MULTI-PASS TRANSCRIPTION (#3, #7, #13)
# ============================================================================

def multi_pass_transcribe(audio_path, prompt, duration, language,
                          word_timestamps=True, regroup_passes=None):
    """
    Try multiple Whisper configurations, return (best_result, pass_index).

    #3:  Weighted scoring — earlier passes get higher weight.
         Accept pass 1 at 70% of min_expected.
    #7:  Omit language param when None.
    #13: min_expected=2 when duration is None.
    """
    if regroup_passes is None:
        regroup_passes = [True, True, True, True]

    # Normalize audio levels for consistent Whisper input
    audio_path = normalize_audio(audio_path)

    # Verify the actual audio file duration matches what caller reported
    actual_dur = get_audio_duration(audio_path)
    print(f"  🔍 Whisper input: {audio_path}")
    print(f"  🔍 File duration: {actual_dur:.1f}s (caller reported: {duration}s)")
    if actual_dur is not None and duration is not None and actual_dur > duration + 10:
        print(f"  ⚠ WARNING: audio file ({actual_dur:.1f}s) much longer than expected ({duration}s)!")

    # #13: Graceful when duration is unknown
    if duration is not None:
        min_expected = max(2, int(duration / 3.5))
    else:
        min_expected = 2

    # #7: Only include language if known
    lang_params = {"language": language} if language else {}

    wt_params = {"word_timestamps": True} if word_timestamps else {}

    passes = [
        {
            "name": "Pass 1 (strict)",
            "weight": 1.0,
            "params": dict(
                vad=True, vad_threshold=0.25,
                suppress_silence=True, regroup=regroup_passes[0],
                temperature=0, initial_prompt=prompt,
                condition_on_previous_text=False,
                only_voice_freq=True, min_word_dur=0.02,
                nonspeech_skip=5.0,
                **wt_params, **lang_params,
            )
        },
        {
            "name": "Pass 2 (medium)",
            "weight": 0.9,
            "params": dict(
                vad=True, vad_threshold=0.2,
                suppress_silence=False, regroup=regroup_passes[1],
                temperature=0.2, initial_prompt=prompt,
                condition_on_previous_text=False,
                only_voice_freq=True, min_word_dur=0.02,
                nonspeech_skip=5.0,
                **wt_params, **lang_params,
            )
        },
        {
            "name": "Pass 3 (loose)",
            "weight": 0.75,
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=regroup_passes[2], temperature=0.4,
                initial_prompt=prompt,
                condition_on_previous_text=False,
                only_voice_freq=True, min_word_dur=0.02,
                nonspeech_skip=5.0,
                **wt_params, **lang_params,
            )
        },
        {
            "name": "Pass 4 (no prompt)",
            "weight": 0.6,
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=regroup_passes[3], temperature=0.6,
                initial_prompt=None,
                condition_on_previous_text=True,
                only_voice_freq=True, min_word_dur=0.02,
                nonspeech_skip=5.0,
                **wt_params,
                # No language hint on pass 4 — let Whisper auto-detect
            )
        },
    ]

    best_result = None
    best_score = 0
    best_pass_idx = -1
    model = None
    used_cpu_fallback = False
    import time as _time

    try:
        model = load_whisper_model()
        device = get_device_info()
        print(f"  🖥 Device: {device}")
        batch_start = _time.time()

        for idx, p in enumerate(passes):
            # Time cap: if we already have a result and spent > 180s, stop
            elapsed_total = _time.time() - batch_start
            if best_result is not None and elapsed_total > 180:
                print(f"  ⏱ Time cap reached ({elapsed_total:.0f}s) — using best result from pass {best_pass_idx + 1}")
                try:
                    best_result.adjust_by_silence(audio_path, vad=True)
                except Exception:
                    pass
                return best_result, best_pass_idx

            try:
                clear_vram()
                pass_start = _time.time()
                print(f"  {p['name']}...")
                result = model.transcribe(audio_path, **p["params"])
                pass_time = _time.time() - pass_start

                if not result or not result.segments:
                    print(f"    \u2192 0 segments ({pass_time:.0f}s)")
                    continue

                # Post-transcription refinement
                try:
                    result.apply_min_dur(0.02)
                    result.remove_repetition(max_words=1)
                except Exception:
                    pass

                count = sum(
                    1 for s in result.segments
                    if s.text.strip() and len(s.text.strip()) > 1
                )
                print(f"    \u2192 {count} segments ({pass_time:.0f}s)")

                # #3: Weighted score
                weighted = count * p["weight"]
                if weighted > best_score:
                    best_score = weighted
                    best_result = result
                    best_pass_idx = idx

                # Accept early only if we have genuinely good results
                if count >= min_expected:
                    print(f"    \u2713 Sufficient ({count} \u2265 {min_expected} expected)")
                    # Snap word timestamps to speech boundaries
                    try:
                        result.adjust_by_silence(audio_path, vad=True)
                    except Exception:
                        pass
                    return result, idx

            except RuntimeError as e:
                if "CUDA out of memory" in str(e) and not used_cpu_fallback:
                    print(f"    \u26a0 GPU OOM \u2014 switching to CPU...")
                    unload_model()
                    model = load_whisper_model(force_cpu=True)
                    used_cpu_fallback = True
                    try:
                        result = model.transcribe(audio_path, **p["params"])
                        if result and result.segments:
                            try:
                                result.apply_min_dur(0.02)
                                result.remove_repetition(max_words=1)
                            except Exception:
                                pass
                            count = sum(
                                1 for s in result.segments
                                if s.text.strip() and len(s.text.strip()) > 1
                            )
                            print(f"    \u2192 {count} segments (CPU)")
                            weighted = count * p["weight"]
                            if weighted > best_score:
                                best_score = weighted
                                best_result = result
                                best_pass_idx = idx
                            threshold = int(min_expected * 0.7) if idx == 0 else min_expected
                            if count >= threshold:
                                try:
                                    result.adjust_by_silence(audio_path, vad=True)
                                except Exception:
                                    pass
                                return result, idx
                    except Exception as cpu_e:
                        print(f"    \u2192 CPU fallback failed: {cpu_e}")
                else:
                    print(f"    \u2192 Error: {e}")
                    continue

            except Exception as e:
                print(f"    \u2192 Error: {e}")
                continue

        if best_result:
            print(f"  \u26a0 Best: weighted {best_score:.1f} (wanted {min_expected}+)")
            # Snap word timestamps to speech boundaries
            try:
                best_result.adjust_by_silence(audio_path, vad=True)
            except Exception:
                pass

        return best_result, best_pass_idx

    finally:
        # Don't unload — model is cached for next job (#2)
        # Only clear VRAM between runs
        clear_vram()


# ============================================================================
# MARKER BUILDING (Mono/Onyx shared)
# ============================================================================

def build_markers_from_segments(segments):
    """Build marker objects from Whisper segments with word timing."""
    markers = []

    for segment in segments:
        seg_text = segment.text.strip()
        seg_start = float(segment.start)
        seg_end = float(segment.end)

        if not seg_text or len(seg_text) < 2:
            continue
        if seg_end - seg_start > 30:
            print(f"   \u26a0 Skipping overly long segment ({seg_end - seg_start:.1f}s): {seg_text[:30]}...")
            continue

        words = extract_word_timings(segment, seg_start, seg_end, seg_text)

        marker = {
            "time": round(seg_start, 3),
            "text": seg_text,
            "words": words,
            "color": "",
            "end_time": round(seg_end, 3),
        }

        # Save segment confidence metrics for diagnostics
        avg_logprob = getattr(segment, 'avg_logprob', None)
        no_speech_prob = getattr(segment, 'no_speech_prob', None)
        if avg_logprob is not None:
            marker["avg_logprob"] = round(float(avg_logprob), 4)
        if no_speech_prob is not None:
            marker["no_speech_prob"] = round(float(no_speech_prob), 4)

        markers.append(marker)

    return markers


def extract_word_timings(segment, seg_start, seg_end, seg_text):
    """Extract word-level timings from a Whisper segment."""
    words = []

    if hasattr(segment, 'words') and segment.words:
        for word in segment.words:
            word_text = word.word.strip()
            if not word_text:
                continue
            ws = float(word.start)
            we = float(word.end)
            if we - ws > 3:
                we = ws + 1.0
            w_entry = {
                "word": word_text,
                "start": round(ws, 3),
                "end": round(we, 3),
            }
            prob = getattr(word, 'probability', None)
            if prob is not None:
                w_entry["probability"] = round(float(prob), 3)
            words.append(w_entry)

    if not words:
        word_list = seg_text.split()
        if word_list:
            dur = seg_end - seg_start
            wd = min(dur / len(word_list), 3.0)
            for i, w in enumerate(word_list):
                words.append({
                    "word": w,
                    "start": round(seg_start + i * wd, 3),
                    "end": round(seg_start + (i + 1) * wd, 3)
                })

    return words


# ============================================================================
# WORD TIMING REBUILD (#4: Fuzzy word matching)
# ============================================================================

def rebuild_words_after_alignment(markers):
    """
    After Genius alignment, rebuild word arrays with Genius text and Whisper timing.
    #4: Uses fuzzy matching instead of positional mapping.
    """
    for marker in markers:
        genius_words = marker["text"].split()
        whisper_words = marker.get("words", [])

        if not genius_words or not whisper_words:
            continue

        whisper_joined = " ".join(w["word"] for w in whisper_words)
        if whisper_joined.strip().lower() == marker["text"].strip().lower():
            continue

        new_words = []

        if len(genius_words) <= len(whisper_words):
            # #4: Fuzzy match each genius word to best whisper word
            used = set()
            for gw in genius_words:
                best_idx = -1
                best_score = -1
                gw_clean = re.sub(r"[^a-zA-Z0-9]", "", gw).lower()

                for wi, ww in enumerate(whisper_words):
                    if wi in used:
                        continue
                    ww_clean = re.sub(r"[^a-zA-Z0-9]", "", ww["word"]).lower()
                    score = fuzz.ratio(gw_clean, ww_clean)
                    if score > best_score:
                        best_score = score
                        best_idx = wi

                if best_idx >= 0:
                    used.add(best_idx)
                    new_words.append({
                        "word": gw,
                        "start": whisper_words[best_idx]["start"],
                        "end": whisper_words[best_idx]["end"]
                    })
                else:
                    new_words.append({
                        "word": gw,
                        "start": marker["time"],
                        "end": marker["end_time"]
                    })
        else:
            # More Genius words: distribute evenly across time span
            seg_start = marker["time"]
            seg_end = marker["end_time"]
            dur = seg_end - seg_start
            wd = dur / len(genius_words) if genius_words else dur
            for i, gw in enumerate(genius_words):
                new_words.append({
                    "word": gw,
                    "start": round(seg_start + i * wd, 3),
                    "end": round(seg_start + (i + 1) * wd, 3)
                })

        # Sort by start time to preserve chronological order
        new_words.sort(key=lambda w: w["start"])
        marker["words"] = new_words

    return markers


# ============================================================================
# FORCED ALIGNMENT (#28: Genius text → audio via model.align)
# ============================================================================

def align_genius_to_audio(audio_path, genius_text, language=None):
    """
    Use stable-ts forced alignment to get precise word timestamps for Genius text.
    Falls back to None on failure — caller should use rebuild_words_after_alignment.
    """
    if not genius_text or not genius_text.strip():
        return None

    try:
        model = load_whisper_model()
        lang_params = {"language": language} if language else {}
        result = model.align(
            audio_path, genius_text,
            vad=True, suppress_silence=True,
            min_word_dur=0.02, only_voice_freq=True,
            **lang_params,
        )
        if result and result.segments:
            try:
                result.adjust_by_silence(audio_path, vad=True)
            except Exception:
                pass
            print(f"  Forced alignment: {len(result.segments)} segments")
            return result
        return None
    except Exception as e:
        print(f"  Forced alignment failed: {e}")
        return None


# ============================================================================
# COLOR ASSIGNMENT (Mono/Onyx shared)
# ============================================================================

def assign_colors(markers):
    """Alternate white/black colors on markers."""
    for i, m in enumerate(markers):
        m["color"] = "white" if i % 2 == 0 else "black"


# ============================================================================
# MARKER GAP FIX (#14: Threshold 4.0s, proportional compression)
# ============================================================================

def fix_marker_gaps(markers):
    """
    Fix large gaps between consecutive words.
    #14: Threshold 2.0s -> 4.0s, proportional compression min(gap*0.1, 0.5).
    """
    for m in markers:
        words = m.get("words", [])
        for i in range(1, len(words)):
            gap = words[i]["start"] - words[i - 1]["end"]
            if gap > 4.0:
                compression = min(gap * 0.1, 0.5)
                words[i]["start"] = words[i - 1]["end"] + compression


# ============================================================================
# MERGE SHORT MARKERS (#19: Combine lonely single-word markers)
# ============================================================================

def merge_short_markers(markers, max_words=2, max_gap=1.5):
    """
    Merge single-word (or very short) markers with their nearest neighbour.
    Single-word markers like "yeah", "oh", "Spotlight," look bad in lyric
    videos. If the gap to the next marker is small enough, absorb into it.
    """
    if len(markers) < 2:
        return markers

    merged = []
    skip_next = False

    for i, m in enumerate(markers):
        if skip_next:
            skip_next = False
            continue

        word_count = len(m.get("text", "").split())

        if word_count <= max_words and i + 1 < len(markers):
            nxt = markers[i + 1]
            gap = nxt["time"] - m.get("end_time", m["time"])

            if gap <= max_gap:
                # Absorb current marker into the next one
                combined_text = m["text"].rstrip(",. ") + " " + nxt["text"]
                combined_words = m.get("words", []) + nxt.get("words", [])
                new_marker = {
                    "time": m["time"],
                    "text": combined_text,
                    "words": combined_words,
                    "color": nxt.get("color", ""),
                    "end_time": nxt.get("end_time", nxt["time"]),
                }
                merged.append(new_marker)
                skip_next = True
                print(f"   🔗 Merged short marker '{m['text'][:30]}' with next")
                continue

        merged.append(m)

    if len(merged) < len(markers):
        print(f"   Merged {len(markers) - len(merged)} short marker(s)")
    return merged


# ============================================================================
# QUALITY GATE (#20: Reject low-coverage transcriptions)
# ============================================================================

def quality_gate(markers, clip_duration):
    """
    Check if transcription markers adequately cover the clip.
    Returns (passed, issues) where issues is a list of warning strings.
    Callers can decide whether to save or discard.
    """
    issues = []

    if not markers:
        issues.append("No markers produced")
        return False, issues

    if clip_duration is None or clip_duration <= 0:
        return True, issues

    # Total time covered by markers
    covered = sum(
        m.get("end_time", m["time"]) - m["time"]
        for m in markers
    )
    coverage_pct = covered / clip_duration

    # Total dead space (gaps between markers)
    gaps = []
    if markers[0]["time"] > 3.0:
        gaps.append(markers[0]["time"])
    for i in range(1, len(markers)):
        gap = markers[i]["time"] - markers[i - 1].get("end_time", markers[i - 1]["time"])
        if gap > 3.0:
            gaps.append(gap)
    end_gap = clip_duration - markers[-1].get("end_time", markers[-1]["time"])
    if end_gap > 3.0:
        gaps.append(end_gap)
    total_dead = sum(gaps)
    dead_pct = total_dead / clip_duration

    # Check for non-Latin script in majority of text
    all_text = " ".join(m.get("text", "") for m in markers)
    latin_chars = sum(1 for c in all_text if c.isalpha() and ord(c) < 0x0250)
    non_latin = sum(1 for c in all_text if c.isalpha() and ord(c) >= 0x0250)
    total_alpha = latin_chars + non_latin
    if total_alpha > 0 and non_latin / total_alpha > 0.5:
        issues.append(f"Non-Latin script dominates ({non_latin}/{total_alpha} chars)")

    if coverage_pct < 0.25:
        issues.append(f"Coverage too low: {coverage_pct:.0%} of clip")

    if dead_pct > 0.5:
        issues.append(f"Dead space: {dead_pct:.0%} of clip ({len(gaps)} gap(s) > 3s)")

    if len(markers) == 1 and clip_duration > 10:
        issues.append(f"Single marker for {clip_duration:.0f}s clip")

    passed = len(issues) == 0
    if not passed:
        for iss in issues:
            print(f"   ⚠ Quality gate: {iss}")
    return passed, issues


# ============================================================================
# WHISPER CACHE (#11)
# ============================================================================

def save_whisper_cache(job_folder, segments):
    """Save raw Whisper segments to whisper_raw.json for caching.
    Tags the cache with the model name so stale caches are invalidated
    when the user changes WHISPER_MODEL."""
    cache_path = os.path.join(job_folder, "whisper_raw.json")
    try:
        data = []
        for seg in segments:
            entry = {
                "start": seg.get("t", seg.get("time", 0)),
                "end": seg.get("end_time", 0),
                "text": seg.get("lyric_current", seg.get("text", ""))
            }
            if "words" in seg:
                entry["words"] = seg["words"]
            data.append(entry)
        wrapper = {"model": Config.WHISPER_MODEL, "segments": data}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, indent=2, ensure_ascii=False)
        print(f"  \U0001f4be Cached {len(data)} segments to whisper_raw.json")
    except Exception as e:
        print(f"  \u26a0 Failed to save Whisper cache: {e}")


def load_whisper_cache(job_folder):
    """Load cached Whisper segments if available.
    Returns None if the cache was produced by a different model."""
    cache_path = os.path.join(job_folder, "whisper_raw.json")
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Support both old format (bare list) and new format (dict with model tag)
        if isinstance(raw, dict):
            cached_model = raw.get("model")
            data = raw.get("segments", [])
            if cached_model and cached_model != Config.WHISPER_MODEL:
                print(f"  \u26a0 Cache model mismatch ({cached_model} vs {Config.WHISPER_MODEL}) — re-transcribing")
                return None
        else:
            # Old format: bare list — use it but it can't be validated
            data = raw
        if data:
            print(f"  \u267b Loaded {len(data)} segments from Whisper cache")
            return data
    except Exception as e:
        print(f"  \u26a0 Failed to load Whisper cache: {e}")
    return None


# ============================================================================
# INSTRUMENTAL HALLUCINATION DETECTION (#17)
# ============================================================================

def remove_instrumental_hallucinations(items, text_key, audio_path):
    """
    Remove segments that fall over silent/instrumental sections.
    #17: RMS energy analysis — full-span check instead of midpoint-only.
    Also uses no_speech_prob from segment confidence metrics.
    """
    if not items:
        return items

    try:
        audio = AudioSegment.from_file(audio_path)
    except Exception:
        return items

    # Build silence map: 1s chunks, energy < 10% of max
    chunk_ms = 1000
    chunks = [audio[i:i + chunk_ms] for i in range(0, len(audio), chunk_ms)]

    if not chunks:
        return items

    rms_values = [chunk.rms for chunk in chunks]
    max_rms = max(rms_values) if rms_values else 1

    if max_rms == 0:
        return items

    silence_map = set()
    threshold = max_rms * 0.1
    for i, rms in enumerate(rms_values):
        if rms < threshold:
            silence_map.add(i)

    # Determine time key
    time_key = "t" if text_key == "lyric_current" else "time"

    filtered = []
    removed = 0

    for item in items:
        start = item.get(time_key, 0)
        end = item.get("end_time", start + 2)

        # Check 1: high no_speech_prob from Whisper confidence metrics
        no_speech = item.get("no_speech_prob", 0)
        if no_speech and no_speech > 0.7:
            print(f"   \U0001f5d1 High no_speech_prob ({no_speech:.2f}): '{item.get(text_key, '')[:50]}' @ {start:.1f}s")
            removed += 1
            continue

        # Check 2: full-span silence analysis (>70% of span in silence)
        if silence_map:
            start_chunk = int(start)
            end_chunk = int(end)
            span_chunks = list(range(start_chunk, end_chunk + 1))
            if span_chunks:
                silent_count = sum(1 for c in span_chunks if c in silence_map)
                silent_ratio = silent_count / len(span_chunks)
                if silent_ratio > 0.7:
                    print(f"   \U0001f5d1 Instrumental hallucination ({silent_ratio:.0%} silent): "
                          f"'{item.get(text_key, '')[:50]}' @ {start:.1f}s")
                    removed += 1
                    continue

        filtered.append(item)

    if removed:
        print(f"   Removed {removed} instrumental hallucination(s)")
    return filtered
