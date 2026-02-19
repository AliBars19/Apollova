"""
Genius Processing - Bulletproof lyrics and image fetching from Genius API
Shared across Aurora, Mono, and Onyx templates

Extraction strategy (triple-layer):
  1. __PRELOADED_STATE__ JSON (fastest, most reliable when available)
  2. BeautifulSoup HTML parsing (data-lyrics-container divs)
  3. Regex fallback (last resort for unusual page structures)
"""
import requests
import re
import json
from html import unescape

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("  ⚠ beautifulsoup4 not installed. Install with: pip install beautifulsoup4")
    print("    Falling back to regex-based extraction (less reliable)")

from scripts.config import Config


# ============================================================================
# Browser-like headers to prevent Genius from blocking or serving different HTML
# ============================================================================
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


# ============================================================================
# PUBLIC API: fetch_genius_image
# ============================================================================
def fetch_genius_image(song_title, job_folder):
    """Fetch album art image from Genius for a given song title"""
    # Import here to avoid circular imports (only Aurora/Onyx need this)
    from scripts.image_processing import download_image
    
    if not Config.GENIUS_API_TOKEN or not song_title:
        return None
    
    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    artist, title = _parse_song_title(song_title)
    query = f"{title} {artist}" if artist else title
    
    try:
        response = requests.get(
            f"{Config.GENIUS_BASE_URL}/search",
            params={"q": query},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  Genius image search failed: {e}")
        return None
    
    hits = data.get("response", {}).get("hits", [])
    if not hits:
        print("  No Genius results found for image")
        return None
    
    best_hit = _find_best_hit(hits, artist, title)
    song_info = best_hit["result"]
    image_url = song_info.get("song_art_image_url") or song_info.get("header_image_url")
    
    if not image_url:
        print("  No image found in Genius result")
        return None
    
    try:
        return download_image(job_folder, image_url)
    except Exception as e:
        print(f"  Failed to download Genius image: {e}")
        return None


# ============================================================================
# PUBLIC API: fetch_genius_lyrics
# ============================================================================
def fetch_genius_lyrics(song_title):
    """
    Fetch full song lyrics from Genius.
    
    Returns the COMPLETE lyrics as a string with newlines, including section
    headers like [Chorus], [Verse 1] etc. These are useful for alignment.
    
    Returns None if lyrics cannot be fetched.
    """
    if not Config.GENIUS_API_TOKEN or not song_title:
        return None
    
    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    artist, title = _parse_song_title(song_title)
    
    # Try multiple search queries for better hit rate
    queries = []
    if artist:
        queries.append(f"{title} {artist}")
        queries.append(f"{artist} {title}")
    queries.append(title)
    
    url = None
    for query in queries:
        try:
            response = requests.get(
                f"{Config.GENIUS_BASE_URL}/search",
                params={"q": query},
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            hits = data.get("response", {}).get("hits", [])
            if hits:
                # Try to find best match - prefer exact artist match
                best_hit = _find_best_hit(hits, artist, title)
                url = best_hit["result"]["url"]
                print(f"  Genius match: {best_hit['result'].get('full_title', 'Unknown')}")
                break
        except Exception as e:
            print(f"  Genius search failed for '{query}': {e}")
            continue
    
    if not url:
        print("  No Genius results found")
        return None
    
    # Fetch lyrics page with browser headers
    try:
        html = requests.get(url, headers=BROWSER_HEADERS, timeout=15).text
    except Exception as e:
        print(f"  Failed to fetch Genius page: {e}")
        return None
    
    # Triple-layer extraction
    lyrics = _extract_from_preloaded_state(html)
    
    if not lyrics:
        print("  Method 1 (JSON) failed, trying BeautifulSoup...")
        lyrics = _extract_with_beautifulsoup(html)
    
    if not lyrics:
        print("  Method 2 (BS4) failed, trying regex fallback...")
        lyrics = _extract_with_regex(html)
    
    if not lyrics:
        print("  ❌ All extraction methods failed")
        return None
    
    # Clean up the extracted lyrics
    lyrics = _clean_lyrics(lyrics)
    
    if lyrics:
        line_count = len([l for l in lyrics.splitlines() if l.strip()])
        print(f"  ✓ Genius lyrics fetched: {line_count} lines")
    
    return lyrics


# ============================================================================
# EXTRACTION METHOD 1: __PRELOADED_STATE__ JSON
# ============================================================================
def _extract_from_preloaded_state(html):
    """Extract lyrics from the embedded JSON state object"""
    # Try multiple patterns as Genius changes their JS variable names
    patterns = [
        r'window\.__PRELOADED_STATE__\s*=\s*JSON\.parse\(\'(.*?)\'\);',
        r'window\.__PRELOADED_STATE__\s*=\s*JSON\.parse\("(.*?)"\);',
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.DOTALL)
        if match:
            try:
                raw = match.group(1)
                
                # Handle escaped JSON string (from JSON.parse)
                if pattern.startswith(r'window\.__PRELOADED_STATE__\s*=\s*JSON\.parse'):
                    # Unescape the string
                    raw = raw.replace("\\'", "'")
                    raw = raw.replace('\\"', '"')
                    raw = raw.replace('\\\\', '\\')
                    raw = raw.encode().decode('unicode_escape')
                
                state_data = json.loads(raw)
                
                # Try multiple paths through the JSON structure
                lyrics_text = _traverse_state_for_lyrics(state_data)
                if lyrics_text and len(lyrics_text.strip()) > 10:
                    return lyrics_text
                    
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as e:
                continue
    
    return None


def _traverse_state_for_lyrics(state_data):
    """Try multiple JSON paths to find lyrics data"""
    # Path variations Genius has used over time
    paths_to_try = [
        # Current (2024-2025)
        lambda d: d["songPage"]["lyricsData"]["body"]["children"],
        # Alternative current
        lambda d: d["songPage"]["lyricsData"]["body"],
        # Older format
        lambda d: d["entities"]["songs"][list(d["entities"]["songs"].keys())[0]]["lyrics"]["body"]["children"],
        # Another variant
        lambda d: d["songPage"]["lyrics"]["body"]["children"],
    ]
    
    for path_fn in paths_to_try:
        try:
            node = path_fn(state_data)
            text = _extract_text_recursive(node)
            if text and len(text.strip()) > 10:
                return text
        except (KeyError, IndexError, TypeError):
            continue
    
    return None


def _extract_text_recursive(node):
    """Recursively extract text from Genius JSON lyrics structure"""
    if isinstance(node, str):
        return node
    
    if isinstance(node, dict):
        tag = node.get("tag", "")
        children = node.get("children", [])
        
        pieces = []
        for child in children:
            piece = _extract_text_recursive(child)
            if piece:
                pieces.append(piece)
        
        result = ""
        if tag == "br":
            result = "\n"
        elif tag in ("p", "div"):
            result = "\n".join(pieces) + "\n"
        else:
            result = "".join(pieces)
        
        return result
    
    if isinstance(node, list):
        pieces = []
        for child in node:
            piece = _extract_text_recursive(child)
            if piece:
                pieces.append(piece)
        return "\n".join(pieces)
    
    return ""


# ============================================================================
# EXTRACTION METHOD 2: BeautifulSoup HTML parsing
# ============================================================================
def _extract_with_beautifulsoup(html):
    """Extract lyrics using BeautifulSoup for robust HTML parsing"""
    if not HAS_BS4:
        return None
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Primary: Find lyrics containers
        containers = soup.find_all("div", attrs={"data-lyrics-container": "true"})
        
        if not containers:
            # Fallback: Try class-based selectors Genius has used
            containers = soup.find_all("div", class_=re.compile(r"Lyrics__Container"))
        
        if not containers:
            # Another fallback: look for the lyrics root
            containers = soup.find_all("div", class_=re.compile(r"lyrics"))
        
        if not containers:
            return None
        
        lyrics_parts = []
        for container in containers:
            # Replace <br> tags with newlines before getting text
            for br in container.find_all("br"):
                br.replace_with("\n")
            
            text = container.get_text(separator="")
            if text.strip():
                lyrics_parts.append(text.strip())
        
        if not lyrics_parts:
            return None
        
        return "\n".join(lyrics_parts)
        
    except Exception as e:
        print(f"  BS4 extraction error: {e}")
        return None


# ============================================================================
# EXTRACTION METHOD 3: Regex fallback
# ============================================================================
def _extract_with_regex(html):
    """Last-resort regex extraction"""
    # Find all lyrics container divs
    blocks = re.findall(
        r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    if not blocks:
        # Try class-based pattern
        blocks = re.findall(
            r'<div[^>]+class="[^"]*Lyrics__Container[^"]*"[^>]*>(.*?)</div>',
            html,
            flags=re.DOTALL | re.IGNORECASE
        )
    
    if not blocks:
        return None
    
    cleaned = []
    for block in blocks:
        # Replace <br> with newlines
        block = re.sub(r'<br\s*/?>', '\n', block)
        # Remove all HTML tags
        block = re.sub(r'<.*?>', '', block, flags=re.DOTALL)
        # Unescape HTML entities
        block = unescape(block)
        if block.strip():
            cleaned.append(block.strip())
    
    if not cleaned:
        return None
    
    return "\n".join(cleaned)


# ============================================================================
# LYRICS CLEANUP
# ============================================================================
def _clean_lyrics(text):
    """
    Clean extracted lyrics text.
    
    IMPORTANT: We keep section headers like [Chorus], [Verse 1] etc.
    These help the alignment algorithm understand song structure.
    We only remove metadata/junk lines.
    """
    if not text:
        return None
    
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            lines.append("")  # Preserve blank lines (section breaks)
            continue
        
        # Skip known metadata/junk lines
        lower = ln.lower()
        skip_patterns = [
            "contributors",
            "translations",
            "embed",
            "you might also like",
            "see .* live",
            r"^\d+$",  # Just numbers
            "genius",
        ]
        
        should_skip = False
        for pattern in skip_patterns:
            if re.search(pattern, lower):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        lines.append(ln)
    
    # Remove leading/trailing blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    
    result = "\n".join(lines)
    
    # Remove excessive blank lines (more than 2 consecutive)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result if result.strip() else None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def _parse_song_title(song_title):
    """Parse 'Artist - Song' format, returns (artist, title)"""
    artist = None
    title = song_title.strip()
    
    if " - " in song_title:
        parts = song_title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
    return artist, title


def _find_best_hit(hits, artist, title):
    """
    Find the best matching hit from Genius search results.
    
    Priorities:
      1. Exact artist match + NOT a translation
      2. Artist in full title + NOT a translation
      3. Any non-translation result
      4. First result (last resort)
    
    Filters out translations (Türkçe Çeviri, Tradução, Traduction, etc.)
    which Genius sometimes ranks higher than the original.
    """
    # Translation indicators in Genius result titles
    translation_markers = [
        "türkçe çeviri", "tradução", "traduction", "traducción",
        "перевод", "översättning", "übersetzung", "terjemahan",
        "翻訳", "번역", "traduzione", "vertaling",
        "genius türkçe", "genius brasil", "genius traductions",
        "genius traducciones", "genius traduções",
    ]
    
    def _is_translation(hit):
        full_title = hit["result"].get("full_title", "").lower()
        primary_artist = hit["result"].get("primary_artist", {}).get("name", "").lower()
        # Check title and artist for translation markers
        for marker in translation_markers:
            if marker in full_title or marker in primary_artist:
                return True
        return False
    
    # Split hits into originals and translations
    originals = [h for h in hits if not _is_translation(h)]
    
    # If no originals found, use all hits (better than nothing)
    pool = originals if originals else hits
    
    if not artist:
        return pool[0]
    
    artist_lower = artist.lower()
    
    # First pass: exact artist match in non-translations
    for hit in pool:
        result = hit["result"]
        primary_artist = result.get("primary_artist", {}).get("name", "").lower()
        
        if artist_lower in primary_artist or primary_artist in artist_lower:
            return hit
    
    # Second pass: artist mentioned in full title of non-translations
    for hit in pool:
        result = hit["result"]
        full_title = result.get("full_title", "").lower()
        
        if artist_lower in full_title:
            return hit
    
    # Third pass: title match in non-translations
    title_lower = title.lower() if title else ""
    for hit in pool:
        result = hit["result"]
        hit_title = result.get("title", "").lower()
        
        if title_lower in hit_title or hit_title in title_lower:
            return hit
    
    # Default to first non-translation (or first overall)
    return pool[0]