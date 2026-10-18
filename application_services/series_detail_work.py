"""Bounded, shared enrichment work that outlives short interactive HTTP waits."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
import time


class SeriesDetailsBusy(RuntimeError):
    pass


class SeriesDetailWork:
    def __init__(self, *, workers=2, capacity=8, retain_seconds=5, clock=time.monotonic, thread_name="series-detail"):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name)
        self.capacity, self.retain_seconds, self.clock = capacity, retain_seconds, clock
        self.lock = threading.Lock()
        self.jobs = OrderedDict()

    def submit(self, key, work):
        with self.lock:
            now = self.clock()
            for old_key, (future, expires) in list(self.jobs.items()):
                if future.done() and (future.cancelled() or expires <= now):
                    self.jobs.pop(old_key)
            existing = self.jobs.get(key)
            if existing:
                return existing[0]
            if sum(not future.done() for future, _ in self.jobs.values()) >= self.capacity:
                raise SeriesDetailsBusy("Serienabgleiche sind ausgelastet")
            # Completed results also stay bounded while clients retrieve them.
            while len(self.jobs) >= self.capacity * 2:
                oldest = next((item for item, (future, _) in self.jobs.items() if future.done()), None)
                if oldest is None:
                    raise SeriesDetailsBusy("Serienabgleiche sind ausgelastet")
                self.jobs.pop(oldest)
            future = self.pool.submit(work)
            self.jobs[key] = (future, float("inf"))

        def completed(done):
            with self.lock:
                if self.jobs.get(key, (None,))[0] is done:
                    if done.cancelled() or done.exception() is not None:
                        self.jobs.pop(key, None)
                    else:
                        self.jobs[key] = (done, self.clock() + self.retain_seconds)

        future.add_done_callback(completed)
        return future

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
