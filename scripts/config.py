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

    # Cloudflare Browser Rendering (optional — fallback for lyrics extraction)
    CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")

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
    
    VALID_WHISPER_MODELS = [
        'tiny', 'base', 'small', 'medium',
        'large', 'large-v2', 'large-v3',
    ]

    @classmethod
    def set_max_line_length(cls, length):
        """Override max line length (Mono uses longer lines than Aurora)."""
        cls.MAX_LINE_LENGTH = length

    @classmethod
    def validate(cls):
        """Validate config and return list of warning strings (empty = all OK)."""
        warnings = []
        if not cls.GENIUS_API_TOKEN:
            warnings.append("GENIUS_API_TOKEN not set — lyric fetching disabled.")

        if cls.WHISPER_MODEL not in cls.VALID_WHISPER_MODELS:
            warnings.append(
                f"Unknown WHISPER_MODEL '{cls.WHISPER_MODEL}'. Falling back to 'small'.")
            cls.WHISPER_MODEL = 'small'
        return warnings
