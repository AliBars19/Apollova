import os
import json
import re
from rapidfuzz import fuzz
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics


def transcribe_audio(job_folder, song_title=None):
    print(f"\n✎ Transcribing audio with Whisper ({Config.WHISPER_MODEL})...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return None
    
    try:
        # Load model
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        # Transcribe
        result = model.transcribe(
            audio_path,
            vad=True,
            suppress_silence=False,
            regroup=True,
            temperature=0,
        )
        
        # Fallback if empty
        if not result.segments:
            print("  Empty transcription, retrying with fallback params...")
            result = model.transcribe(
                audio_path,
                vad=False,
                suppress_silence=False,
                regroup=True,
                temperature=0.5,
            )
        
        if not result.segments:
            print("❌ Whisper returned no segments")
            return None
        
        # Build initial segments
        segments = [
            {
                "t": float(seg.start),
                "lyric_prev": "",
                "lyric_current": seg.text.strip(),
                "lyric_next1": "",
                "lyric_next2": ""
            }
            for seg in result.segments
        ]
        
        # Fetch and align Genius lyrics if available
        genius_text = None
        if song_title and Config.GENIUS_API_TOKEN:
            print("✎ Fetching Genius lyrics...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                # Save reference
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                # Align
                print("✎ Aligning Genius lyrics to timestamps...")
                segments = _align_genius_to_whisper(segments, genius_text)
                
                # Remove duplicate lyrics
                segments = _remove_duplicate_lyrics(segments)
        
        # Wrap long lines
        for seg in segments:
            seg["lyric_current"] = _wrap_line(seg["lyric_current"])
        
        # Save
        lyrics_path = os.path.join(job_folder, "lyrics.txt")
        with open(lyrics_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=4, ensure_ascii=False)
        
        print(f"✓ Transcription complete: {len(segments)} segments")
        return lyrics_path
        
    except Exception as e:
        print(f"❌ Transcription failed: {e}")
        raise


def _wrap_line(text, limit=25):
    text = text.strip()
    
    # Already wrapped
    if "\\r" in text:
        return text
    
    # Fits in one line
    if len(text) <= limit:
        return text
    
    # Find space to split
    cut = text.rfind(" ", 0, limit)
    if cut == -1:
        cut = limit
    
    first = text[:cut].strip()
    rest = text[cut:].strip()
    
    return f"{first} \\r {rest}"


def _align_genius_to_whisper(whisper_segments, genius_text):
    # Parse genius lines
    genius_lines = [
        ln.strip()
        for ln in genius_text.splitlines()
        if ln.strip() and not (ln.startswith("[") and ln.endswith("]"))
    ]
    
    if not genius_lines:
        return whisper_segments
    
    # Clean for matching
    genius_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", ln).lower()
        for ln in genius_lines
    ]
    
    whisper_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", seg["lyric_current"]).lower()
        for seg in whisper_segments
    ]
    
    # Fuzzy match with better duplicate prevention
    aligned = []
    last_idx = 0
    min_score = 65
    
    for i, w in enumerate(whisper_clean):
        if last_idx >= len(genius_clean):
            # No more Genius lines available, use Whisper transcription
            aligned.append(whisper_segments[i]["lyric_current"])
            continue
        
        # Find best match in remaining Genius lines
        best_score = -1
        best_j = last_idx
        
        # Only search next 5 lines to prevent skipping too far
        search_limit = min(len(genius_clean), last_idx + 5)
        
        for j in range(last_idx, search_limit):
            score = fuzz.partial_ratio(w, genius_clean[j])
            
            if score > best_score:
                best_score = score
                best_j = j
            
            # Early exit if we found excellent match
            if best_score >= 90:
                break
        
        # Only use Genius lyric if match quality is good
        if best_score >= min_score:
            aligned.append(genius_lines[best_j])
            last_idx = best_j + 1  # Advance past used line
        else:
            # Poor match, use Whisper transcription
            aligned.append(whisper_segments[i]["lyric_current"])
    
    # Apply aligned lyrics
    for i in range(min(len(whisper_segments), len(aligned))):
        whisper_segments[i]["lyric_current"] = aligned[i]
    
    # Remove consecutive duplicates
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
        
        # Normalize for comparison (remove punctuation, lowercase)
        current_clean = re.sub(r"[^a-zA-Z0-9 ]+", "", current_lyric).lower().strip()
        
        # Check if same as previous lyric
        if current_clean and current_clean == prev_lyric_clean:
            # Duplicate found - clear the lyric but keep the timestamp
            segments[i]["lyric_current"] = ""
            removed_count += 1
        else:
            # Not a duplicate - update previous
            prev_lyric_clean = current_clean
    
    if removed_count > 0:
        print(f"   Removed {removed_count} duplicate lyrics")
    
    return segments