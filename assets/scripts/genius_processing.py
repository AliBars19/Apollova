"""
Genius Processing - Bulletproof lyrics and image fetching from Genius API
Shared across Aurora, Mono, and Onyx templates

Extraction strategy (quad-layer):
  1. __PRELOADED_STATE__ JSON (fastest, most reliable when available)
  2. BeautifulSoup HTML parsing (data-lyrics-container divs)
  3. Regex fallback (for unusual page structures)
  4. Cloudflare Browser Rendering /scrape (optional, for JS-rendered pages)
"""
import random
import time

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
# #16: Rotating User-Agent to prevent Genius from blocking
# ============================================================================
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _browser_headers():
    """Return browser-like headers with a randomly picked User-Agent (#16)."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


# ============================================================================
# #15: Retry helper for Genius API requests
# ============================================================================
def _request_with_retry(method, url, retries=2, backoff=1.0, **kwargs):
    """
    Wrapper around requests with retry on connection errors and 5xx.
    #15: 2 retries, 1s backoff, only on transient failures.
    """
    kwargs.setdefault("timeout", 10)
    last_exc = None
    for attempt in range(1 + retries):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code < 500:
                return resp
            # 5xx — retry
            last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
        if attempt < retries:
            time.sleep(backoff)
    raise last_exc


# ============================================================================
# PUBLIC API: fetch_genius_image
# ============================================================================
def _collect_image_candidates(hits: list) -> list:
    """Pull every unique image URL from search hits, in Genius's ranking order."""
    candidates = []
    for hit in hits:
        result = hit.get("result", {})
        for key in ("song_art_image_url", "header_image_url",
                    "song_art_image_thumbnail_url"):
            url = result.get(key)
            if url and url not in candidates:
                candidates.append(url)
    return candidates


def _pick_vibrant_candidate(candidates: list, job_folder: str,
                            skip_url: str = None) -> tuple:
    """Try each candidate URL in order, return first one that passes the
    vibrancy gate. Falls back to the highest-scoring candidate if none pass.

    Returns (image_path, chosen_url, info_dict) or (None, None, {}) on failure.
    """
    from scripts.image_processing import download_image, is_image_vibrant

    best_path = None
    best_url = None
    best_info: dict = {}
    best_score = -1.0

    for url in candidates:
        if skip_url and url == skip_url:
            continue
        try:
            path = download_image(job_folder, url)
        except Exception as e:
            print(f"  Skipping candidate (download failed): {e}")
            continue

        ok, info = is_image_vibrant(path)
        if ok:
            print(f"  ✓ Vibrant cover accepted: {info.get('reason', '')}")
            return path, url, info

        # Track the best non-vibrant candidate as a fallback. Score = mean_sat
        # (higher = closer to passing the gate).
        score = info.get("mean_saturation", 0.0)
        print(f"  ✗ Rejected: {info.get('reason', 'unknown')}")
        if score > best_score:
            best_score = score
            best_path = path
            best_url = url
            best_info = info

    if best_path:
        print(f"  ⚠ No vibrant candidate found — falling back to best ({best_info.get('reason')})")
        return best_path, best_url, best_info

    return None, None, {}


def fetch_genius_image(song_title, job_folder):
    """Fetch album art from Genius, walking through candidates until one passes
    the vibrancy gate (saturation, channel spread, chroma spread). Falls back
    to the most-saturated candidate if none pass."""
    if not Config.GENIUS_API_TOKEN or not song_title:
        return None

    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    artist, title = _parse_song_title(song_title)
    query = f"{title} {artist}" if artist else title

    try:
        response = _request_with_retry(
            "GET", f"{Config.GENIUS_BASE_URL}/search",
            params={"q": query},
            headers=headers,
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

    # Order candidates: best-hit's images first, then everything else
    best_hit = _find_best_hit(hits, artist, title)
    ordered_hits = [best_hit] + [h for h in hits if h is not best_hit]
    candidates = _collect_image_candidates(ordered_hits)

    if not candidates:
        print("  No image candidates found")
        return None

    path, _, _ = _pick_vibrant_candidate(candidates, job_folder)
    return path


# ============================================================================
# PUBLIC API: fetch_genius_image_rotated
# ============================================================================
def fetch_genius_image_rotated(song_title, job_folder, current_url=None):
    """Fetch an alternative cover from Genius, walking through candidates until
    one passes the vibrancy gate. Skips current_url so the result differs from
    the cached one. Falls back to the most-saturated candidate if none pass.

    Returns (image_path, chosen_url) tuple, or (None, None) on failure.
    """
    if not Config.GENIUS_API_TOKEN or not song_title:
        return None, None

    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    artist, title = _parse_song_title(song_title)
    query = f"{title} {artist}" if artist else title

    try:
        response = _request_with_retry(
            "GET", f"{Config.GENIUS_BASE_URL}/search",
            params={"q": query},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  Genius image rotation search failed: {e}")
        return None, None

    hits = data.get("response", {}).get("hits", [])
    if not hits:
        print("  No Genius results found for image rotation")
        return None, None

    candidates = _collect_image_candidates(hits)
    if not candidates:
        print("  No image candidates found")
        return None, None

    # Shuffle alternatives so we don't always re-pick the same one when
    # multiple candidates pass the gate
    alternatives = [u for u in candidates if u != current_url]
    if not alternatives:
        alternatives = candidates  # All match current — accept anything
    random.shuffle(alternatives)

    path, chosen, _ = _pick_vibrant_candidate(alternatives, job_folder)
    if path:
        return path, chosen
    return None, None


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
            response = _request_with_retry(
                "GET", f"{Config.GENIUS_BASE_URL}/search",
                params={"q": query},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            hits = data.get("response", {}).get("hits", [])
            if hits:
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
    
    # Fetch lyrics page with rotating browser headers (#16)
    try:
        html = _request_with_retry("GET", url, headers=_browser_headers(), timeout=15).text
    except Exception as e:
        print(f"  Failed to fetch Genius page: {e}")
        return None
    
    # Quad-layer extraction
    lyrics = _extract_from_preloaded_state(html)
    
    if not lyrics:
        print("  Method 1 (JSON) failed, trying BeautifulSoup...")
        lyrics = _extract_with_beautifulsoup(html)
    
    if not lyrics:
        print("  Method 2 (BS4) failed, trying regex fallback...")
        lyrics = _extract_with_regex(html)
    
    if not lyrics and _has_cloudflare_config():
        print("  Method 3 (regex) failed, trying Cloudflare /scrape...")
        lyrics = _extract_with_cloudflare(url)

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
# EXTRACTION METHOD 4: Cloudflare Browser Rendering /scrape
# ============================================================================
def _has_cloudflare_config():
    """Check if Cloudflare Browser Rendering credentials are configured."""
    return bool(Config.CLOUDFLARE_ACCOUNT_ID and Config.CLOUDFLARE_API_TOKEN)


def _extract_with_cloudflare(url):
    """
    Use Cloudflare Browser Rendering /scrape to extract lyrics from a
    fully JS-rendered Genius page.

    Only called when methods 1-3 fail AND Cloudflare credentials are set.
    The /scrape endpoint is synchronous — it renders the page in a headless
    browser and returns the content of matched CSS selectors.
    """
    if not _has_cloudflare_config():
        return None

    scrape_url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{Config.CLOUDFLARE_ACCOUNT_ID}/browser-rendering/scrape"
    )

    payload = {
        "url": url,
        "elements": [
            {
                "selector": "[data-lyrics-container='true']",
            }
        ],
        "wait_for": {
            "selector": "[data-lyrics-container='true']",
            "timeout": 10000,
        },
    }

    headers = {
        "Authorization": f"Bearer {Config.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(scrape_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Cloudflare /scrape request failed: {e}")
        return None

    if not data.get("success"):
        errors = data.get("errors", [])
        print(f"  Cloudflare /scrape API error: {errors}")
        return None

    # Extract text from each matched element
    result = data.get("result", {})
    elements = result.get("elements", [])
    if not elements:
        print("  Cloudflare /scrape: no lyrics containers found")
        return None

    lyrics_parts = []
    for element_group in elements:
        results_list = element_group.get("results", [])
        for item in results_list:
            # Prefer rendered text; fall back to parsing the HTML
            text = item.get("text", "")
            if not text and item.get("html"):
                text = _cloudflare_html_to_text(item["html"])
            if text and text.strip():
                lyrics_parts.append(text.strip())

    if not lyrics_parts:
        print("  Cloudflare /scrape: elements matched but no text extracted")
        return None

    return "\n".join(lyrics_parts)


def _cloudflare_html_to_text(html_fragment):
    """Convert an HTML fragment from Cloudflare into plain text with newlines."""
    # Replace <br> with newlines
    text = re.sub(r'<br\s*/?>', '\n', html_fragment)
    # Remove all remaining HTML tags
    text = re.sub(r'<.*?>', '', text, flags=re.DOTALL)
    # Unescape HTML entities
    text = unescape(text)
    return text


# ============================================================================
# TEXT NORMALIZATION HELPERS
# ============================================================================

def _fix_mojibake(text: str) -> str:
    """
    Repair UTF-8 text that was incorrectly decoded as Latin-1.
    Common in Genius scraping: 'â€"' -> '—', 'â€™' -> ''', etc.
    Returns the original text unchanged if repair fails or isn't needed.
    """
    try:
        repaired = text.encode('latin-1').decode('utf-8')
        if repaired != text:
            return repaired
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return text


_CYRILLIC_TO_LATIN: dict[str, str] = {
    '\u0430': 'a', '\u0435': 'e', '\u043e': 'o', '\u0440': 'p',
    '\u0441': 'c', '\u0443': 'y', '\u0445': 'x',
    '\u0410': 'A', '\u0412': 'B', '\u0415': 'E', '\u041a': 'K',
    '\u041c': 'M', '\u041d': 'H', '\u041e': 'O', '\u0420': 'P',
    '\u0421': 'C', '\u0422': 'T', '\u0423': 'Y', '\u0425': 'X',
}


def _normalize_homoglyphs(text: str) -> str:
    """
    Replace Cyrillic lookalike characters with Latin equivalents.
    Only applied when the line is predominantly Latin (>80% Latin alpha chars),
    so actual Cyrillic lyrics are not modified.
    """
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return text
    latin_count = sum(1 for c in alpha_chars if ord(c) < 0x0250)
    if latin_count / len(alpha_chars) <= 0.80:
        return text
    return "".join(_CYRILLIC_TO_LATIN.get(c, c) for c in text)


_ARTIST_TITLE_RE = re.compile(
    r"^[A-Z][\w\s&+.'\u2019]+ - [A-Z][\w\s&+.'\u2019()]+$"
)


def _is_artist_title_line(line: str) -> bool:
    """Detect 'Artist - Song Title' metadata lines from Genius related-songs sections."""
    stripped = line.strip()
    if ' - ' not in stripped or '\u2014' in stripped:
        return False
    return bool(_ARTIST_TITLE_RE.match(stripped))


def _remove_consecutive_artist_titles(lines: list[str]) -> list[str]:
    """Remove runs of 2+ consecutive 'Artist - Title' lines."""
    result: list[str] = []
    run: list[str] = []
    for ln in lines:
        if ln and _is_artist_title_line(ln):
            run.append(ln)
        else:
            if len(run) < 2:
                result.extend(run)
            run = []
            result.append(ln)
    if len(run) < 2:
        result.extend(run)
    return result


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

    # Pre-clean: fix encoding issues on the entire block
    text = _fix_mojibake(text)

    lines = []
    after_ymal = False  # "you might also like" flag

    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            lines.append("")  # Preserve blank lines (section breaks)
            after_ymal = False
            continue

        # Normalize Cyrillic homoglyphs per line
        ln = _normalize_homoglyphs(ln)

        # Skip known metadata/junk lines
        lower = ln.lower()
        skip_patterns = [
            "contributors",
            "translations",
            "embed",
            "you might also like",
            r"^see\s+.*\s+live\s*$",  # #6: Anchored — only whole-line "See X Live"
            r"^\d+$",                  # Just numbers
            r"^\s*genius\s*$",         # #6: Whole-line only — don't strip lyrics containing "genius"
        ]

        should_skip = False
        for pattern in skip_patterns:
            if re.search(pattern, lower):
                should_skip = True
                if "you might also like" in lower:
                    after_ymal = True
                break

        if should_skip:
            continue

        # After "you might also like", skip artist-title metadata lines
        if after_ymal and _is_artist_title_line(ln):
            continue
        after_ymal = False  # non-matching line resets

        lines.append(ln)

    # Second pass: remove runs of 2+ consecutive artist-title lines
    lines = _remove_consecutive_artist_titles(lines)

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