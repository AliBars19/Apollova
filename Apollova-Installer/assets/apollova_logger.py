"""
apollova_logger.py
Shared logging module for Setup, Apollova, and Uninstall.

Log files written to:
  <install_root>/assets/logs/setup.log
  <install_root>/assets/logs/app.log
  <install_root>/assets/logs/uninstall.log

Each session appends a timestamped block. Logs are capped at 5 MB then rotated
(3 generations: .log.1, .log.2, .log.3) so disk space never runs away.

Usage:
    from apollova_logger import get_logger
    log = get_logger("setup")          # or "app" or "uninstall"
    log.info("Starting installation")
    log.warning("Torch not found")
    log.error("pip failed", exc_info=True)
    log.section("Installing packages")  # visual separator
"""

import logging
import logging.handlers
import os
import sys
import platform
import traceback
from datetime import datetime
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_LOG_BYTES = 5 * 1024 * 1024   # 5 MB before rotation
MAX_LOG_BACKUPS = 3               # keep .log.1, .log.2, .log.3
LOG_NAMES = ("setup", "app", "uninstall")


# ── Resolve log directory ──────────────────────────────────────────────────────
def _get_log_dir() -> Path:
    """Return <install_root>/assets/logs, creating it if needed."""
    if getattr(sys, "frozen", False):
        # Running as compiled exe — exe is in install root
        root = Path(sys.executable).parent
    else:
        # Running as .py — go up from assets/ to install root
        here = Path(__file__).parent
        root = here.parent if here.name == "assets" else here

    log_dir = root / "assets" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback: temp dir
        import tempfile
        log_dir = Path(tempfile.gettempdir()) / "apollova_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# ── Custom formatter ───────────────────────────────────────────────────────────
class _Formatter(logging.Formatter):
    LEVEL_ICONS = {
        logging.DEBUG:    "DEBUG  ",
        logging.INFO:     "INFO   ",
        logging.WARNING:  "WARNING",
        logging.ERROR:    "ERROR  ",
        logging.CRITICAL: "FATAL  ",
    }

    def format(self, record: logging.LogRecord) -> str:
        icon = self.LEVEL_ICONS.get(record.levelno, "INFO   ")
        ts   = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        base = f"[{ts}] {icon}  {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ── ApollovaLogger wrapper ─────────────────────────────────────────────────────
class ApollovaLogger:
    """Thin wrapper around stdlib Logger with extra helpers."""

    def __init__(self, name: str, log_path: Path):
        self._path   = log_path
        self._logger = logging.getLogger(f"apollova.{name}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._logger.propagate = False

        # RotatingFileHandler — automatic rotation during long sessions
        try:
            fh = logging.handlers.RotatingFileHandler(
                str(log_path),
                maxBytes=MAX_LOG_BYTES,
                backupCount=MAX_LOG_BACKUPS,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(_Formatter())
            self._logger.addHandler(fh)
        except Exception as e:
            # If we can't write logs, don't crash the app
            print(f"[apollova_logger] Could not open log file {log_path}: {e}",
                  file=sys.stderr)

    # ── Stdlib pass-throughs ──────────────────────────────────────────────────
    def debug(self, msg, *a, **kw):    self._logger.debug(msg, *a, **kw)
    def info(self, msg, *a, **kw):     self._logger.info(msg, *a, **kw)
    def warning(self, msg, *a, **kw):  self._logger.warning(msg, *a, **kw)
    def error(self, msg, *a, **kw):    self._logger.error(msg, *a, **kw)
    def critical(self, msg, *a, **kw): self._logger.critical(msg, *a, **kw)

    def exception(self, msg: str):
        """Log an error with the current exception traceback."""
        self._logger.error(msg, exc_info=True)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def section(self, title: str):
        """Write a visual separator line — makes log easy to scan."""
        sep = "─" * 60
        self._logger.info(f"\n{sep}\n  {title}\n{sep}")

    def session_start(self, component: str):
        """Write a session header — called once when the app/installer opens."""
        self.section(f"{component} session started")
        self.info(f"Apollova  |  component: {component}")
        self.info(f"Date/time: {datetime.now().strftime('%A %d %B %Y  %H:%M:%S')}")
        self.info(f"Platform:  {platform.system()} {platform.release()} "
                  f"({platform.machine()})")
        self.info(f"Python:    {sys.version}")
        self.info(f"Log file:  {self._path}")

    def session_end(self, component: str, success: bool = True):
        """Write a session footer."""
        outcome = "COMPLETED SUCCESSFULLY" if success else "ENDED WITH ERRORS"
        self.section(f"{component} session {outcome}")

    def cmd_result(self, cmd: list | str, returncode: int,
                   stdout: str = "", stderr: str = ""):
        """Log the result of a subprocess call."""
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        level   = logging.INFO if returncode == 0 else logging.WARNING
        self._logger.log(level,
            f"CMD: {cmd_str[:120]}\n"
            f"     exit={returncode}"
            + (f"\n     stdout: {stdout[:300]}" if stdout.strip() else "")
            + (f"\n     stderr: {stderr[:300]}" if stderr.strip() else ""))

    def pkg_install(self, package: str, success: bool, detail: str = ""):
        """Log a pip install result."""
        if success:
            self.info(f"INSTALLED:  {package}"
                      + (f"  ({detail})" if detail else ""))
        else:
            self.error(f"FAILED:     {package}"
                       + (f"  —  {detail}" if detail else ""))

    def check(self, label: str, passed: bool, detail: str = ""):
        """Log an integrity check result."""
        icon = "✓" if passed else "✗"
        msg  = f"CHECK {icon}  {label}"
        if detail:
            msg += f"  —  {detail}"
        if passed:
            self.info(msg)
        else:
            self.warning(msg)

    def performance_summary(self, timings: dict, total_time: float = 0,
                            device: str = ""):
        """Log a formatted table of step timings for end-of-batch reporting.

        Args:
            timings: dict of {step_name: seconds} or {step_name: (seconds, status)}
            total_time: overall elapsed time in seconds
            device: GPU/CPU device string
        """
        lines = ["\n┌─────────────────────────────────────────────────┐",
                 "│              PERFORMANCE SUMMARY                 │",
                 "├──────────────────────────────┬──────┬────────────┤",
                 "│ Step                         │ Time │ Status     │",
                 "├──────────────────────────────┼──────┼────────────┤"]
        for step, val in timings.items():
            if isinstance(val, tuple):
                secs, status = val
            else:
                secs, status = val, "ok"
            lines.append(
                f"│ {step:<28} │ {secs:>4.0f}s │ {status:<10} │")
        lines.append("├──────────────────────────────┼──────┼────────────┤")
        if total_time:
            lines.append(
                f"│ {'TOTAL':<28} │ {total_time:>4.0f}s │            │")
        if device:
            lines.append(
                f"│ Device: {device:<39} │")
        lines.append("└─────────────────────────────────────────────────┘")
        self.info("\n".join(lines))

    @property
    def path(self) -> Path:
        return self._path


# ── Factory ────────────────────────────────────────────────────────────────────
_instances: dict[str, ApollovaLogger] = {}

def get_logger(name: str) -> ApollovaLogger:
    """
    Return a named logger.  name must be one of: 'setup', 'app', 'uninstall'.
    Repeated calls with the same name return the same instance.
    """
    if name not in LOG_NAMES:
        raise ValueError(f"Invalid logger name '{name}'. "
                         f"Must be one of: {LOG_NAMES}")
    if name not in _instances:
        log_dir  = _get_log_dir()
        log_path = log_dir / f"{name}.log"
        _instances[name] = ApollovaLogger(name, log_path)
    return _instances[name]
