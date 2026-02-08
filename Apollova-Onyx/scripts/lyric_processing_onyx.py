"""
Onyx Lyric Processing - Word-level timestamp extraction
For hybrid template: word-by-word lyrics + spinning disc
"""
import os
import json
import re
from stable_whisper import load_model

from scripts.config import Config
from scripts.genius_processing import fetch_genius_lyrics


def transcribe_audio_onyx(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Onyx style videos
    
    Returns dict with:
        - markers: list of marker objects for JSX
        - Each marker has: time, text, words[], color, end_time
    """
    print(f"\n✎ Onyx Transcription ({Config.WHISPER_MODEL})...")
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print("❌ Trimmed audio not found")
        return {"markers": [], "total_markers": 0}
    
    try:
        # Load model
        os.makedirs(Config.WHISPER_CACHE_DIR, exist_ok=True)
        
        model = load_model(
            Config.WHISPER_MODEL,
            download_root=Config.WHISPER_CACHE_DIR,
            in_memory=False
        )
        
        # Build initial prompt from song title to help Whisper
        initial_prompt = None
        if song_title:
            if " - " in song_title:
                artist, track = song_title.split(" - ", 1)
                initial_prompt = f"Lyrics from the song '{track}' by {artist}."
            else:
                initial_prompt = f"Lyrics from the song '{song_title}'."
        
        # Transcribe with word-level timestamps
        result = model.transcribe(
            audio_path,
            word_timestamps=True,
            language="en",  # Force English detection
            vad=True,
            vad_threshold=0.35,
            suppress_silence=True,
            regroup=False,  # Don't auto-regroup
            temperature=0,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
        )
        
        # Manual regrouping with better segment splitting
        if result.segments:
            result = result.split_by_gap(0.5)
            result = result.split_by_punctuation(['.', '?', '!', ','])
            result = result.split_by_length(max_chars=50)
        
        # Fallback if empty
        if not result.segments:
            print("  Empty transcription, retrying with fallback params...")
            result = model.transcribe(
                audio_path,
                word_timestamps=True,
                language="en",
                vad=False,
                suppress_silence=False,
                regroup=True,
                temperature=0.3,
                initial_prompt=initial_prompt,
            )
        
        if not result.segments:
            print("❌ Whisper returned no segments")
            return {"markers": [], "total_markers": 0}
        
        # Fetch Genius lyrics for text replacement
        genius_lines = []
        if song_title and Config.GENIUS_API_TOKEN:
            print("✎ Fetching Genius lyrics for alignment...")
            genius_text = fetch_genius_lyrics(song_title)
            
            if genius_text:
                # Save reference
                genius_path = os.path.join(job_folder, "genius_lyrics.txt")
                with open(genius_path, "w", encoding="utf-8") as f:
                    f.write(genius_text)
                
                # Filter out section headers and parenthetical parts
                for ln in genius_text.splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ln.startswith("[") and ln.endswith("]"):
                        continue
                    if ln.startswith("(") and ln.endswith(")"):
                        continue
                    genius_lines.append(ln)
        
        # Build Onyx markers with word timing
        markers = []
        genius_idx = 0
        
        for seg_idx, segment in enumerate(result.segments):
            seg_start = float(segment.start)
            seg_end = float(segment.end)
            seg_text = segment.text.strip()
            
            # Skip very short or empty segments
            if not seg_text or len(seg_text) < 2:
                continue
            
            # Skip overly long segments (merge errors)
            if seg_end - seg_start > 15:
                print(f"   ⚠ Skipping overly long segment: {seg_text[:30]}...")
                continue
            
            # Try to use Genius text if available and matches
            if genius_lines and genius_idx < len(genius_lines):
                genius_text_clean = _clean_for_match(genius_lines[genius_idx])
                whisper_text_clean = _clean_for_match(seg_text)
                
                if _simple_match(whisper_text_clean, genius_text_clean):
                    seg_text = genius_lines[genius_idx]
                    genius_idx += 1
            
            # Extract word timings with validation
            words = []
            if hasattr(segment, 'words') and segment.words:
                for word in segment.words:
                    word_text = word.word.strip()
                    word_start = float(word.start)
                    word_end = float(word.end)
                    
                    # Validate word timing
                    word_duration = word_end - word_start
                    if word_duration > 5:
                        print(f"   ⚠ Fixing long word duration: '{word_text}' ({word_duration:.1f}s)")
                        word_end = word_start + min(word_duration, 1.0)
                    
                    words.append({
                        "word": word_text,
                        "start": round(word_start, 3),
                        "end": round(word_end, 3)
                    })
            else:
                # Fallback: distribute words evenly
                word_list = seg_text.split()
                if word_list:
                    duration = seg_end - seg_start
                    word_duration = duration / len(word_list)
                    for i, w in enumerate(word_list):
                        words.append({
                            "word": w,
                            "start": round(seg_start + (i * word_duration), 3),
                            "end": round(seg_start + ((i + 1) * word_duration), 3)
                        })
            
            if not words:
                continue
            
            # Recalculate segment end based on actual word timings
            actual_end = max(w["end"] for w in words)
            
            # Color alternation (white/black)
            color = "white" if len(markers) % 2 == 0 else "black"
            
            marker = {
                "time": round(seg_start, 3),
                "text": seg_text,
                "words": words,
                "color": color,
                "end_time": round(actual_end, 3)
            }
            
            markers.append(marker)
        
        # Remove consecutive duplicates
        markers = _remove_duplicate_markers(markers)
        
        # Fix timing gaps
        markers = _fix_marker_gaps(markers)
        
        print(f"✓ Onyx transcription complete: {len(markers)} markers")
        
        return {
            "markers": markers,
            "total_markers": len(markers)
        }
        
    except Exception as e:
        print(f"❌ Onyx transcription failed: {e}")
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


def _fix_marker_gaps(markers):
    """Ensure word timings don't have large unexplained gaps"""
    for marker in markers:
        words = marker.get("words", [])
        if len(words) < 2:
            continue
        
        for i in range(1, len(words)):
            prev_end = words[i-1]["end"]
            curr_start = words[i]["start"]
            gap = curr_start - prev_end
            
            if gap > 2.0:
                words[i]["start"] = prev_end + 0.1
    
    return markers
