import os
from pathlib import Path

# Resolve the base install directory (assets/../)
# This file lives at: <install>/assets/scripts/config.py
_SCRIPTS_DIR = Path(__file__).parent          # .../assets/scripts
_ASSETS_DIR  = _SCRIPTS_DIR.parent            # .../assets
_BASE_DIR    = _ASSETS_DIR.parent             # .../  (install root)

# Load .env from install root so Genius API token etc. are picked up
try:
    from dotenv import load_dotenv
    _env_file = _BASE_DIR / ".env"
    load_dotenv(dotenv_path=str(_env_file))
except ImportError:
    pass


class Config:
    # API Settings
    GENIUS_API_TOKEN = os.getenv("GENIUS_API_TOKEN", "")
    GENIUS_BASE_URL = "https://api.genius.com"

    # Whisper Settings
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
    # Absolute path so models always land in the right place regardless of cwd
    WHISPER_CACHE_DIR = str(_BASE_DIR / "whisper_models")
    
    # Job Settings
    TOTAL_JOBS = int(os.getenv("TOTAL_JOBS", "12"))
    
    # Processing Settings
    MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
    
    # Audio Settings
    AUDIO_FORMAT = "mp3"
    TRIMMED_FORMAT = "wav"
    
    # Image Settings
    IMAGE_TARGET_SIZE = 700
    IMAGE_FORMAT = "PNG"
    COLOR_COUNT = 2
    
    # Lyric Settings
    MAX_LINE_LENGTH = 25
    
    @classmethod
    def validate(cls):
        if not cls.GENIUS_API_TOKEN:
            print("  Warning: GENIUS_API_TOKEN not set. Lyric fetching disabled.")
        
        if cls.WHISPER_MODEL not in ['tiny', 'base', 'small', 'medium', 'large-v3']:
            print(f"  Warning: Unknown WHISPER_MODEL '{cls.WHISPER_MODEL}'. Using 'small'.")
            cls.WHISPER_MODEL = 'small'
