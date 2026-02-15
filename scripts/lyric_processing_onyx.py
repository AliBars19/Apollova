"""
Onyx Lyric Processing - Word-level timestamp extraction
For hybrid template: word-by-word lyrics + spinning disc

Bulletproof features:
  - Multi-pass Whisper (4 passes with escalating aggressiveness)
  - Manual regrouping for better segment splitting
  - Hallucination detection
  - Junk segment removal
  - Duration-based quality validation
  - Genius sliding window alignment
  - Word timing rebuild after alignment

Output: markers with {time, text, words[], color, end_time}
"""
import os
import json
import re
from pydub import AudioSegment
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics
from scripts.lyric_alignment import align_genius_to_whisper


def transcribe_audio_onyx(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Onyx style videos.
    
    Returns dict with:
        - markers: list of marker objects for JSX
        - total_markers: count of markers
    """
    print(f"\n✎ Onyx Transcription ({Config.WHISPER_MODEL})...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return {"markers": [], "total_markers": 0}
    
    try:
        audio_duration = _get_audio_duration(audio_path)
        print(f"  Audio duration: {audio_duration:.1f}s")
        
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        initial_prompt = _build_initial_prompt(song_title)
        
        # ============================================================
        # MULTI-PASS TRANSCRIPTION
        # ============================================================
        result = _multi_pass_transcribe(model, audio_path, initial_prompt, audio_duration)
        
        if not result or not result.segments:
            print("❌ Whisper returned no segments after all attempts")
            return {"markers": [], "total_markers": 0}
        
        # ============================================================
        # MANUAL REGROUPING (Onyx benefits from shorter segments)
        # ============================================================
        try:
            result = result.split_by_gap(0.5)
            result = result.split_by_punctuation(['.', '?', '!', ','])
            result = result.split_by_length(max_chars=50)
        except Exception as e:
            print(f"  ⚠ Regrouping failed (using defaults): {e}")
        
        # ============================================================
        # BUILD MARKERS
        # ============================================================
        markers = _build_markers_from_segments(result.segments)
        
        if not markers:
            print("❌ No valid markers generated")
            return {"markers": [], "total_markers": 0}
        
        print(f"  Raw Whisper output: {len(markers)} markers")
        
        # ============================================================
        # CLEANUP PIPELINE
        # ============================================================
        markers = _remove_hallucinations(markers, initial_prompt)
        markers = _remove_junk_markers(markers)
        markers = _remove_stutter_duplicates(markers)
        
        if not markers:
            print("❌ No markers remain after cleanup")
            return {"markers": [], "total_markers": 0}
        
        print(f"  After cleanup: {len(markers)} markers")
        
        # ============================================================
        # GENIUS ALIGNMENT
        # ============================================================
        if song_title and Config.GENIUS_API_TOKEN:
            print("✎ Fetching Genius lyrics for alignment...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                print("✎ Aligning lyrics (sliding window)...")
                markers = align_genius_to_whisper(
                    markers, genius_text, segment_text_key="text"
                )
                
                markers = _rebuild_words_after_alignment(markers)
        
        # ============================================================
        # FINAL CLEANUP
        # ============================================================
        markers = [m for m in markers if m["text"].strip()]
        _assign_colors(markers)
        _fix_marker_gaps(markers)
        
        print(f"✓ Onyx transcription complete: {len(markers)} markers")
        
        return {
            "markers": markers,
            "total_markers": len(markers)
        }
        
    except Exception as e:
        print(f"❌ Onyx transcription failed: {e}")
        raise


# ============================================================================
# MULTI-PASS WHISPER
# ============================================================================

def _multi_pass_transcribe(model, audio_path, initial_prompt, audio_duration):
    """Try multiple Whisper configs. Onyx uses regroup=False so we can manually split."""
    min_expected = max(2, int(audio_duration / 3.5))
    
    passes = [
        {
            "name": "Pass 1 (strict)",
            "params": dict(
                word_timestamps=True, vad=True, vad_threshold=0.35,
                suppress_silence=True, regroup=False,
                temperature=0, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 2 (medium)",
            "params": dict(
                word_timestamps=True, vad=True, vad_threshold=0.2,
                suppress_silence=False, regroup=False,
                temperature=0.2, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 3 (loose)",
            "params": dict(
                word_timestamps=True, vad=False,
                suppress_silence=False, regroup=False,
                temperature=0.4, initial_prompt=initial_prompt,
                condition_on_previous_text=False,
            )
        },
        {
            "name": "Pass 4 (no prompt)",
            "params": dict(
                word_timestamps=True, vad=False,
                suppress_silence=False, regroup=True,
                temperature=0.6, initial_prompt=None,
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
            
            count = sum(1 for s in result.segments if s.text.strip() and len(s.text.strip()) > 1)
            print(f"    → {count} segments")
            
            if count > best_count:
                best_count = count
                best_result = result
            
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
# MARKER BUILDING
# ============================================================================

def _build_markers_from_segments(segments):
    """Build marker objects from Whisper segments with word timing."""
    markers = []
    
    for segment in segments:
        seg_text = segment.text.strip()
        seg_start = float(segment.start)
        seg_end = float(segment.end)
        
        if not seg_text or len(seg_text) < 2:
            continue
        if seg_end - seg_start > 15:
            print(f"   ⚠ Skipping overly long segment ({seg_end - seg_start:.1f}s): {seg_text[:30]}...")
            continue
        
        words = _extract_word_timings(segment, seg_start, seg_end, seg_text)
        
        markers.append({
            "time": round(seg_start, 3),
            "text": seg_text,
            "words": words,
            "color": "",
            "end_time": round(seg_end, 3)
        })
    
    return markers


def _extract_word_timings(segment, seg_start, seg_end, seg_text):
    words = []
    
    if hasattr(segment, 'words') and segment.words:
        for word in segment.words:
            wt = word.word.strip()
            if not wt:
                continue
            ws = float(word.start)
            we = float(word.end)
            if we - ws > 5:
                we = ws + 1.0
            words.append({"word": wt, "start": round(ws, 3), "end": round(we, 3)})
    
    if not words:
        word_list = seg_text.split()
        if word_list:
            dur = seg_end - seg_start
            wd = dur / len(word_list)
            for i, w in enumerate(word_list):
                words.append({
                    "word": w,
                    "start": round(seg_start + i * wd, 3),
                    "end": round(seg_start + (i + 1) * wd, 3)
                })
    
    return words


def _rebuild_words_after_alignment(markers):
    """Rebuild word arrays with Genius text but Whisper timing."""
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
            for i, gw in enumerate(genius_words):
                new_words.append({
                    "word": gw,
                    "start": whisper_words[i]["start"],
                    "end": whisper_words[min(i, len(whisper_words) - 1)]["end"]
                })
        else:
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
        
        marker["words"] = new_words
    
    return markers


# ============================================================================
# HALLUCINATION & JUNK REMOVAL
# ============================================================================

def _remove_hallucinations(markers, initial_prompt):
    """Remove segments where Whisper hallucinated. Only kills exact prompt regurgitation."""
    patterns = [
        r"^thank\s*you\s+(for\s+)?(watching|listening)\s*\.?$",
        r"^(please\s+)?subscribe\b",
        r"^\s*music\s*\.?$",
        r"^\s*\[?\s*music\s*\]?\s*$",
        r"^\s*♪+\s*$",
        r"^subtitles?\s+by\b", r"^captions?\s+by\b",
        r"^copyright\b", r"^all\s+rights?\s+reserved",
        r"^\s*\.\.\.\s*$", r"^\s*you\s*\.?$",
    ]
    
    filtered = []
    removed = 0
    
    for m in markers:
        text = m.get("text", "").strip()
        if not text:
            continue
        tc = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower().strip()
        
        is_bad = any(_safe_search(p, tc) for p in patterns)
        
        # Only kill if segment is basically JUST the prompt (>85% match + short)
        if not is_bad and initial_prompt:
            from rapidfuzz import fuzz
            pc = re.sub(r"[^a-zA-Z0-9\s]", "", initial_prompt).lower().strip()
            similarity = fuzz.ratio(tc, pc)
            if similarity > 85 and len(tc.split()) <= len(pc.split()) + 2:
                is_bad = True
        
        if is_bad:
            print(f"   🗑 Hallucination: '{text[:60]}'")
            removed += 1
        else:
            filtered.append(m)
    
    if removed:
        print(f"   Removed {removed} hallucinated segment(s)")
    return filtered


def _safe_search(pattern, text):
    try:
        return re.search(pattern, text, re.IGNORECASE)
    except re.error:
        return False


def _remove_junk_markers(markers):
    filtered = []
    removed = 0
    
    for m in markers:
        text = m.get("text", "").strip()
        text_alpha = re.sub(r"[^a-zA-Z]", "", text)
        
        if len(text_alpha) < 2:
            removed += 1
            continue
        
        junk = [r"^[\W\s]+$", r"^(um|uh|hmm|ah|oh|ha|huh)+\s*$", r"^\.*$", r"^-+$"]
        if any(re.search(p, text.lower().strip()) for p in junk):
            removed += 1
        else:
            filtered.append(m)
    
    if removed:
        print(f"   Removed {removed} junk segment(s)")
    return filtered


def _remove_stutter_duplicates(markers):
    if len(markers) < 2:
        return markers
    
    clean = re.compile(r"[^a-zA-Z0-9\s]")
    removed = 0
    
    i = len(markers) - 1
    while i > 0:
        curr = clean.sub("", markers[i].get("text", "")).lower().strip()
        prev = clean.sub("", markers[i - 1].get("text", "")).lower().strip()
        
        if curr and prev and curr == prev:
            gap = markers[i]["time"] - markers[i - 1].get("end_time", markers[i - 1]["time"] + 2)
            if gap < 0.5:
                markers.pop(i)
                removed += 1
        i -= 1
    
    if removed:
        print(f"   Removed {removed} stutter duplicate(s)")
    return markers


# ============================================================================
# HELPERS
# ============================================================================

def _get_audio_duration(audio_path):
    try:
        return len(AudioSegment.from_file(audio_path)) / 1000.0
    except Exception:
        return 30.0


def _build_initial_prompt(song_title):
    if not song_title:
        return None
    if " - " in song_title:
        artist, track = song_title.split(" - ", 1)
        return f"{track}, {artist}."
    return f"{song_title}."


def _assign_colors(markers):
    for i, m in enumerate(markers):
        m["color"] = "white" if i % 2 == 0 else "black"


def _fix_marker_gaps(markers):
    for m in markers:
        words = m.get("words", [])
        for i in range(1, len(words)):
            if words[i]["start"] - words[i - 1]["end"] > 2.0:
                words[i]["start"] = words[i - 1]["end"] + 0.1