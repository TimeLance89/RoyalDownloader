"""Bounded, credential-free evidence for stalls and process restarts."""

import asyncio
import logging
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from core.runtime_resources import container_memory, process_resources


logger = logging.getLogger(__name__)


class RuntimeDiagnostics:
    def __init__(self, *, clock=time.monotonic, stall_seconds=3.0):
        self.clock = clock
        self.started = clock()
        self.started_at = time.time()
        self.instance_id = uuid.uuid4().hex
        self.stall_seconds = stall_seconds
        self.lock = threading.Lock()
        self.last_tick = None
        self.loop_thread = None
        self.max_lag = 0.0
        self.stalls = 0
        self.last_stall = None
        self.reported = False
        self.stop_event = threading.Event()
        self.thread = None

    def tick(self):
        now = self.clock()
        with self.lock:
            if self.last_tick is not None:
                self.max_lag = max(self.max_lag, max(0.0, now - self.last_tick - 1.0))
            self.last_tick = now
            self.loop_thread = threading.get_ident()
            self.reported = False

    def check(self):
        with self.lock:
            lag = max(0.0, self.clock() - self.last_tick - 1.0) if self.last_tick is not None else 0.0
            self.max_lag = max(self.max_lag, lag)
            if lag < self.stall_seconds or self.reported:
                return
            self.reported = True
            self.stalls += 1
            frame = sys._current_frames().get(self.loop_thread)
            # No locals, source text, request arguments or credentials.
            stack = []
            while frame is not None and len(stack) < 12:
                stack.append(f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}")
                frame = frame.f_back
            stack.reverse()
            self.last_stall = {"timestamp": time.time(), "lag_seconds": round(lag, 3), "stack": stack}
        logger.warning("Webserver event loop stalled: %.3fs; stack=%s", lag, " > ".join(stack))

    def _watch(self):
        while not self.stop_event.wait(1.0):
            self.check()

    async def heartbeat(self):
        self.tick()
        logger.info("Webserver runtime started: pid=%s instance=%s", os.getpid(), self.instance_id)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._watch, name="loop-watchdog", daemon=True)
        self.thread.start()
        try:
            while True:
                await asyncio.sleep(1.0)
                self.tick()
        finally:
            self.stop_event.set()
            await asyncio.to_thread(self.thread.join, 2.0)

    def snapshot(self):
        with self.lock:
            result = {
                "instance_id": self.instance_id, "pid": os.getpid(),
                "started_at": self.started_at, "uptime_seconds": round(self.clock() - self.started, 3),
                "max_event_loop_lag_seconds": round(self.max_lag, 3),
                "stall_count": self.stalls,
                "last_stall": dict(self.last_stall) if self.last_stall else None,
            }
        result["thread_count"] = threading.active_count()
        result["container_memory"] = container_memory()
        result["process_resources"] = process_resources()
        return result
