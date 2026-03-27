#!/usr/bin/env python3
"""
Database Image URL Fixer
Fixes all entries where genius_image_url is 'fetched_from_genius'
by re-fetching the actual URL from Genius API
"""
import sqlite3
import requests
import time
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

GENIUS_API_TOKEN = os.getenv("GENIUS_API_TOKEN", "")
GENIUS_BASE_URL = "https://api.genius.com"

# Database path - adjust as needed
DB_PATH = Path(__file__).parent / "songs.db"


def get_genius_image_url(song_title):
    """Fetch the actual image URL from Genius API"""
    if not GENIUS_API_TOKEN:
        print("  ⚠ No GENIUS_API_TOKEN set")
        return None
    
    headers = {"Authorization": f"Bearer {GENIUS_API_TOKEN}"}
    
    # Parse "Artist - Song" format
    artist = None
    title = song_title.strip()
    if " - " in song_title:
        parts = song_title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
    query = f"{title} {artist}" if artist else title
    
    try:
        response = requests.get(
            f"{GENIUS_BASE_URL}/search",
            params={"q": query},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        hits = data.get("response", {}).get("hits", [])
        if not hits:
            return None
        
        song_info = hits[0]["result"]
        image_url = song_info.get("song_art_image_url") or song_info.get("header_image_url")
        
        return image_url
        
    except Exception as e:
        print(f"  ⚠ API error: {e}")
        return None


def fix_database_images(db_path=None):
    """Fix all 'fetched_from_genius' entries"""
    if db_path is None:
        db_path = DB_PATH
    
    print(f"\n🔧 Database Image URL Fixer")
    print(f"   Database: {db_path}\n")
    
    if not GENIUS_API_TOKEN:
        print("❌ Error: GENIUS_API_TOKEN not set in environment")
        print("   Create a .env file with: GENIUS_API_TOKEN=your_token_here")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Find all entries with 'fetched_from_genius'
    cursor.execute("""
        SELECT id, song_title, genius_image_url 
        FROM songs 
        WHERE genius_image_url = 'fetched_from_genius' 
           OR genius_image_url IS NULL
           OR genius_image_url = ''
    """)
    
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ No entries need fixing!")
        conn.close()
        return
    
    print(f"Found {len(rows)} entries to fix\n")
    
    fixed = 0
    failed = 0
    
    for song_id, song_title, current_url in rows:
        print(f"🎵 {song_title}")
        
        # Fetch actual URL
        actual_url = get_genius_image_url(song_title)
        
        if actual_url and actual_url != "fetched_from_genius":
            # Update database
            cursor.execute("""
                UPDATE songs 
                SET genius_image_url = ? 
                WHERE id = ?
            """, (actual_url, song_id))
            conn.commit()
            
            print(f"   ✅ Updated: {actual_url[:60]}...")
            fixed += 1
        else:
            print(f"   ❌ Could not find image URL")
            failed += 1
        
        # Rate limiting - be nice to the API
        time.sleep(0.5)
    
    conn.close()
    
    print(f"\n{'='*50}")
    print(f"✅ Fixed: {fixed}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total processed: {len(rows)}")


def show_current_status(db_path=None):
    """Show current status of image URLs"""
    if db_path is None:
        db_path = DB_PATH
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM songs")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM songs WHERE genius_image_url = 'fetched_from_genius'")
    placeholder = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM songs WHERE genius_image_url IS NULL OR genius_image_url = ''")
    empty = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM songs WHERE genius_image_url NOT IN ('fetched_from_genius', '') AND genius_image_url IS NOT NULL")
    valid = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"\n📊 Database Image URL Status")
    print(f"   Total songs: {total}")
    print(f"   ✅ Valid URLs: {valid}")
    print(f"   ⚠️  Placeholder ('fetched_from_genius'): {placeholder}")
    print(f"   ❌ Empty/NULL: {empty}")
    print()


if __name__ == "__main__":
    import sys
    
    # Allow passing custom database path
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        db_path = DB_PATH
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print(f"   Usage: python fix_image_urls.py [path/to/songs.db]")
        sys.exit(1)
    
    show_current_status(db_path)
    
    response = input("Fix all placeholder URLs? (y/N): ").strip().lower()
    if response == 'y':
        fix_database_images(db_path)
        print("\n")
        show_current_status(db_path)
    else:
        print("Cancelled.")