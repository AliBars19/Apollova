"""
Aurora Lyric Processing - Line-level transcription with Genius alignment
Uses the shared sliding window alignment engine for accurate lyrics.

Output format: segments with {t, lyric_prev, lyric_current, lyric_next1, lyric_next2}
  - lyric_prev, lyric_next1, lyric_next2 are ALWAYS empty strings
  - Only lyric_current is populated with the actual line

Bulletproof features:
  - Multi-pass Whisper (4 passes with escalating aggressiveness)
  - Hallucination detection (strips initial_prompt regurgitation)
  - Junk segment removal (filler, single chars, symbols)
  - Duration-based quality validation
  - Genius sliding window alignment
"""
import os
import json
import re
import gc
from pydub import AudioSegment
from stable_whisper import load_model

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics
from scripts.lyric_alignment import align_genius_to_whisper


def transcribe_audio(job_folder, song_title=None):
    """
    Transcribe audio and align with Genius lyrics for Aurora template.
    Returns path to saved lyrics.txt file, or None on failure.
    """
    print(f"\n✎ Aurora Transcription ({Config.WHISPER_MODEL})...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return None
    
    try:
        # Get audio duration for quality validation
        audio_duration = _get_audio_duration(audio_path)
        print(f"  Audio duration: {audio_duration:.1f}s")
        
        # Build context prompt
        initial_prompt = _build_initial_prompt(song_title)
        
        # ============================================================
        # MULTI-PASS TRANSCRIPTION (with VRAM management)
        # ============================================================
        language = _detect_language(song_title)
        result = _multi_pass_transcribe(audio_path, initial_prompt, audio_duration, language)
        
        if not result or not result.segments:
            print("❌ Whisper returned no segments after all attempts")
            return None
        
        # ============================================================
        # BUILD SEGMENTS
        # ============================================================
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
        
        if not segments:
            print("❌ No valid segments after extraction")
            return None
        
        print(f"  Raw Whisper output: {len(segments)} segments")
        
        # ============================================================
        # CLEANUP PIPELINE
        # ============================================================
        
        # 1. Remove hallucinated prompt text
        segments = _remove_hallucinations(segments, initial_prompt)
        
        # 2. Remove junk (filler, single chars, symbols, etc.)
        segments = _remove_junk_segments(segments)
        
        # 3. Remove Whisper stutter duplicates (< 0.5s gap)
        segments = _remove_stutter_duplicates(segments)
        
        if not segments:
            print("❌ No segments remain after cleanup")
            return None
        
        print(f"  After cleanup: {len(segments)} segments")
        
        # ============================================================
        # GENIUS ALIGNMENT
        # ============================================================
        if song_title and Config.GENIUS_API_TOKEN:
            print("✎ Fetching Genius lyrics...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                print("✎ Aligning lyrics (sliding window)...")
                segments = align_genius_to_whisper(
                    segments, genius_text, segment_text_key="lyric_current"
                )
            else:
                print("  ⚠ Using Whisper text only (Genius unavailable)")
        
        # ============================================================
        # FINAL CLEANUP & OUTPUT
        # ============================================================
        
        # Remove any segments that ended up empty after alignment
        segments = [s for s in segments if s["lyric_current"].strip()]
        
        # Strip non-Latin script lines (Greek/Cyrillic from bad Genius matches)
        segments = _remove_non_target_script(segments, "lyric_current", song_title)
        
        # Wrap long lines for AE display
        for seg in segments:
            seg["lyric_current"] = _wrap_line(seg["lyric_current"])
            seg["lyric_prev"] = ""
            seg["lyric_next1"] = ""
            seg["lyric_next2"] = ""
            seg.pop("end_time", None)
        
        # Quality warning for low-segment jobs
        if segments and audio_duration > 0:
            ratio = len(segments) / audio_duration * 10
            if ratio < 1.0:
                print(f"  ⚠ LOW QUALITY: only {len(segments)} segments for {audio_duration:.0f}s — consider adjusting timestamps")
        
        # Save
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=4, ensure_ascii=False)
        
        print(f"✓ Transcription complete: {len(segments)} segments")
        return lyrics_path
        
    except Exception as e:
        print(f"❌ Transcription failed: {e}")
        raise


# ============================================================================
# MULTI-PASS WHISPER TRANSCRIPTION
# ============================================================================

def _multi_pass_transcribe(audio_path, initial_prompt, audio_duration, language=None):
    """
    Try multiple Whisper configurations, from strict to aggressive.
    Returns the best result based on segment count vs. audio duration.
    
    VRAM Management:
      - Loads model fresh, clears VRAM between passes
      - On OOM: unloads model, clears VRAM, retries on CPU
      - Explicitly deletes model after completion
    
    Language hinting:
      - If language is detected from song title, forces it on passes 1-3
      - Pass 4 (nuclear) always auto-detects to catch edge cases
    """
    min_expected = max(2, int(audio_duration / 3.5))
    
    # Build language params for each pass
    lang_params = {"language": language} if language else {}
    
    passes = [
        {
            "name": "Pass 1 (strict)",
            "params": dict(
                vad=True, vad_threshold=0.35,
                suppress_silence=True, regroup=True,
                temperature=0, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
                **lang_params,
            )
        },
        {
            "name": "Pass 2 (medium)",
            "params": dict(
                vad=True, vad_threshold=0.2,
                suppress_silence=False, regroup=True,
                temperature=0.2, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
                **lang_params,
            )
        },
        {
            "name": "Pass 3 (loose)",
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=True, temperature=0.4,
                initial_prompt=initial_prompt,
                condition_on_previous_text=False,
                **lang_params,
            )
        },
        {
            "name": "Pass 4 (no prompt)",
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=True, temperature=0.6,
                initial_prompt=None,
                condition_on_previous_text=True,
                # No language hint — let Whisper auto-detect as last resort
            )
        },
    ]
    
    best_result = None
    best_count = 0
    model = None
    used_cpu_fallback = False
    
    try:
        # Load model (GPU if available)
        model = _load_whisper_model()
        
        for p in passes:
            try:
                # Clear VRAM before each pass
                _clear_vram()
                
                print(f"  {p['name']}...")
                result = model.transcribe(audio_path, **p["params"])
                
                if not result or not result.segments:
                    print(f"    → 0 segments")
                    continue
                
                count = sum(
                    1 for s in result.segments
                    if s.text.strip() and len(s.text.strip()) > 1
                )
                print(f"    → {count} segments")
                
                if count > best_count:
                    best_count = count
                    best_result = result
                
                if count >= min_expected:
                    print(f"    ✓ Sufficient ({count} ≥ {min_expected} expected)")
                    return result
                
            except RuntimeError as e:
                if "CUDA out of memory" in str(e) and not used_cpu_fallback:
                    print(f"    ⚠ GPU OOM — switching to CPU fallback...")
                    # Unload GPU model completely
                    del model
                    model = None
                    _clear_vram()
                    
                    # Reload on CPU
                    model = _load_whisper_model(force_cpu=True)
                    used_cpu_fallback = True
                    
                    # Retry this pass on CPU
                    try:
                        result = model.transcribe(audio_path, **p["params"])
                        if result and result.segments:
                            count = sum(1 for s in result.segments if s.text.strip() and len(s.text.strip()) > 1)
                            print(f"    → {count} segments (CPU)")
                            if count > best_count:
                                best_count = count
                                best_result = result
                            if count >= min_expected:
                                return result
                    except Exception as cpu_e:
                        print(f"    → CPU fallback also failed: {cpu_e}")
                else:
                    print(f"    → Error: {e}")
                    continue
                    
            except Exception as e:
                print(f"    → Error: {e}")
                continue
        
        if best_result:
            print(f"  ⚠ Best: {best_count} segments (wanted {min_expected}+)")
        
        return best_result
    
    finally:
        # ALWAYS clean up model after all passes
        if model is not None:
            del model
        _clear_vram()


def _load_whisper_model(force_cpu=False):
    """Load Whisper model with proper cache dir. Optionally force CPU."""
    os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
    
    if force_cpu and HAS_TORCH:
        # Force CPU by temporarily hiding CUDA
        original_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        try:
            print(f"  Loading {Config.WHISPER_MODEL} on CPU...")
            model = load_model(
                Config.WHISPER_MODEL,
                download_root=Config.WHISPER_CACHE_DIR,
                in_memory=False,
            )
        finally:
            if original_visible is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_visible
            else:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        return model
    
    return load_model(
        Config.WHISPER_MODEL,
        download_root=Config.WHISPER_CACHE_DIR,
        in_memory=False,
    )


def _clear_vram():
    """Clear GPU memory between passes / after model unload."""
    gc.collect()
    if HAS_TORCH and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


# ============================================================================
# HALLUCINATION REMOVAL
# ============================================================================

def _remove_hallucinations(segments, initial_prompt):
    """
    Remove segments where Whisper hallucinated:
    - Common Whisper hallucination patterns (music tags, thank yous, etc.)
    - Segments that are EXACTLY the prompt text with nothing else added
    
    IMPORTANT: Does NOT remove segments that contain the song title as part
    of actual lyrics. "I'm running up that hill" is a real lyric even though
    the song is called "Running Up That Hill". We only remove segments that
    are purely the prompt text with no additional lyrical content.
    """
    # Static hallucination patterns — these are NEVER real lyrics
    hallucination_patterns = [
        r"^thank\s*you\s+(for\s+)?(watching|listening)\s*\.?$",
        r"^(please\s+)?subscribe\b",
        r"^\s*music\s*\.?$",
        r"^\s*\[?\s*music\s*\]?\s*$",
        r"^\s*♪+\s*$",
        r"^subtitles?\s+by\b",
        r"^captions?\s+by\b",
        r"^copyright\b",
        r"^all\s+rights?\s+reserved",
        r"^\s*\.\.\.\s*$",
        r"^\s*you\s*\.?$",
    ]
    
    filtered = []
    removed = 0
    
    for seg in segments:
        text = seg.get("lyric_current", "").strip()
        if not text:
            continue
        
        text_clean = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower().strip()
        
        is_hallucination = False
        for pattern in hallucination_patterns:
            try:
                if re.search(pattern, text_clean, re.IGNORECASE):
                    is_hallucination = True
                    break
            except re.error:
                continue
        
        # Check for EXACT prompt regurgitation only
        # "Running Up That Hill, Kate Bush." being repeated verbatim = hallucination
        # "I'm running up that hill" = real lyric (has extra words)
        if not is_hallucination and initial_prompt:
            prompt_clean = re.sub(r"[^a-zA-Z0-9\s]", "", initial_prompt).lower().strip()
            from rapidfuzz import fuzz
            # Only flag if the segment is basically JUST the prompt (>85% match)
            # AND the segment is short (real lyrics tend to have more content)
            similarity = fuzz.ratio(text_clean, prompt_clean)
            if similarity > 85 and len(text_clean.split()) <= len(prompt_clean.split()) + 2:
                is_hallucination = True
        
        if is_hallucination:
            print(f"   🗑 Hallucination: '{text[:60]}'")
            removed += 1
        else:
            filtered.append(seg)
    
    if removed:
        print(f"   Removed {removed} hallucinated segment(s)")
    
    return filtered


# ============================================================================
# JUNK REMOVAL
# ============================================================================

def _remove_junk_segments(segments):
    """
    Remove segments that are clearly not lyrics:
    - Single characters / very short meaningless text
    - Pure punctuation / symbols
    - Filler sounds
    """
    junk_patterns = [
        r"^[\W\s]+$",                     # Pure punctuation/symbols/whitespace
        r"^(um|uh|hmm|ah|oh|ha|huh)+\s*$", # Filler sounds
        r"^\.*$",                           # Just dots
        r"^-+$",                            # Just dashes
    ]
    
    filtered = []
    removed = 0
    
    for seg in segments:
        text = seg.get("lyric_current", "").strip()
        text_alpha = re.sub(r"[^a-zA-Z]", "", text)
        
        # Must have at least 2 alphabetic characters
        if len(text_alpha) < 2:
            removed += 1
            continue
        
        text_lower = text.lower().strip()
        is_junk = False
        for pattern in junk_patterns:
            if re.search(pattern, text_lower):
                is_junk = True
                break
        
        if is_junk:
            removed += 1
        else:
            filtered.append(seg)
    
    if removed:
        print(f"   Removed {removed} junk segment(s)")
    
    return filtered


# ============================================================================
# STUTTER DUPLICATE REMOVAL
# ============================================================================

def _remove_stutter_duplicates(segments):
    """
    Remove consecutive duplicate segments with tiny time gaps (<0.5s).
    These are Whisper stutter artifacts, NOT intentional repeats.
    
    Choruses (same text, bigger gaps) are PRESERVED.
    """
    if len(segments) < 2:
        return segments
    
    removed = 0
    clean = re.compile(r"[^a-zA-Z0-9\s]")
    
    i = len(segments) - 1
    while i > 0:
        curr = clean.sub("", segments[i].get("lyric_current", "")).lower().strip()
        prev = clean.sub("", segments[i - 1].get("lyric_current", "")).lower().strip()
        
        if curr and prev and curr == prev:
            curr_time = segments[i].get("t", 0)
            prev_end = segments[i - 1].get("end_time", segments[i - 1].get("t", 0) + 2)
            gap = curr_time - prev_end
            
            if gap < 0.5:
                segments.pop(i)
                removed += 1
        i -= 1
    
    if removed:
        print(f"   Removed {removed} stutter duplicate(s)")
    
    return segments


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_audio_duration(audio_path):
    """Get duration of audio file in seconds"""
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception:
        return 30.0


def _build_initial_prompt(song_title):
    """
    Build Whisper initial prompt from song title.
    Kept SHORT and natural to minimize hallucination risk.
    """
    if not song_title:
        return None
    
    if " - " in song_title:
        artist, track = song_title.split(" - ", 1)
        return f"{track}, {artist}."
    
    return f"{song_title}."


def _detect_language(song_title):
    """
    Detect likely language from song title to help Whisper.
    
    Known non-English songs get their language code.
    Most songs default to English since the database is primarily English music.
    Returns None to let Whisper auto-detect for ambiguous cases.
    """
    if not song_title:
        return "en"
    
    title_lower = song_title.lower()
    
    # Known Spanish songs/artists
    spanish_indicators = [
        "despacito", "danza kuduro", "taki taki", "gata only",
        "telepatia", "ozuna", "don omar", "luis fonsi", "floyymenor",
        "bad bunny", "j balvin", "daddy yankee", "nicky jam",
        "maluma", "shakira", "reggaeton", "latino",
    ]
    for indicator in spanish_indicators:
        if indicator in title_lower:
            return "es"
    
    # Known French songs/artists
    french_indicators = ["stromae", "papaoutai", "edith piaf", "daft punk"]
    for indicator in french_indicators:
        if indicator in title_lower:
            return "fr"
    
    # Known Somali
    if "nimco happy" in title_lower or "isii nafta" in title_lower:
        return "so"
    
    # Known Nigerian/Pidgin
    if "ckay" in title_lower and "nwantiti" in title_lower:
        return "ig"  # Igbo
    
    # Default: English for everything else
    return "en"


def _remove_non_target_script(segments, text_key, song_title=None):
    """
    Remove segments that contain non-target script characters.
    
    Catches Greek, Cyrillic, Arabic, CJK etc. that leak in from
    Genius translation pages embedded within the original lyrics.
    
    Preserves:
      - Latin characters (English, Spanish, French, etc.)
      - Common accented chars (é, ñ, ü, etc.)
      - Known non-English songs (Spanish, French, etc.)
    """
    if not segments:
        return segments
    
    # Determine what scripts are expected
    lang = _detect_language(song_title) if song_title else "en"
    
    # Latin-based languages: allow all Latin + accented characters
    latin_languages = {"en", "es", "fr", "pt", "it", "de", "so", "ig"}
    
    if lang not in latin_languages:
        # Non-Latin language — don't filter, we expect non-Latin chars
        return segments
    
    filtered = []
    removed = 0
    
    for seg in segments:
        text = seg.get(text_key, "").strip()
        if not text:
            continue
        
        # Count characters by script type
        latin_count = 0
        non_latin_count = 0
        
        for char in text:
            if char.isalpha():
                cp = ord(char)
                # Latin + Latin Extended + Latin Supplement (covers accented chars)
                if cp < 0x0250 or (0x1E00 <= cp <= 0x1EFF):
                    latin_count += 1
                else:
                    non_latin_count += 1
        
        total_alpha = latin_count + non_latin_count
        
        # If more than 40% of alphabetic chars are non-Latin, it's a translation leak
        if total_alpha > 0 and non_latin_count / total_alpha > 0.4:
            print(f"   🗑 Non-Latin script: '{text[:50]}'")
            removed += 1
        else:
            filtered.append(seg)
    
    if removed:
        print(f"   Removed {removed} non-target script segment(s)")
    
    return filtered


def _wrap_line(text, limit=None):
    """Wrap long lines for After Effects text display"""
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