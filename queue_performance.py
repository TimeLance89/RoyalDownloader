"""Targeted runtime optimizations for large download queues.

The application-service layer deliberately resolves its backend dependencies at
call time.  This module uses that existing composition seam to keep queue
performance policy in one place without changing the REST/WebSocket contracts
or the physical download implementation.

Optimizations provided here are intentionally narrow:

* avoid repeatedly scanning a large pending queue when every compatible worker
  slot is already occupied;
* collapse persistence writes that only change restart-volatile progress or
  active-state fields while retaining every durable queue transition;
* bound high-frequency progress events and full queue-update snapshots;
* preserve the existing queue job, cancel/retry, recovery, and host-limit
  semantics.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import api_queue_router
from downloader import DownloadQueue


QUEUE_UPDATE_INTERVAL_SECONDS = 0.5
PROGRESS_EVENT_INTERVAL_SECONDS = 0.25
PROGRESS_PERSIST_INTERVAL_SECONDS = 5.0

# These values are useful while a process is alive, but a restarted process
# cannot resume a physical byte stream from them.  Queue recovery already maps
# preparing/downloading jobs back to queued, so changing only these fields does
# not require another fsync of the complete queue document.
_VOLATILE_JOB_FIELDS = frozenset({
    "started_at",
    "progress",
    "downloaded_bytes",
    "total_bytes",
    "speed_bps",
    "eta_seconds",
})
_RECOVERED_AS_QUEUED = frozenset({"preparing", "downloading"})

_INSTALL_LOCK = threading.Lock()
_CONTROLLERS: dict[int, "QueuePerformanceController"] = {}
_QUEUE_CLASS_PATCHED = False
_ORIGINAL_QUEUE_INIT = None


def _is_preparation_job(job: Any) -> bool:
    return bool(getattr(job, "is_preparation_job", False))


def _host_group(job: Any) -> str:
    return str(getattr(job, "host_group", "") or "")


def _reset_pending_counters_locked(queue: DownloadQueue) -> None:
    preparations = 0
    downloads = 0
    host_counts: dict[str, int] = {}
    for _job_id, job in queue._jobs:
        if _is_preparation_job(job):
            preparations += 1
            continue
        downloads += 1
        group = _host_group(job)
        host_counts[group] = host_counts.get(group, 0) + 1
    queue._pending_preparations = preparations
    queue._pending_downloads = downloads
    queue._pending_download_hosts = host_counts
    if not hasattr(queue, "_perf_pending_scan_items"):
        queue._perf_pending_scan_items = 0
    if not hasattr(queue, "_perf_fast_path_skips"):
        queue._perf_fast_path_skips = 0


def _decrement_pending_locked(queue: DownloadQueue, job: Any) -> None:
    if _is_preparation_job(job):
        queue._pending_preparations = max(0, queue._pending_preparations - 1)
        return
    queue._pending_downloads = max(0, queue._pending_downloads - 1)
    group = _host_group(job)
    remaining = int(queue._pending_download_hosts.get(group, 0)) - 1
    if remaining > 0:
        queue._pending_download_hosts[group] = remaining
    else:
        queue._pending_download_hosts.pop(group, None)


def _optimized_queue_init(self, *args, **kwargs):
    _ORIGINAL_QUEUE_INIT(self, *args, **kwargs)
    with self._lock:
        _reset_pending_counters_locked(self)


def _optimized_queue_add(self, job):
    with self._lock:
        self._next_job_id += 1
        self._jobs.append((self._next_job_id, job))
        if _is_preparation_job(job):
            self._pending_preparations += 1
        else:
            self._pending_downloads += 1
            group = _host_group(job)
            self._pending_download_hosts[group] = (
                self._pending_download_hosts.get(group, 0) + 1
            )


def _optimized_queue_add_front(self, job):
    """Add a pending job at the front while keeping type counters exact."""
    with self._lock:
        self._next_job_id += 1
        self._jobs.insert(0, (self._next_job_id, job))
        if _is_preparation_job(job):
            self._pending_preparations += 1
        else:
            self._pending_downloads += 1
            group = _host_group(job)
            self._pending_download_hosts[group] = (
                self._pending_download_hosts.get(group, 0) + 1
            )


def _optimized_queue_remove_pending(self, predicate):
    """Remove pending jobs and refresh the O(1) scheduler class counters."""
    with self._lock:
        kept = []
        removed = []
        for queued in self._jobs:
            _job_id, job = queued
            if predicate(job):
                removed.append(job)
            else:
                kept.append(queued)
        self._jobs = kept
        _reset_pending_counters_locked(self)
        return removed


def _optimized_queue_cancel_all(self):
    with self._lock:
        self._running = False
        self._scheduler_generation += 1
        cancelled = []
        cancelled_jobs = []
        for jid, (job, thread, _started) in list(self._active.items()):
            job.cancel()
            cancelled.append((jid, thread))
            cancelled_jobs.append(job)
        self._jobs.clear()
        self._pending_preparations = 0
        self._pending_downloads = 0
        self._pending_download_hosts.clear()
    if cancelled:
        threading.Thread(
            target=self._reap_cancelled,
            args=(cancelled,),
            daemon=True,
        ).start()
    return cancelled_jobs


def _download_slot_can_start(queue: DownloadQueue, active_downloads: int, active_hosts: dict[str, int]) -> bool:
    if active_downloads >= queue._max_parallel or queue._pending_downloads <= 0:
        return False
    # Empty host groups are intentionally not limited in the original
    # scheduler, so one such pending job is enough to make a slot useful.
    if queue._pending_download_hosts.get("", 0):
        return True
    return any(
        count > 0 and active_hosts.get(group, 0) < queue._per_host_limit
        for group, count in queue._pending_download_hosts.items()
    )


def _optimized_queue_scheduler(self, generation: int):
    """Run the existing scheduler semantics without idle O(queue-size) scans."""
    completed_normally = False
    while True:
        with self._lock:
            if not self._running or generation != self._scheduler_generation:
                break

            finished = [
                jid
                for jid, (_job, thread, _started) in self._active.items()
                if not thread.is_alive()
            ]
            for jid in finished:
                self._active.pop(jid, None)

            active_hosts: dict[str, int] = {}
            active_downloads = 0
            active_preparations = 0
            for active_job, _thread, _started in self._active.values():
                if _is_preparation_job(active_job):
                    active_preparations += 1
                    continue
                active_downloads += 1
                group = _host_group(active_job)
                if group:
                    active_hosts[group] = active_hosts.get(group, 0) + 1

            while (
                self._running
                and generation == self._scheduler_generation
                and self._jobs
            ):
                preparation_slot = (
                    self._pending_preparations > 0
                    and active_preparations < self._max_preparations
                )
                download_slot = _download_slot_can_start(
                    self, active_downloads, active_hosts,
                )
                if not preparation_slot and not download_slot:
                    # This is the important large-queue fast path.  While all
                    # compatible slots are busy, the old loop inspected every
                    # pending object five times per second merely to conclude
                    # that nothing could start.
                    self._perf_fast_path_skips += 1
                    break

                best_priority = None
                best_index = None
                self._perf_pending_scan_items += len(self._jobs)
                for index, (_jid, queued) in enumerate(self._jobs):
                    if _is_preparation_job(queued):
                        if not preparation_slot:
                            continue
                    else:
                        if not download_slot:
                            continue
                        group = _host_group(queued)
                        if active_hosts.get(group, 0) >= self._per_host_limit:
                            continue
                    priority = self._job_priority(queued)
                    if best_priority is None or priority < best_priority:
                        best_priority = priority
                        best_index = index

                if best_index is None:
                    # Counter/host fast checks are conservative.  If a custom
                    # job implementation still makes no candidate eligible,
                    # keep the original polling behavior without spinning.
                    break

                jid, job = self._jobs.pop(best_index)
                _decrement_pending_locked(self, job)
                thread = job.start()
                self._active[jid] = (job, thread, time.monotonic())
                if _is_preparation_job(job):
                    active_preparations += 1
                else:
                    active_downloads += 1
                    group = _host_group(job)
                    if group:
                        active_hosts[group] = active_hosts.get(group, 0) + 1

            if generation != self._scheduler_generation:
                break
            if not self._active and not self._jobs:
                self._running = False
                completed_normally = True
                break

        time.sleep(0.2)

    with self._lock:
        owns_generation = generation == self._scheduler_generation
        if owns_generation:
            self._running = False
    if completed_normally and owns_generation and self.on_queue_done:
        try:
            self.on_queue_done()
        except Exception as exc:  # pragma: no cover - existing defensive seam
            import logging
            logging.getLogger(__name__).error("on_queue_done Fehler: %s", exc)


def _patch_download_queue_class() -> None:
    global _QUEUE_CLASS_PATCHED, _ORIGINAL_QUEUE_INIT
    if _QUEUE_CLASS_PATCHED:
        return
    _ORIGINAL_QUEUE_INIT = DownloadQueue.__init__
    DownloadQueue.__init__ = _optimized_queue_init
    DownloadQueue.add = _optimized_queue_add
    DownloadQueue.add_front = _optimized_queue_add_front
    DownloadQueue.remove_pending = _optimized_queue_remove_pending
    DownloadQueue.cancel_all = _optimized_queue_cancel_all
    DownloadQueue._scheduler = _optimized_queue_scheduler
    _QUEUE_CLASS_PATCHED = True


def _durable_job_projection(job: dict[str, Any]) -> dict[str, Any]:
    projected = {
        key: value
        for key, value in job.items()
        if key not in _VOLATILE_JOB_FIELDS
    }
    if projected.get("status") in _RECOVERED_AS_QUEUED:
        projected["status"] = "queued"
    return projected


def _signature_payload(jobs, history) -> str:
    payload = {
        "jobs": [_durable_job_projection(dict(job)) for job in jobs],
        "history": [_durable_job_projection(dict(job)) for job in history],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class QueuePerformanceController:
    def __init__(self, backend: ModuleType):
        self.backend = backend
        self._persist_delegate = backend._persist_queue_state
        self._require_delegate = backend._require_persistent_snapshot
        self._signature_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._queue_update_lock = threading.Lock()
        self._last_durable_signature = self._current_durable_signature()
        self._last_progress_persist_at = time.monotonic()
        self._progress_event_times: dict[tuple[str, str, str], float] = {}
        self._last_queue_update_at = 0.0
        self._queue_update_timer: threading.Timer | None = None
        self.queue_update_interval = QUEUE_UPDATE_INTERVAL_SECONDS
        self.progress_event_interval = PROGRESS_EVENT_INTERVAL_SECONDS
        self.progress_persist_interval = PROGRESS_PERSIST_INTERVAL_SECONDS
        self.persistence_writes = 0
        self.persistence_skips = 0
        self.forced_persistence_writes = 0
        self.progress_persistence_writes = 0
        self.progress_events_sent = 0
        self.progress_events_suppressed = 0
        self.queue_updates_sent = 0
        self.queue_updates_coalesced = 0

    def _current_durable_signature(self) -> str:
        state = self.backend.state
        with state.queue_claim_lock:
            jobs = [
                _durable_job_projection(dict(job))
                for job in state.queue_jobs.values()
                if job.get("slug") in state.picked
            ]
            limit = int(getattr(self.backend, "HISTORY_LIMIT", 500))
            history = [
                _durable_job_projection(dict(job))
                for job in list(state.queue_history)[:limit]
            ]
        return _signature_payload(jobs, history)

    @staticmethod
    def _snapshot_durable_signature(snapshot: dict[str, Any]) -> str:
        return _signature_payload(
            snapshot.get("jobs") or [],
            snapshot.get("history") or [],
        )

    def persist_queue_state(self) -> bool:
        """Skip full fsyncs when only restart-volatile fields changed."""
        before = self._current_durable_signature()
        with self._signature_lock:
            if before == self._last_durable_signature:
                self.persistence_skips += 1
                return True

        saved = bool(self._persist_delegate())
        after = self._current_durable_signature()
        with self._signature_lock:
            if saved and after == before:
                self._last_durable_signature = before
                self.persistence_writes += 1
            elif saved:
                # A concurrent durable mutation may have happened while the
                # delegate was writing.  Force the next caller to save again
                # rather than claiming that an uncertain generation is durable.
                self._last_durable_signature = ""
                self.persistence_writes += 1
        return saved

    def require_persistent_snapshot(self, resource: str, snapshot) -> None:
        """Keep fail-closed writes exact and teach the deduper what was saved."""
        result = self._require_delegate(resource, snapshot)
        if resource == "queue":
            signature = self._snapshot_durable_signature(snapshot)
            with self._signature_lock:
                self._last_durable_signature = signature
                self.forced_persistence_writes += 1
        return result

    def _persist_progress_snapshot(self) -> bool:
        """Persist progress occasionally without weakening durable transitions."""
        before = self._current_durable_signature()
        saved = bool(self._persist_delegate())
        after = self._current_durable_signature()
        with self._signature_lock:
            if saved and before == after:
                self._last_durable_signature = before
            elif saved:
                self._last_durable_signature = ""
            if saved:
                self.progress_persistence_writes += 1
        return saved

    def _prune_progress_times_locked(self, now: float) -> None:
        if len(self._progress_event_times) <= 2048:
            return
        cutoff = now - 10 * 60
        self._progress_event_times = {
            key: value
            for key, value in self._progress_event_times.items()
            if value >= cutoff
        }
        if len(self._progress_event_times) > 2048:
            oldest = sorted(
                self._progress_event_times,
                key=self._progress_event_times.get,
            )[: len(self._progress_event_times) - 1024]
            for key in oldest:
                self._progress_event_times.pop(key, None)

    def on_job_progress(
        self,
        pct: float,
        msg: str,
        label: str,
        *,
        slug: str = "",
        job_id: str = "",
        attempt_id: str = "",
        downloaded_bytes: int = 0,
        total_bytes=None,
        speed_bps: float = 0.0,
        eta_seconds=None,
    ):
        """Bound direct-download progress floods while preserving event shape."""
        payload = {"type": "progress", "label": label, "msg": msg}
        if slug:
            current = self.backend._queue_job_for_slug(slug)
            if not current or (
                job_id and current.get("job_id") != job_id
            ) or (
                attempt_id and current.get("attempt_id") != attempt_id
            ) or current.get("status") == "cancelling":
                return False

            effective_job_id = str(current.get("job_id") or job_id or "")
            effective_attempt_id = str(current.get("attempt_id") or attempt_id or "")
            now = time.monotonic()
            event_key = (slug, effective_job_id, effective_attempt_id)
            force_event = pct < 0 or pct >= 100
            with self._progress_lock:
                last_event = float(self._progress_event_times.get(event_key) or 0)
                should_emit = (
                    force_event
                    or now - last_event >= self.progress_event_interval
                )
                should_persist = (
                    pct >= 100
                    or now - self._last_progress_persist_at
                    >= self.progress_persist_interval
                )
                if should_emit:
                    self._progress_event_times[event_key] = now
                else:
                    self.progress_events_suppressed += 1
                if should_persist:
                    self._last_progress_persist_at = now
                self._prune_progress_times_locked(now)

            if not should_emit and not should_persist:
                return True

            logical = self.backend._update_queue_job(
                slug,
                persist=False,
                expected_job_id=job_id,
                expected_attempt_id=attempt_id,
                status="downloading",
                progress=max(0.0, pct) if pct >= 0 else None,
                downloaded_bytes=max(0, int(downloaded_bytes or 0)),
                total_bytes=total_bytes,
                speed_bps=max(0.0, float(speed_bps or 0)),
                eta_seconds=eta_seconds,
            )
            if should_persist:
                self._persist_progress_snapshot()
            if logical:
                payload["job"] = logical
                job_id = logical["job_id"]
            if not should_emit:
                return True

        if job_id:
            payload["job_id"] = job_id
        if attempt_id:
            payload["attempt_id"] = attempt_id
        if slug:
            payload["slug"] = slug
        if pct >= 0:
            payload["pct"] = pct
        self.backend.broadcast(payload)
        self.progress_events_sent += 1
        return True

    def _send_queue_update(self) -> None:
        try:
            payload = self.backend.build_queue_payload()
            self.backend.broadcast({"type": "queue_update", "queue": payload})
            self.queue_updates_sent += 1
        except Exception as exc:  # noqa: BLE001 - UI updates must not kill workers
            self.backend.log(f"Queue-Liveupdate fehlgeschlagen: {exc}", "warn")

    def _timer_queue_update(self) -> None:
        with self._queue_update_lock:
            self._queue_update_timer = None
            self._last_queue_update_at = time.monotonic()
        self._send_queue_update()

    def request_queue_update(self) -> None:
        """Send at most two full queue snapshots per second, with trailing state."""
        send_now = False
        with self._queue_update_lock:
            now = time.monotonic()
            elapsed = now - self._last_queue_update_at
            if self._queue_update_timer is None and (
                self._last_queue_update_at == 0.0
                or elapsed >= self.queue_update_interval
            ):
                self._last_queue_update_at = now
                send_now = True
            elif self._queue_update_timer is None:
                delay = max(0.001, self.queue_update_interval - elapsed)
                timer = threading.Timer(delay, self._timer_queue_update)
                timer.daemon = True
                self._queue_update_timer = timer
                timer.start()
                self.queue_updates_coalesced += 1
            else:
                self.queue_updates_coalesced += 1
        if send_now:
            self._send_queue_update()

    @staticmethod
    def _physical_matches_attempt(physical, slug: str, job_id: str, attempt_id: str) -> bool:
        queue_slugs = set(getattr(physical, "queue_slugs", set()) or set())
        queue_slug = getattr(physical, "queue_slug", "")
        if queue_slug:
            queue_slugs.add(queue_slug)
        attempts = getattr(physical, "queue_attempts", None)
        if isinstance(attempts, dict):
            return (
                slug in queue_slugs
                and attempts.get(slug) == attempt_id
                and getattr(physical, "queue_job_ids", {}).get(slug) == job_id
            )
        return (
            queue_slug == slug
            and getattr(physical, "job_id", "") == job_id
            and getattr(physical, "attempt_id", "") == attempt_id
        )

    def run_preparation_job(self, physical) -> None:
        """Keep preparation semantics while coalescing full-state side effects."""
        state = self.backend.state
        queued_slugs: set[str] = set()
        marked_preparing = False
        try:
            with state.queue_prepare_lock:
                if physical._cancelled.is_set():
                    return
                with state.queue_claim_lock:
                    state.preparing_queue_slugs.update(
                        physical.queue_slugs & state.picked
                    )
                    for slug in physical.queue_slugs & state.picked:
                        self.backend._update_queue_job(
                            slug,
                            persist=False,
                            expected_job_id=physical.queue_job_ids.get(slug, ""),
                            expected_attempt_id=physical.queue_attempts.get(slug, ""),
                            status="preparing",
                        )
                    marked_preparing = True
                # This call is intentionally retained.  Automatic watchlist
                # jobs create their logical records immediately before the
                # preparation workers.  The durable-signature wrapper writes
                # that structural change once, then skips the N transient
                # preparing/progress-only rewrites that used to follow.
                self.backend._persist_queue_state()
                self.request_queue_update()
                queued_slugs = self.backend.run_download_queue(
                    physical.jobs,
                    physical.out_root,
                    start_queue=False,
                    cancelled=physical._cancelled.is_set,
                    movie_fallbacks=physical.movie_fallbacks,
                ) or set()
        except Exception as exc:  # noqa: BLE001 - matches existing boundary
            self.backend.log(
                f"Automatische Downloadvorbereitung fehlgeschlagen: {exc}",
                "err",
            )
            for movie, slug in physical.jobs:
                self.backend.on_job_done(
                    False,
                    f"Vorbereitung fehlgeschlagen: {exc}",
                    movie.title,
                    Path(""),
                    slug=slug,
                    job_id=physical.queue_job_ids.get(slug, ""),
                    attempt_id=physical.queue_attempts.get(slug, ""),
                )
        finally:
            if marked_preparing:
                with state.queue_claim_lock:
                    state.preparing_queue_slugs.difference_update(
                        physical.queue_slugs
                    )
            if not physical._cancelled.is_set():
                for movie, slug in physical.jobs:
                    if (
                        slug not in queued_slugs
                        and self.backend._queue_slug_claimed(slug)
                    ):
                        self.backend.on_job_done(
                            False,
                            "Downloadvorbereitung ohne Abschluss beendet",
                            movie.title,
                            Path(""),
                            slug=slug,
                            job_id=physical.queue_job_ids.get(slug, ""),
                            attempt_id=physical.queue_attempts.get(slug, ""),
                        )
            if physical._cancelled.is_set():
                remove_pending = getattr(state.dl_queue, "remove_pending", None)
                if remove_pending:
                    remove_pending(
                        lambda job: bool(
                            physical.queue_slugs
                            & set(getattr(job, "queue_slugs", []))
                        )
                        or getattr(job, "queue_slug", "")
                        in physical.queue_slugs
                    )
                active_jobs = state.dl_queue.active_jobs()
                for movie, slug in physical.jobs:
                    if not any(
                        active is not physical
                        and self._physical_matches_attempt(
                            active,
                            slug,
                            physical.queue_job_ids.get(slug, ""),
                            physical.queue_attempts.get(slug, ""),
                        )
                        for active in active_jobs
                    ):
                        self.backend.on_job_done(
                            False,
                            "Abgebrochen",
                            movie.title,
                            Path(""),
                            slug=slug,
                            job_id=physical.queue_job_ids.get(slug, ""),
                            attempt_id=physical.queue_attempts.get(slug, ""),
                        )
            if marked_preparing:
                self.request_queue_update()

    def diagnostics(self) -> dict[str, Any]:
        queue = self.backend.state.dl_queue
        return {
            "persistence_writes": self.persistence_writes,
            "persistence_skips": self.persistence_skips,
            "forced_persistence_writes": self.forced_persistence_writes,
            "progress_persistence_writes": self.progress_persistence_writes,
            "progress_events_sent": self.progress_events_sent,
            "progress_events_suppressed": self.progress_events_suppressed,
            "queue_updates_sent": self.queue_updates_sent,
            "queue_updates_coalesced": self.queue_updates_coalesced,
            "scheduler_pending_scan_items": int(
                getattr(queue, "_perf_pending_scan_items", 0)
            ),
            "scheduler_fast_path_skips": int(
                getattr(queue, "_perf_fast_path_skips", 0)
            ),
        }


def _patch_preparation_job(controller: QueuePerformanceController) -> None:
    cls = api_queue_router._QueuePreparationJob
    if getattr(cls, "_queue_performance_patched", False):
        return
    cls._queue_performance_original_run = cls._run

    def optimized_run(physical):
        return controller.run_preparation_job(physical)

    cls._run = optimized_run
    cls._queue_performance_patched = True


def install_queue_performance(backend: ModuleType) -> QueuePerformanceController:
    """Install the queue optimizations once after all application services exist."""
    key = id(backend)
    with _INSTALL_LOCK:
        existing = _CONTROLLERS.get(key)
        if existing is not None:
            return existing

        _patch_download_queue_class()
        queue = backend.state.dl_queue
        with queue._lock:
            _reset_pending_counters_locked(queue)

        controller = QueuePerformanceController(backend)
        backend._persist_queue_state = controller.persist_queue_state
        backend._require_persistent_snapshot = controller.require_persistent_snapshot
        backend.on_job_progress = controller.on_job_progress
        backend.queue_performance_diagnostics = controller.diagnostics
        _patch_preparation_job(controller)
        _CONTROLLERS[key] = controller
        return controller


def get_queue_performance_controller(backend: ModuleType) -> QueuePerformanceController | None:
    return _CONTROLLERS.get(id(backend))
