#!/usr/bin/env python3
"""
🧹 Wipe All Lyrics - One-Time Script
Clears all lyrics columns from the database so every song
gets re-transcribed with the improved alignment engine.

Preserves: URLs, timestamps, colors, beats, use_count
Clears: transcribed_lyrics, mono_lyrics, onyx_lyrics

Run from the Apollova root directory:
  python wipe_lyrics.py
"""
import sqlite3
import os
from pathlib import Path

# Find the database
DB_PATH = Path(__file__).parent / "songs.db"

if not DB_PATH.exists():
    print(f"❌ Database not found at: {DB_PATH}")
    print("   Make sure you run this from the Apollova root directory.")
    exit(1)

# Show current state
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM songs")
total = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM songs WHERE transcribed_lyrics IS NOT NULL")
aurora_count = cursor.fetchone()[0]

try:
    cursor.execute("SELECT COUNT(*) FROM songs WHERE mono_lyrics IS NOT NULL")
    mono_count = cursor.fetchone()[0]
except:
    mono_count = 0

try:
    cursor.execute("SELECT COUNT(*) FROM songs WHERE onyx_lyrics IS NOT NULL")
    onyx_count = cursor.fetchone()[0]
except:
    onyx_count = 0

conn.close()

print(f"\n🗃️  Database: {DB_PATH}")
print(f"   Total songs: {total}")
print(f"   Aurora lyrics cached: {aurora_count}")
print(f"   Mono lyrics cached:  {mono_count}")
print(f"   Onyx lyrics cached:  {onyx_count}")
print()
print("⚠️  This will clear ALL lyrics from ALL templates.")
print("   URLs, timestamps, colors, beats, and use_count will be preserved.")
print()

response = input("Are you sure? Type 'yes' to confirm: ").strip().lower()

if response != 'yes':
    print("Cancelled.")
    exit(0)

# Wipe lyrics
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

cursor.execute("""
    UPDATE songs 
    SET transcribed_lyrics = NULL,
        mono_lyrics = NULL,
        onyx_lyrics = NULL
""")

wiped = cursor.rowcount
conn.commit()
conn.close()

print(f"\n✅ Wiped lyrics for {wiped} songs.")
print("   Next time you run any main.py, songs will be re-transcribed")
print("   with the improved sliding window alignment.\n")