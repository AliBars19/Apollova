import requests
import re
import json
from html import unescape

from scripts.config import Config
from scripts.image_processing import download_image


def fetch_genius_image(song_title, job_folder):
    if not Config.GENIUS_API_TOKEN:
        return None
    
    if not song_title:
        return None
    
    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    
    artist = None
    title = song_title.strip()
    if " - " in song_title:
        parts = song_title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
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
        print(f"  Genius search failed: {e}")
        return None
    
    hits = data.get("response", {}).get("hits", [])
    if not hits:
        print("  No Genius results found")
        return None
    
    song_info = hits[0]["result"]
    image_url = song_info.get("song_art_image_url") or song_info.get("header_image_url")
    
    if not image_url:
        print("  No image found in Genius result")
        return None
    
    try:
        return download_image(job_folder, image_url)
    except Exception as e:
        print(f"  Failed to download Genius image: {e}")
        return None


def fetch_genius_lyrics(song_title):
    if not Config.GENIUS_API_TOKEN:
        return None
    
    if not song_title:
        return None
    
    headers = {"Authorization": f"Bearer {Config.GENIUS_API_TOKEN}"}
    
    artist = None
    title = song_title.strip()
    if " - " in song_title:
        parts = song_title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
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
        print(f"  Genius search failed: {e}")
        return None
    
    hits = data.get("response", {}).get("hits", [])
    if not hits:
        print("  No Genius results found")
        return None
    
    url = hits[0]["result"]["url"]
    
    try:
        html = requests.get(url, timeout=10).text
    except Exception as e:
        print(f"  Failed to fetch Genius page: {e}")
        return None
    
    state_match = re.search(
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});',
        html,
        flags=re.DOTALL
    )
    
    if not state_match:
        return _fallback_html_extraction(html)
    
    try:
        state_data = json.loads(state_match.group(1))
        body_children = state_data["songPage"]["lyricsData"]["body"]["children"]
        
        full_text = _extract_text_recursive(body_children)
        
        lines = [
            ln.strip()
            for ln in full_text.splitlines()
            if ln.strip() and not (ln.startswith("[") and ln.endswith("]"))
        ]
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"  Genius JSON parsing failed: {e}")
        return _fallback_html_extraction(html)


def _extract_text_recursive(node):
    if isinstance(node, str):
        return node
    
    if isinstance(node, dict):
        pieces = [_extract_text_recursive(child) for child in node.get("children", [])]
        return "\n".join(pieces)
    
    if isinstance(node, list):
        pieces = [_extract_text_recursive(child) for child in node]
        return "\n".join(pieces)
    
    return ""


def _fallback_html_extraction(html):
    blocks = re.findall(
        r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    if not blocks:
        return None
    
    cleaned = []
    for block in blocks:
        block = re.sub(r'<br\s*/?>', '\n', block)
        block = re.sub(r'<.*?>', '', block)
        cleaned.append(block.strip())
    
    text = unescape("\n".join(cleaned))
    
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("[") and ln.endswith("]"):
            continue
        low = ln.lower()
        if "contributors" in low or "translations" in low:
            continue
        lines.append(ln)
    
    return "\n".join(lines)
