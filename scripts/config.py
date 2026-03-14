"""
Shared Configuration - Used by Aurora, Mono, and Onyx templates
Loads settings from .env file in the project root
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from project root
# Walk up from this file's location to find .env
_script_dir = Path(__file__).parent
_project_root = _script_dir.parent  # One level up from scripts/

# Try loading .env from project root, then from each template dir
for env_path in [
    _project_root / ".env",
    _script_dir / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()  # Try default locations


class Config:
    
    # API Settings
    GENIUS_API_TOKEN = os.getenv("GENIUS_API_TOKEN", "")
    GENIUS_BASE_URL = "https://api.genius.com"

    # Cloudflare Browser Rendering (optional — fallback for lyrics extraction)
    CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
    
    # Whisper Settings
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
    WHISPER_CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", "whisper_models")
    
    # Job Settings
    TOTAL_JOBS = int(os.getenv("TOTAL_JOBS", "12"))
    
    # Processing Settings
    MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
    
    # File Paths
    JOBS_DIR = "jobs"
    
    # Audio Settings
    AUDIO_FORMAT = "mp3"
    TRIMMED_FORMAT = "wav"
    
    # Image Settings (Aurora/Onyx)
    IMAGE_TARGET_SIZE = 700
    IMAGE_FORMAT = "PNG"
    COLOR_COUNT = 2
    
    # Lyric Settings
    MAX_LINE_LENGTH = int(os.getenv("MAX_LINE_LENGTH", "25"))
    
    @classmethod
    def validate(cls):
        """Validate configuration and print warnings for missing settings"""
        if not cls.GENIUS_API_TOKEN:
            print("  ⚠ GENIUS_API_TOKEN not set. Genius lyrics fetching disabled.")
            print("    Set it in .env: GENIUS_API_TOKEN=your_token_here")
        
        valid_models = ['tiny', 'base', 'small', 'medium', 'large-v3']
        if cls.WHISPER_MODEL not in valid_models:
            print(f"  ⚠ Unknown WHISPER_MODEL '{cls.WHISPER_MODEL}'. Using 'small'.")
            print(f"    Valid models: {', '.join(valid_models)}")
            cls.WHISPER_MODEL = 'small'
    
    @classmethod
    def set_max_line_length(cls, length):
        """Override max line length (Mono uses longer lines than Aurora)"""
        cls.MAX_LINE_LENGTH = length
