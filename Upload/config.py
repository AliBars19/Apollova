"""
Apollova Render Watcher — Configuration
========================================

Loads from .env file → environment variables → defaults.
Folder-to-account mapping is easily extensible (just add a line when Onyx gets its own account).
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _load_dotenv(path: str) -> None:
    """Minimal .env loader — no external dependency needed."""
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
    except FileNotFoundError:
        pass


@dataclass
class Config:
    """Central configuration for the render watcher."""

    # ── API ───────────────────────────────────────────────────────
    api_base_url: str = "https://macbookvisuals.com"
    gate_password: str = ""

    # ── Apollova Root (parent of all template folders) ────────────
    apollova_root: str = "."

    # ── Folder → Account Mapping ──────────────────────────────────
    # Key   = folder name under apollova_root (contains jobs/renders/)
    # Value = account name used in the website API
    #
    # When Onyx gets its own account, just change "nova" → "onyx" below.
    folder_account_map: dict[str, str] = field(default_factory=lambda: {
        "Apollova-Aurora": "aurora",
        "Apollova-Mono":   "nova",
        "Apollova-Onyx":   "nova",      # ← change to "onyx" when ready
    })

    # ── Paths ─────────────────────────────────────────────────────
    # Renders subfolder inside each template folder
    renders_subfolder: str = "jobs/renders"
    state_db_path: str = "./data/upload_state.db"
    log_dir: str = "./logs"

    # ── Scheduling ────────────────────────────────────────────────
    videos_per_day_per_account: int = 12
    schedule_interval_minutes: int = 60       # 1 hour between videos
    schedule_day_start_hour: int = 11         # First video at 11 AM
    schedule_day_end_hour: int = 23           # Last slot at 11 PM
    dead_hours_start: int = 2                 # 2 AM
    dead_hours_end: int = 6                   # 6 AM

    # ── Upload Reliability ────────────────────────────────────────
    max_upload_retries: int = 3
    retry_base_delay: float = 2.0             # doubles each attempt
    upload_timeout: int = 300                 # 5 min for large files
    api_timeout: int = 15                     # non-upload API calls

    # ── File Handling ─────────────────────────────────────────────
    file_stable_wait: float = 3.0             # seconds between size checks
    file_stable_checks: int = 3
    debounce_seconds: float = 5.0
    video_extensions: list[str] = field(default_factory=lambda: [".mp4", ".mov"])

    # ── Notifications ─────────────────────────────────────────────
    notifications_enabled: bool = True

    # ── Logging ───────────────────────────────────────────────────
    log_level: str = "INFO"
    log_max_days: int = 7

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "Config":
        """Load config from .env and environment variables."""
        if env_path:
            _load_dotenv(env_path)
        else:
            for candidate in [".env", "render_watcher.env", "../.env"]:
                if Path(candidate).exists():
                    _load_dotenv(candidate)
                    break

        config = cls(
            api_base_url=os.getenv("APOLLOVA_API_URL", cls.api_base_url),
            gate_password=os.getenv("GATE_PASSWORD", ""),
            apollova_root=os.getenv("APOLLOVA_ROOT", cls.apollova_root),
            state_db_path=os.getenv("STATE_DB_PATH", cls.state_db_path),
            log_dir=os.getenv("LOG_DIR", cls.log_dir),
            schedule_interval_minutes=int(os.getenv("SCHEDULE_INTERVAL", cls.schedule_interval_minutes)),
            schedule_day_start_hour=int(os.getenv("SCHEDULE_START_HOUR", cls.schedule_day_start_hour)),
            videos_per_day_per_account=int(os.getenv("VIDEOS_PER_DAY", cls.videos_per_day_per_account)),
            max_upload_retries=int(os.getenv("MAX_RETRIES", cls.max_upload_retries)),
            upload_timeout=int(os.getenv("UPLOAD_TIMEOUT", cls.upload_timeout)),
            notifications_enabled=os.getenv("NOTIFICATIONS", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
        )

        # Override folder map from env if provided (JSON string)
        map_env = os.getenv("FOLDER_ACCOUNT_MAP")
        if map_env:
            import json
            try:
                config.folder_account_map = json.loads(map_env)
            except json.JSONDecodeError:
                pass

        return config

    def get_watch_paths(self) -> dict[str, tuple[Path, str]]:
        """Return {folder_name: (renders_folder_path, account_name)} for all templates.
        
        Uses folder_name as key to avoid Windows path resolution collisions.
        Creates missing directories automatically.
        """
        root = Path(self.apollova_root)
        paths = {}
        for folder_name, account in self.folder_account_map.items():
            renders_path = root / folder_name / self.renders_subfolder
            paths[folder_name] = (renders_path, account)
        return paths

    def get_template_from_path(self, file_path: str) -> str:
        """Determine which template a file belongs to based on its parent path."""
        fp = Path(file_path).resolve()
        for folder_name in self.folder_account_map:
            if folder_name.lower() in str(fp).lower():
                return folder_name.replace("Apollova-", "").lower()
        return "unknown"

    def validate(self) -> list[str]:
        """Validate config. Returns list of errors (empty = valid)."""
        errors = []
        if not self.gate_password:
            errors.append("GATE_PASSWORD is required (set in .env or environment)")
        if not self.api_base_url.startswith(("http://", "https://")):
            errors.append(f"Invalid API URL: {self.api_base_url}")
        if self.videos_per_day_per_account < 1:
            errors.append("VIDEOS_PER_DAY must be at least 1")
        if self.schedule_interval_minutes < 5:
            errors.append("Schedule interval must be at least 5 minutes")
        if not self.folder_account_map:
            errors.append("No folder→account mappings configured")
        return errors

    def validate_or_exit(self) -> None:
        errors = self.validate()
        if errors:
            print("❌ Configuration errors:")
            for err in errors:
                print(f"   • {err}")
            print("\nCreate a .env file with at minimum:")
            print("   GATE_PASSWORD=your_admin_password")
            sys.exit(1)

    def ensure_dirs(self) -> None:
        """Create required directories."""
        Path(self.state_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        root = Path(self.apollova_root)
        for folder_name in self.folder_account_map:
            (root / folder_name / self.renders_subfolder).mkdir(parents=True, exist_ok=True)