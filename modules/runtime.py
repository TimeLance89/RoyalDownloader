"""Reusable, lock-protected lifecycle controller for built-in workers."""

from __future__ import annotations

from threading import RLock
from typing import Callable


class WorkerModuleController:
    """Adapts a real worker to the module lifecycle contract.

    The controller validates configuration and checks the worker after each
    transition. Setting a stop event alone is never a completed stop.
    """

    def __init__(
        self,
        start: Callable[[], None],
        stop: Callable[[], bool],
        alive: Callable[[], bool],
        configured: Callable[[], tuple[bool, str]],
    ) -> None:
        self._start = start
        self._stop = stop
        self._alive = alive
        self._configured = configured
        self._lock = RLock()

    def configuration_state(self) -> tuple[bool, str]:
        return self._configured()

    def start(self) -> None:
        with self._lock:
            configured, detail = self.configuration_state()
            if not configured:
                raise RuntimeError(detail)
            if not self._alive():
                self._start()
            if not self._alive():
                raise RuntimeError("Worker wurde nicht gestartet")

    def stop(self) -> bool:
        with self._lock:
            if not self._alive():
                return True
            return bool(self._stop()) and not self._alive()

    def health(self) -> tuple[bool, str]:
        configured, detail = self.configuration_state()
        if not configured:
            return False, detail
        return (True, "Worker läuft") if self._alive() else (False, "Worker läuft nicht")


class OnDemandModuleController:
    """Lifecycle contract for modules that perform work only per API request."""
    def __init__(self, configured: Callable[[], tuple[bool, str]]) -> None:
        self._configured, self._active, self._lock = configured, False, RLock()
    def configuration_state(self) -> tuple[bool, str]: return self._configured()
    def start(self) -> None:
        configured, detail = self.configuration_state()
        if not configured: raise RuntimeError(detail)
        with self._lock: self._active = True
    def stop(self) -> bool:
        with self._lock: self._active = False
        return True
    def health(self) -> tuple[bool, str]:
        configured, detail = self.configuration_state()
        if not configured: return False, detail
        with self._lock: return (True, "Bei Anfrage bereit") if self._active else (False, "Modul ist nicht gestartet")
