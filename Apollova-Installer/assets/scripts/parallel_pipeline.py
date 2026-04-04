"""
Parallel pipeline helpers for overlapping I/O-bound stages.

Whisper transcription stays serialized (GPU lock), but audio download,
image download, and Demucs separation can run concurrently.
"""
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any


# Global lock for Whisper model access (GPU is single-instance)
whisper_lock = threading.Lock()

# Thread pool for I/O-bound prefetch (download audio, images, Demucs)
_pool: ThreadPoolExecutor | None = None
_MAX_WORKERS = 3


def get_pool() -> ThreadPoolExecutor:
    """Get or create the shared thread pool for I/O prefetch."""
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="prefetch")
    return _pool


def shutdown_pool() -> None:
    """Shut down the thread pool (call on app exit)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def submit_prefetch(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """Submit an I/O task to the prefetch pool."""
    return get_pool().submit(fn, *args, **kwargs)


def with_whisper_lock(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a function while holding the Whisper GPU lock."""
    with whisper_lock:
        return fn(*args, **kwargs)
