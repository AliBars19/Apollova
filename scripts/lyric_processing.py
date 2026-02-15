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
from pydub import AudioSegment
from stable_whisper import load_model

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
        
        # Load model
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        # Build context prompt
        initial_prompt = _build_initial_prompt(song_title)
        
        # ============================================================
        # MULTI-PASS TRANSCRIPTION
        # ============================================================
        result = _multi_pass_transcribe(model, audio_path, initial_prompt, audio_duration)
        
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
        
        # Wrap long lines for AE display
        for seg in segments:
            seg["lyric_current"] = _wrap_line(seg["lyric_current"])
            # These are ALWAYS empty — AE handles prev/next via expressions
            seg["lyric_prev"] = ""
            seg["lyric_next1"] = ""
            seg["lyric_next2"] = ""
            # Remove internal tracking field
            seg.pop("end_time", None)
        
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

def _multi_pass_transcribe(model, audio_path, initial_prompt, audio_duration):
    """
    Try multiple Whisper configurations, from strict to aggressive.
    Returns the best result based on segment count vs. audio duration.
    
    Pass 1: Strict — VAD on, temp=0, suppress silence (cleanest)
    Pass 2: Medium — VAD on, lower threshold, temp=0.2
    Pass 3: Loose  — VAD off, temp=0.4
    Pass 4: Nuclear — No prompt at all, temp=0.6, previous text on
    
    Stops early if we get a satisfactory number of segments.
    """
    # Expect roughly 1 segment per 3 seconds of audio
    min_expected = max(2, int(audio_duration / 3.5))
    
    passes = [
        {
            "name": "Pass 1 (strict)",
            "params": dict(
                vad=True, vad_threshold=0.35,
                suppress_silence=True, regroup=True,
                temperature=0, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 2 (medium)",
            "params": dict(
                vad=True, vad_threshold=0.2,
                suppress_silence=False, regroup=True,
                temperature=0.2, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 3 (loose)",
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=True, temperature=0.4,
                initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 4 (no prompt)",
            "params": dict(
                vad=False, suppress_silence=False,
                regroup=True, temperature=0.6,
                initial_prompt=None,
                condition_on_previous_text=True,
            )
        },
    ]
    
    best_result = None
    best_count = 0
    
    for p in passes:
        try:
            print(f"  {p['name']}...")
            result = model.transcribe(audio_path, **p["params"])
            
            if not result or not result.segments:
                print(f"    → 0 segments")
                continue
            
            # Count non-trivial segments (exclude very short text)
            count = sum(
                1 for s in result.segments
                if s.text.strip() and len(s.text.strip()) > 1
            )
            print(f"    → {count} segments")
            
            if count > best_count:
                best_count = count
                best_result = result
            
            # Good enough — stop trying
            if count >= min_expected:
                print(f"    ✓ Sufficient ({count} ≥ {min_expected} expected)")
                return result
            
        except Exception as e:
            print(f"    → Error: {e}")
            continue
    
    if best_result:
        print(f"  ⚠ Best: {best_count} segments (wanted {min_expected}+)")
    
    return best_result


# ============================================================================
# HALLUCINATION REMOVAL
# ============================================================================

def _remove_hallucinations(segments, initial_prompt):
    """
    Remove segments where Whisper hallucinated:
    - Regurgitated the initial_prompt (e.g. "Lyrics from the song...")
    - Common Whisper hallucination patterns (music tags, thank yous, etc.)
    - Segments that are suspiciously similar to the prompt
    """
    # Static hallucination patterns
    hallucination_patterns = [
        r"lyrics?\s+(from|of|to)\s+the\s+song",
        r"thank\s*you\s+(for\s+)?(watching|listening)",
        r"(please\s+)?subscribe",
        r"^\s*music\s*$",
        r"^\s*\[?\s*music\s*\]?\s*$",
        r"^\s*♪+\s*$",
        r"subtitles?\s+by",
        r"captions?\s+by",
        r"copyright\b",
        r"all\s+rights?\s+reserved",
        r"^\s*\.\.\.\s*$",
        r"^\s*you$",
    ]
    
    # Add the actual prompt text as a pattern
    if initial_prompt:
        prompt_clean = re.sub(r"[^a-zA-Z0-9\s]", "", initial_prompt).lower().strip()
        if len(prompt_clean) > 5:
            hallucination_patterns.append(re.escape(prompt_clean))
            # Also catch partial prompt matches
            for chunk in prompt_clean.split():
                if len(chunk) > 6:
                    continue  # Skip short common words
            # Catch "Lyrics from the song" style
            if "by" in prompt_clean:
                parts = prompt_clean.split("by")
                for part in parts:
                    part = part.strip()
                    if len(part) > 10:
                        hallucination_patterns.append(re.escape(part))
    
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
        
        # Also check: if the segment is very similar to the prompt itself
        if not is_hallucination and initial_prompt:
            prompt_clean_full = re.sub(r"[^a-zA-Z0-9\s]", "", initial_prompt).lower().strip()
            from rapidfuzz import fuzz
            if fuzz.ratio(text_clean, prompt_clean_full) > 70:
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
    Just artist and song name — no "Lyrics from the song" phrasing
    that Whisper loves to regurgitate.
    """
    if not song_title:
        return None
    
    if " - " in song_title:
        artist, track = song_title.split(" - ", 1)
        return f"{track}, {artist}."
    
    return f"{song_title}."


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