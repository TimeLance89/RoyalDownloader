"""Bound worker-to-loop events before asyncio's unbounded callback queue."""

from collections import deque
import logging
import threading


logger = logging.getLogger(__name__)


class LoopEventBridge:
    def __init__(self, publish, resync, *, capacity=256, batch_size=32):
        self.publish, self.resync = publish, resync
        self.capacity, self.batch_size = max(1, capacity), max(1, batch_size)
        self.lock = threading.Lock()
        self.pending = deque()
        self.loop = None
        self.scheduled = False
        self.overflow = False

    def submit(self, loop, data):
        if loop.is_closed():
            return
        with self.lock:
            if self.loop is not loop:
                self.pending.clear()
                self.loop, self.scheduled, self.overflow = loop, False, False
            if not self.overflow:
                if len(self.pending) >= self.capacity:
                    self.pending.clear()
                    self.overflow = True
                else:
                    self.pending.append(data)
            if self.scheduled:
                return
            self.scheduled = True
        try:
            loop.call_soon_threadsafe(self._drain, loop)
        except RuntimeError:
            # The loop can close between checking it and scheduling the drain.
            with self.lock:
                if self.loop is loop:
                    self.pending.clear()
                    self.scheduled = False

    def _drain(self, loop):
        with self.lock:
            if self.loop is not loop:
                return
            overflow, self.overflow = self.overflow, False
            batch = []
            if overflow:
                self.pending.clear()
            else:
                for _ in range(min(self.batch_size, len(self.pending))):
                    batch.append(self.pending.popleft())
        try:
            if overflow:
                # Discarding structural events requires a fresh snapshot.
                self.resync()
            else:
                for data in batch:
                    self.publish(data)
        except Exception:
            logger.exception("Live event delivery failed; clients need a fresh snapshot")
            self.resync()
        finally:
            with self.lock:
                if self.loop is loop:
                    if self.pending or self.overflow:
                        # Yield between batches so HTTP and health can run.
                        loop.call_soon(self._drain, loop)
                    else:
                        self.scheduled = False
