"""
Lyric processing for Visuals NOVA - Word-level timestamps
"""
import os
import json
import re
from rapidfuzz import fuzz
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics


def transcribe_audio_nova(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for NOVA
    Returns markers with word timing data for word-by-word reveal
    """
    print(f"\n🎵 Transcribing for NOVA (word-level)...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return None
    
    try:
        # Load Whisper model
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        # Transcribe with word timestamps
        print("  Extracting word timestamps...")
        result = model.transcribe(
            audio_path,
            vad=True,
            suppress_silence=False,
            regroup=True,
            temperature=0,
            word_timestamps=True  # KEY: Get word-level timing
        )
        
        if not result.segments:
            print("  Empty transcription, retrying with fallback...")
            result = model.transcribe(
                audio_path,
                vad=False,
                suppress_silence=False,
                regroup=True,
                temperature=0.5,
                word_timestamps=True
            )
        
        if not result.segments:
            print("❌ Whisper returned no segments")
            return None
        
        # Extract segments with word-level data
        nova_markers = []
        
        for seg in result.segments:
            # Get word timestamps from segment
            words = []
            if hasattr(seg, 'words') and seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": float(w.start),
                        "end": float(w.end)
                    })
            
            # Create marker entry
            marker = {
                "time": float(seg.start),
                "text": seg.text.strip(),
                "words": words,
                "end_time": float(seg.end)
            }
            
            nova_markers.append(marker)
        
        print(f"✓ Extracted {len(nova_markers)} segments with word timing")
        
        # Fetch and align Genius lyrics if available
        if song_title and Config.GENIUS_API_TOKEN:
            print("  Fetching Genius lyrics for alignment...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                # Save reference
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                print("  Aligning Genius lyrics to Whisper segments...")
                nova_markers = _align_genius_to_nova_markers(nova_markers, genius_text)
        
        # Remove duplicates
        nova_markers = _remove_duplicate_nova_markers(nova_markers)
        
        # Add color alternation (white/black flip)
        for i, marker in enumerate(nova_markers):
            marker["color"] = "white" if i % 2 == 0 else "black"
        
        # Save markers
        markers_path = os.path.join(job_folder, "nova_markers.json")
        with open(markers_path, "w", encoding="utf-8") as f:
            json.dump(nova_markers, f, indent=2, ensure_ascii=False)
        
        print(f"✓ NOVA markers saved: {len(nova_markers)} segments")
        return markers_path
        
    except Exception as e:
        print(f"❌ Transcription failed: {e}")
        raise


def _align_genius_to_nova_markers(nova_markers, genius_text):
    """
    Align Genius lyrics to Whisper segments while preserving word timestamps
    """
    # Parse Genius lines
    genius_lines = [
        ln.strip()
        for ln in genius_text.splitlines()
        if ln.strip() and not (ln.startswith("[") and ln.endswith("]"))
    ]
    
    if not genius_lines:
        return nova_markers
    
    # Clean for matching
    genius_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", ln).lower().strip()
        for ln in genius_lines
    ]
    
    whisper_clean = [
        re.sub(r"[^a-zA-Z0-9 ]+", " ", m["text"]).lower().strip()
        for m in nova_markers
    ]
    
    # Fuzzy match
    aligned = []
    last_idx = 0
    min_score = 65
    
    for i, w_clean in enumerate(whisper_clean):
        if last_idx >= len(genius_clean):
            # Use Whisper text
            aligned.append(nova_markers[i]["text"])
            continue
        
        # Find best match
        best_score = -1
        best_j = last_idx
        
        search_limit = min(len(genius_clean), last_idx + 5)
        
        for j in range(last_idx, search_limit):
            score = fuzz.partial_ratio(w_clean, genius_clean[j])
            
            if score > best_score:
                best_score = score
                best_j = j
            
            if best_score >= 90:
                break
        
        # Use Genius if good match
        if best_score >= min_score:
            aligned.append(genius_lines[best_j])
            last_idx = best_j + 1
        else:
            aligned.append(nova_markers[i]["text"])
    
    # Apply aligned text (keep word timestamps from Whisper)
    for i in range(min(len(nova_markers), len(aligned))):
        nova_markers[i]["text"] = aligned[i]
    
    return nova_markers


def _remove_duplicate_nova_markers(markers):
    """Remove consecutive duplicate markers"""
    if not markers:
        return markers
    
    filtered = []
    prev_clean = None
    removed = 0
    
    for marker in markers:
        text = marker["text"].strip()
        
        if not text:
            continue
        
        # Normalize
        clean = re.sub(r"[^a-zA-Z0-9 ]+", "", text).lower().strip()
        
        if clean and clean == prev_clean:
            # Duplicate - skip
            removed += 1
            continue
        
        filtered.append(marker)
        prev_clean = clean
    
    if removed > 0:
        print(f"  Removed {removed} duplicate markers")
    
    return filtered


def convert_nova_markers_to_ae_format(markers):
    """
    Convert NOVA markers to AE-compatible format for JSX injection
    Returns list of marker data for AE
    """
    ae_markers = []
    
    for marker in markers:
        ae_marker = {
            "time": marker["time"],
            "comment": json.dumps({
                "text": marker["text"],
                "words": marker["words"],
                "color": marker["color"]
            }, ensure_ascii=False)
        }
        ae_markers.append(ae_marker)
    
    return ae_markers