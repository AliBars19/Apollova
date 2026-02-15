"""
Lyric Alignment Engine - Sliding window approach for matching
Whisper transcriptions to Genius lyrics.

Shared across Aurora, Mono, and Onyx templates.

Core Strategy:
  1. Whisper transcribes the audio clip → produces segments with text
  2. Genius provides the FULL song lyrics
  3. We concatenate Whisper text and find the best-matching WINDOW
     in the Genius lyrics using fuzzy matching
  4. Once the window is found, we do line-by-line alignment within it
  5. Repeated lines (choruses) are PRESERVED — not removed

This solves the fundamental problem: clips are a PORTION of the song,
so we need to find WHERE in the full lyrics the clip falls.
"""
import re
from rapidfuzz import fuzz


# ============================================================================
# PUBLIC API
# ============================================================================

def align_genius_to_whisper(whisper_segments, genius_text, segment_text_key="lyric_current"):
    """
    Align Genius lyrics to Whisper transcription segments.
    
    Works for any template — just specify which key holds the text:
      - Aurora: segment_text_key="lyric_current"
      - Mono/Onyx: segment_text_key="text"
    
    Returns modified whisper_segments with Genius text replacing Whisper text
    where good matches are found. Timing data is always preserved.
    """
    if not genius_text or not whisper_segments:
        return whisper_segments
    
    # Parse genius into lines
    genius_all_lines = [ln.strip() for ln in genius_text.splitlines() if ln.strip()]
    
    # Separate actual lyric lines from section headers & annotations
    genius_lyric_lines = [
        ln for ln in genius_all_lines
        if not _is_section_header(ln)
    ]
    
    if not genius_lyric_lines:
        print("  ⚠ No lyric lines found in Genius text")
        return whisper_segments
    
    # Count active whisper segments (non-empty)
    active_segments = [s for s in whisper_segments if s.get(segment_text_key, "").strip()]
    if not active_segments:
        return whisper_segments
    
    print(f"  Aligning {len(active_segments)} Whisper segments against {len(genius_lyric_lines)} Genius lines...")
    
    # Step 1: Find the best matching window in the full lyrics
    window_start = _find_lyrics_window(active_segments, genius_lyric_lines, segment_text_key)
    
    if window_start is None:
        print("  ⚠ Could not find matching window in Genius lyrics, using Whisper text")
        return whisper_segments
    
    # Step 2: Line-by-line alignment within the window
    whisper_segments = _align_within_window(
        whisper_segments, genius_lyric_lines, window_start, segment_text_key
    )
    
    # Step 3: Remove only Whisper artifacts (NOT legitimate repeats)
    whisper_segments = _remove_whisper_artifacts(whisper_segments, segment_text_key)
    
    return whisper_segments


# ============================================================================
# STEP 1: SLIDING WINDOW — Find where the clip falls in the full lyrics
# ============================================================================

def _find_lyrics_window(active_segments, genius_lines, segment_text_key):
    """
    Find the starting index in genius_lines where the Whisper transcription
    best matches, using a sliding window approach.
    
    Strategy:
      - Build a single text block from all Whisper segments
      - Slide a window of varying sizes across the Genius lyrics
      - Score each window position using fuzzy matching
      - Return the best-scoring start position
    """
    # Build Whisper text block
    whisper_block = " ".join(
        _clean_for_match(seg[segment_text_key])
        for seg in active_segments
    )
    
    if not whisper_block.strip():
        return None
    
    num_segs = len(active_segments)
    num_genius = len(genius_lines)
    
    # Window sizes to try: from slightly smaller to slightly larger than segment count
    # Genius lines and Whisper segments don't map 1:1, so we need flexibility
    min_window = max(1, num_segs - 4)
    max_window = min(num_genius, num_segs + 8)
    
    best_score = -1
    best_start = 0
    best_ws = 0
    
    for start in range(num_genius):
        for ws in range(min_window, max_window + 1):
            end = start + ws
            if end > num_genius:
                break
            
            genius_block = " ".join(
                _clean_for_match(genius_lines[i])
                for i in range(start, end)
            )
            
            if not genius_block:
                continue
            
            # Primary: order-sensitive ratio
            score = fuzz.ratio(whisper_block, genius_block)
            
            # Secondary: token sort for robustness against word order differences
            sort_score = fuzz.token_sort_ratio(whisper_block, genius_block)
            
            # Partial ratio helps when Whisper got a subset of the actual lyrics
            partial_score = fuzz.partial_ratio(whisper_block, genius_block)
            
            # Weighted combination
            combined = (score * 0.5) + (sort_score * 0.25) + (partial_score * 0.25)
            
            if combined > best_score:
                best_score = combined
                best_start = start
                best_ws = ws
    
    if best_score < 35:
        print(f"  ⚠ Best window match score too low: {best_score:.1f}")
        return None
    
    print(f"  ✓ Lyrics window: lines {best_start + 1}–{best_start + best_ws} (score: {best_score:.1f})")
    return best_start


# ============================================================================
# STEP 2: LINE-BY-LINE ALIGNMENT within the found window
# ============================================================================

def _align_within_window(whisper_segments, genius_lines, window_start, segment_text_key):
    """
    Line-by-line alignment between Whisper segments and Genius lines.
    
    - Allows the same Genius line to match multiple times (chorus repeats)
    - Searches forward primarily, backward for repeated sections
    - Falls back to Whisper text gracefully when no match found
    """
    min_score = 50  # Minimum fuzzy match score to accept
    
    genius_clean = [_clean_for_match(ln) for ln in genius_lines]
    
    genius_cursor = window_start
    
    # Search window sizes scale with total Genius lines
    search_ahead = min(12, max(8, len(genius_lines) // 4))
    search_back = min(20, max(10, len(genius_lines) // 3))
    
    matched = 0
    unmatched = 0
    
    for seg in whisper_segments:
        seg_text = seg.get(segment_text_key, "").strip()
        if not seg_text:
            continue
        
        whisper_clean = _clean_for_match(seg_text)
        if not whisper_clean:
            continue
        
        best_score = -1
        best_j = -1
        
        # Forward search (primary direction)
        forward_limit = min(len(genius_clean), genius_cursor + search_ahead)
        for j in range(genius_cursor, forward_limit):
            score = _match_score(whisper_clean, genius_clean[j])
            if score > best_score:
                best_score = score
                best_j = j
            if score >= 92:
                break  # Excellent match, stop searching
        
        # Backward search (for repeated sections like choruses)
        # Only if forward search didn't find a strong match
        if best_score < 70:
            back_start = max(0, genius_cursor - search_back)
            for j in range(back_start, genius_cursor):
                score = _match_score(whisper_clean, genius_clean[j])
                if score > best_score and score >= 65:
                    best_score = score
                    best_j = j
        
        # Full scan fallback — if we still have nothing decent, search everything
        if best_score < min_score:
            for j in range(len(genius_clean)):
                if j >= genius_cursor and j < forward_limit:
                    continue  # Already searched
                score = _match_score(whisper_clean, genius_clean[j])
                if score > best_score and score >= 60:
                    best_score = score
                    best_j = j
                if score >= 92:
                    break
        
        # Apply the match
        if best_score >= min_score and best_j >= 0:
            seg[segment_text_key] = genius_lines[best_j]
            if best_j >= genius_cursor:
                genius_cursor = best_j + 1
            matched += 1
        else:
            unmatched += 1
    
    print(f"  Aligned: {matched} matched, {unmatched} kept as Whisper text")
    return whisper_segments


def _match_score(whisper_clean, genius_clean):
    """
    Calculate match score between a Whisper segment and a Genius line.
    Uses multiple strategies and returns the best.
    """
    if not whisper_clean or not genius_clean:
        return 0
    
    ratio = fuzz.ratio(whisper_clean, genius_clean)
    partial = fuzz.partial_ratio(whisper_clean, genius_clean)
    token_sort = fuzz.token_sort_ratio(whisper_clean, genius_clean)
    
    # Partial ratio is critical — Whisper often captures part of a Genius line
    # or Genius has extra words (ad-libs in parentheses etc.)
    return max(ratio, partial * 0.95, token_sort * 0.9)


# ============================================================================
# STEP 3: ARTIFACT REMOVAL (NOT blanket duplicate removal)
# ============================================================================

def _remove_whisper_artifacts(segments, segment_text_key):
    """
    Remove only clear Whisper transcription artifacts:
    - Identical consecutive lines with very small time gaps (<0.5s)
    
    DOES NOT remove:
    - Chorus repeats (larger time gaps = intentional)
    - Any non-consecutive duplicates
    """
    if not segments or len(segments) < 2:
        return segments
    
    removed_count = 0
    
    for i in range(len(segments) - 1, 0, -1):
        current_text = segments[i].get(segment_text_key, "").strip()
        prev_text = segments[i - 1].get(segment_text_key, "").strip()
        
        if not current_text or not prev_text:
            continue
        
        if _clean_for_match(current_text) == _clean_for_match(prev_text):
            current_time = segments[i].get("t", segments[i].get("time", 0))
            prev_time = segments[i - 1].get("t", segments[i - 1].get("time", 0))
            prev_end = segments[i - 1].get("end_time", prev_time + 2)
            
            gap = current_time - prev_end
            
            if gap < 0.5:
                if segment_text_key == "lyric_current":
                    segments[i][segment_text_key] = ""
                else:
                    segments.pop(i)
                removed_count += 1
    
    if removed_count > 0:
        print(f"   Removed {removed_count} Whisper stutter artifacts")
    
    return segments


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _clean_for_match(text):
    """Normalize text for fuzzy matching"""
    if not text:
        return ""
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_section_header(line):
    """Check if a line is a section header like [Chorus] or (Verse 1)"""
    line = line.strip()
    if line.startswith("[") and line.endswith("]"):
        return True
    if line.startswith("(") and line.endswith(")"):
        # Only if it looks like a section marker, not an ad-lib
        inner = line[1:-1].lower()
        section_words = ["chorus", "verse", "bridge", "intro", "outro", "hook",
                         "pre-chorus", "refrain", "interlude", "break", "produced"]
        return any(w in inner for w in section_words)
    return False