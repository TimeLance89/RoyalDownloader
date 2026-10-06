"""Bounded workers with one running request per provider and fair queues."""
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor


class ProviderProbeScheduler:
    def __init__(self, workers=4, name="episode-probes"):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._workers = workers
        self._lock = threading.Lock()
        self._queues = {}
        self._active = set()
        self._closed = False

    def submit(self, provider, lookup):
        future = Future()
        with self._lock:
            if self._closed:
                future.cancel()
                return future
            self._queues.setdefault(provider, deque()).append((future, lookup))
            self._dispatch()
        return future

    def _dispatch(self):
        if self._closed:
            return
        while len(self._active) < self._workers:
            provider = next((key for key, queue in self._queues.items() if queue and key not in self._active), None)
            if provider is None:
                return
            future, lookup = self._queues[provider].popleft()
            self._active.add(provider)
            self._pool.submit(self._run, provider, future, lookup)

    def _run(self, provider, future, lookup):
        try:
            if future.set_running_or_notify_cancel():
                try:
                    result = lookup()
                    future.probe_finished_at = time.monotonic()
                    future.set_result(result)
                except Exception as error:  # noqa: BLE001 -- independent adapter boundary
                    future.probe_finished_at = time.monotonic()
                    future.set_exception(error)
        finally:
            with self._lock:
                self._active.discard(provider)
                self._dispatch()

    def close(self):
        with self._lock:
            self._closed = True
            for queue in self._queues.values():
                for future, _ in queue:
                    future.cancel()
            self._queues.clear()
        self._pool.shutdown(wait=True, cancel_futures=True)
