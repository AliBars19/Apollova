"""Tests for parallel pipeline infrastructure."""
import threading
import time

import pytest

from scripts.parallel_pipeline import (
    whisper_lock, get_pool, shutdown_pool, submit_prefetch, with_whisper_lock
)


class TestWhisperLock:
    def test_lock_is_reentrant_safe(self):
        """Whisper lock should be a regular Lock (not RLock) to prevent accidental nesting."""
        assert isinstance(whisper_lock, type(threading.Lock()))

    def test_lock_serializes_access(self):
        results = []

        def task(value, delay):
            with whisper_lock:
                time.sleep(delay)
                results.append(value)

        t1 = threading.Thread(target=task, args=("first", 0.05))
        t2 = threading.Thread(target=task, args=("second", 0.01))
        t1.start()
        time.sleep(0.01)  # Ensure t1 gets lock first
        t2.start()
        t1.join()
        t2.join()
        assert results == ["first", "second"]

    def test_with_whisper_lock_returns_result(self):
        result = with_whisper_lock(lambda: 42)
        assert result == 42

    def test_with_whisper_lock_passes_args(self):
        result = with_whisper_lock(lambda a, b: a + b, 3, 4)
        assert result == 7

    def test_with_whisper_lock_propagates_exception(self):
        def raise_error():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            with_whisper_lock(raise_error)


class TestPrefetchPool:
    def teardown_method(self):
        shutdown_pool()

    def test_get_pool_returns_executor(self):
        pool = get_pool()
        assert pool is not None

    def test_get_pool_is_singleton(self):
        pool1 = get_pool()
        pool2 = get_pool()
        assert pool1 is pool2

    def test_submit_prefetch_runs_task(self):
        future = submit_prefetch(lambda: 99)
        assert future.result(timeout=5) == 99

    def test_multiple_prefetch_tasks_run_concurrently(self):
        start = time.time()
        futures = [submit_prefetch(time.sleep, 0.1) for _ in range(3)]
        for f in futures:
            f.result(timeout=5)
        elapsed = time.time() - start
        # 3 tasks of 0.1s each should take ~0.1s (parallel), not 0.3s
        assert elapsed < 0.25

    def test_shutdown_pool_allows_recreation(self):
        pool1 = get_pool()
        shutdown_pool()
        pool2 = get_pool()
        assert pool1 is not pool2

    def test_submit_after_shutdown_works(self):
        submit_prefetch(lambda: 1).result(timeout=5)
        shutdown_pool()
        # New pool created automatically
        result = submit_prefetch(lambda: 2).result(timeout=5)
        assert result == 2

    def test_prefetch_exception_captured(self):
        def bad_task():
            raise RuntimeError("oops")

        future = submit_prefetch(bad_task)
        with pytest.raises(RuntimeError, match="oops"):
            future.result(timeout=5)

    def test_10_concurrent_tasks(self):
        results = []
        lock = threading.Lock()

        def task(i):
            with lock:
                results.append(i)
            return i

        futures = [submit_prefetch(task, i) for i in range(10)]
        for f in futures:
            f.result(timeout=5)
        assert sorted(results) == list(range(10))
