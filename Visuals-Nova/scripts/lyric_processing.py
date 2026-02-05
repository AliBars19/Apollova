"""
Nova Lyric Processing - Word-level timestamp extraction
For minimal text-only lyric videos with word-by-word reveal
"""
import os
import json
import re
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics


def transcribe_audio_nova(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Nova style videos
    
    Returns dict with:
        - markers: list of marker objects for JSX
        - Each marker has: time, text, words[], color, end_time
    """
    print(f"\n✎ Nova Transcription ({Config.WHISPER_MODEL})...")
    
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
        
        # Transcribe with word-level timestamps
        result = model.transcribe(
            audio_path,
            word_timestamps=True,  # Critical for Nova word-by-word
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
                word_timestamps=True,
                vad=False,
                suppress_silence=False,
                regroup=True,
                temperature=0.5,
            )
        
        if not result.segments:
            print("❌ Whisper returned no segments")
            return {"markers": []}
        
        # Fetch Genius lyrics for text replacement (optional)
        genius_lines = []
        if song_title and Config.GENIUS_API_TOKEN:
            print("✎ Fetching Genius lyrics for alignment...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                # Save reference
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                genius_lines = [
                    ln.strip()
                    for ln in genius_text.splitlines()
                    if ln.strip() and not (ln.startswith("[") and ln.endswith("]"))
                ]
        
        # Build Nova markers
        markers = []
        genius_idx = 0
        
        for seg_idx, segment in enumerate(result.segments):
            # Get segment text and timing
            seg_start = float(segment.start)
            seg_end = float(segment.end)
            seg_text = segment.text.strip()
            
            # Try to use Genius text if available and matches
            if genius_lines and genius_idx < len(genius_lines):
                genius_text_clean = _clean_for_match(genius_lines[genius_idx])
                whisper_text_clean = _clean_for_match(seg_text)
                
                # Simple fuzzy match
                if _simple_match(whisper_text_clean, genius_text_clean):
                    seg_text = genius_lines[genius_idx]
                    genius_idx += 1
            
            # Extract word timings
            words = []
            if hasattr(segment, 'words') and segment.words:
                for word in segment.words:
                    words.append({
                        "word": word.word.strip(),
                        "start": float(word.start),
                        "end": float(word.end)
                    })
            else:
                # Fallback: distribute words evenly across segment
                word_list = seg_text.split()
                if word_list:
                    duration = seg_end - seg_start
                    word_duration = duration / len(word_list)
                    for i, w in enumerate(word_list):
                        words.append({
                            "word": w,
                            "start": seg_start + (i * word_duration),
                            "end": seg_start + ((i + 1) * word_duration)
                        })
            
            # Determine color (alternating white/black based on marker index)
            color = "white" if seg_idx % 2 == 0 else "black"
            
            marker = {
                "time": seg_start,
                "text": seg_text,
                "words": words,
                "color": color,
                "end_time": seg_end
            }
            
            markers.append(marker)
        
        # Remove consecutive duplicates
        markers = _remove_duplicate_markers(markers)
        
        print(f"✓ Nova transcription complete: {len(markers)} markers")
        
        return {
            "markers": markers,
            "total_markers": len(markers)
        }
        
    except Exception as e:
        print(f"❌ Nova transcription failed: {e}")
        raise


def _clean_for_match(text):
    """Clean text for fuzzy matching"""
    return re.sub(r"[^a-zA-Z0-9 ]+", "", text).lower().strip()


def _simple_match(a, b, threshold=0.6):
    """Simple word overlap matching"""
    words_a = set(a.split())
    words_b = set(b.split())
    
    if not words_a or not words_b:
        return False
    
    overlap = len(words_a & words_b)
    max_len = max(len(words_a), len(words_b))
    
    return (overlap / max_len) >= threshold


def _remove_duplicate_markers(markers):
    """Remove consecutive duplicate text markers"""
    if not markers:
        return markers
    
    filtered = [markers[0]]
    prev_text_clean = _clean_for_match(markers[0]["text"])
    
    for marker in markers[1:]:
        current_text_clean = _clean_for_match(marker["text"])
        
        if current_text_clean != prev_text_clean:
            filtered.append(marker)
            prev_text_clean = current_text_clean
    
    removed = len(markers) - len(filtered)
    if removed > 0:
        print(f"   Removed {removed} duplicate markers")
    
    return filtered