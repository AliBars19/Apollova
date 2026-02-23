import os
import json
import re
from rapidfuzz import fuzz
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics


def transcribe_audio(job_folder, song_title=None):
    print(f"📝 Transcribing ({Config.WHISPER_MODEL})...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return None
    
    try:
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        result = model.transcribe(
            audio_path,
            vad=True,
            suppress_silence=False,
            regroup=True,
            temperature=0,
            word_timestamps=True,
        )

        if not result.segments:
            print("  Retrying with fallback params...")
            result = model.transcribe(
                audio_path,
                vad=False,
                suppress_silence=False,
                regroup=True,
                temperature=0.5,
                word_timestamps=True,
            )

        if not result.segments:
            print("❌ Whisper returned no segments")
            return None

        # Build segments with word-level timestamps (needed for Mono/Onyx word-by-word reveal)
        segments = []
        for seg in result.segments:
            words = []
            if hasattr(seg, "words") and seg.words:
                for w in seg.words:
                    words.append({
                        "word":  w.word.strip() if hasattr(w, "word") else str(w),
                        "start": float(w.start) if hasattr(w, "start") else float(seg.start),
                        "end":   float(w.end)   if hasattr(w, "end")   else float(seg.end),
                    })
            segments.append({
                "t":             float(seg.start),
                "end":           float(seg.end),
                "lyric_prev":    "",
                "lyric_current": seg.text.strip(),
                "lyric_next1":   "",
                "lyric_next2":   "",
                "words":         words,
            })

        
        genius_text = None
        if song_title and Config.GENIUS_API_TOKEN:
            print("🔍 Fetching Genius lyrics...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                print("🔗 Aligning...")
                segments = _align_genius_to_whisper(segments, genius_text)
                segments = _remove_duplicate_lyrics(segments)
        
        for seg in segments:
            seg["lyric_current"] = _wrap_line(seg["lyric_current"])
        
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=4, ensure_ascii=False)
        
        print(f"✓ {len(segments)} segments")
        return lyrics_path
        
    except Exception as e:
        print(f"❌ Transcription failed: {e}")
        raise


def _wrap_line(text, limit=25):
    text = text.strip()
    
    if "\\r" in text:
        return text
    
    if len(text) <= limit:
        return text
    
    cut = text.rfind(" ", 0, limit)
    if cut == -1:
        cut = limit
    
    first = text[:cut].strip()
    rest = text[cut:].strip()
    
    return f"{first} \\r {rest}"


def _align_genius_to_whisper(whisper_segments, genius_text):
    genius_lines = [
        ln.strip()
        for ln in genius_text.splitlines()
        if ln.strip() and not (ln.startswith("[") and ln.endswith("]"))
    ]
    
    if not genius_lines:
        return whisper_segments
    
    genius_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", ln).lower()
        for ln in genius_lines
    ]
    
    whisper_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", seg["lyric_current"]).lower()
        for seg in whisper_segments
    ]
    
    aligned = []
    last_idx = 0
    min_score = 65
    
    for i, w in enumerate(whisper_clean):
        if last_idx >= len(genius_clean):
            aligned.append(whisper_segments[i]["lyric_current"])
            continue
        
        best_score = -1
        best_j = last_idx
        
        search_limit = min(len(genius_clean), last_idx + 5)
        
        for j in range(last_idx, search_limit):
            score = fuzz.partial_ratio(w, genius_clean[j])
            
            if score > best_score:
                best_score = score
                best_j = j
            
            if best_score >= 90:
                break
        
        if best_score >= min_score:
            aligned.append(genius_lines[best_j])
            last_idx = best_j + 1
        else:
            aligned.append(whisper_segments[i]["lyric_current"])
    
    for i in range(min(len(whisper_segments), len(aligned))):
        whisper_segments[i]["lyric_current"] = aligned[i]
    
    whisper_segments = _remove_duplicate_lyrics(whisper_segments)
    
    return whisper_segments


def _remove_duplicate_lyrics(segments):
    if not segments:
        return segments
    
    removed_count = 0
    prev_lyric_clean = None
    
    for i in range(len(segments)):
        current_lyric = segments[i]["lyric_current"].strip()
        
        if not current_lyric:
            continue
        
        current_clean = re.sub(r"[^a-zA-Z0-9 ]+", "", current_lyric).lower().strip()
        
        if current_clean and current_clean == prev_lyric_clean:
            segments[i]["lyric_current"] = ""
            removed_count += 1
        else:
            prev_lyric_clean = current_clean
    
    if removed_count > 0:
        print(f"   Removed {removed_count} duplicates")
    
    return segments
