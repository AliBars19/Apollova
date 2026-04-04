import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve the base install directory (assets/../)
# This file lives at: <install>/assets/scripts/config.py
_SCRIPTS_DIR = Path(__file__).parent          # .../assets/scripts
_ASSETS_DIR  = _SCRIPTS_DIR.parent            # .../assets
_BASE_DIR    = _ASSETS_DIR.parent             # .../  (install root)

# Preferred .env location: %APPDATA%/Apollova/
APPDATA_DIR = Path(os.environ.get("APPDATA", "")) / "Apollova"

# Load .env — check APPDATA first, fall back to install root
try:
    from dotenv import load_dotenv
    _appdata_env = APPDATA_DIR / ".env"
    _install_env = _BASE_DIR / ".env"
    if _appdata_env.is_file():
        _env_file = _appdata_env
    elif _install_env.is_file():
        _env_file = _install_env
    else:
        _env_file = None
    if _env_file is not None:
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
    def migrate_env(cls) -> bool:
        """Copy install-root .env to APPDATA if APPDATA version doesn't exist yet.

        Returns True if migration was performed, False otherwise.
        """
        appdata_env = APPDATA_DIR / ".env"
        install_env = _BASE_DIR / ".env"
        if appdata_env.is_file():
            return False
        if not install_env.is_file():
            return False
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(install_env), str(appdata_env))
        logger.info("Migrated .env from %s to %s", install_env, appdata_env)
        return True

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
