import threading
import time
from collections import OrderedDict

import pytest

import queue_jobs
import server
from downloader import DownloadQueue
from queue_performance import (
    get_queue_performance_controller,
    install_queue_performance,
)


class _BlockingJob:
    def __init__(
        self,
        *,
        preparation=False,
        host_group="",
        queue_priority=100,
    ):
        self.is_preparation_job = preparation
        self.host_group = host_group
        self.queue_priority = queue_priority
        self.started = threading.Event()
        self.release = threading.Event()

    def start(self):
        def run():
            self.started.set()
            self.release.wait(3)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def cancel(self):
        self.release.set()


def _wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def isolated_queue_state():
    state = server.state
    saved = {
        "picked": set(state.picked),
        "jobs": state.queue_jobs,
        "by_slug": state.queue_job_by_slug,
        "history": state.queue_history,
        "counted": set(state.counted_queue_slugs),
    }
    state.picked = set()
    state.queue_jobs = OrderedDict()
    state.queue_job_by_slug = {}
    state.queue_history = []
    state.counted_queue_slugs.clear()
    try:
        yield state
    finally:
        state.picked = saved["picked"]
        state.queue_jobs = saved["jobs"]
        state.queue_job_by_slug = saved["by_slug"]
        state.queue_history = saved["history"]
        state.counted_queue_slugs.clear()
        state.counted_queue_slugs.update(saved["counted"])


def test_runtime_installs_queue_performance_layer_once():
    controller = get_queue_performance_controller(server)

    assert controller is not None
    assert install_queue_performance(server) is controller
    assert hasattr(server.state.dl_queue, "_pending_preparations")
    assert callable(server.queue_performance_diagnostics)


def test_scheduler_stops_rescanning_large_preparation_backlog_when_slot_is_full():
    queue = DownloadQueue(max_parallel=2, max_preparations=1, per_host_limit=1)
    jobs = [_BlockingJob(preparation=True) for _ in range(101)]
    for job in jobs:
        queue.add(job)

    try:
        queue.start()
        assert _wait_until(lambda: jobs[0].started.is_set())
        time.sleep(0.45)
        first_scan_count = queue._perf_pending_scan_items
        fast_path_count = queue._perf_fast_path_skips
        time.sleep(0.45)

        # One initial priority selection may inspect the backlog.  Once the
        # only preparation slot is occupied, repeated 200 ms scheduler ticks
        # must no longer walk the remaining ~100 objects.
        assert first_scan_count <= len(jobs) + 1
        assert queue._perf_pending_scan_items == first_scan_count
        assert queue._perf_fast_path_skips > fast_path_count
    finally:
        queue.cancel_all()
        for job in jobs:
            job.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)


def test_scheduler_stops_rescanning_same_host_backlog_at_host_limit():
    queue = DownloadQueue(max_parallel=2, max_preparations=1, per_host_limit=1)
    jobs = [_BlockingJob(host_group="same.invalid") for _ in range(101)]
    for job in jobs:
        queue.add(job)

    try:
        queue.start()
        assert _wait_until(lambda: jobs[0].started.is_set())
        time.sleep(0.45)
        first_scan_count = queue._perf_pending_scan_items
        time.sleep(0.45)

        assert first_scan_count <= len(jobs) + 1
        assert queue._perf_pending_scan_items == first_scan_count
        assert sum(job.started.is_set() for job in jobs) == 1
    finally:
        queue.cancel_all()
        for job in jobs:
            job.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)


def test_transient_queue_states_do_not_force_full_persistence(
    isolated_queue_state,
    monkeypatch,
):
    state = isolated_queue_state
    controller = get_queue_performance_controller(server)
    job = queue_jobs.new_job("provider:movie", job_id="perf-persist-job")
    state.queue_jobs[job["job_id"]] = job
    state.queue_job_by_slug[job["slug"]] = job["job_id"]
    state.picked.add(job["slug"])

    writes = []
    monkeypatch.setattr(controller, "_persist_delegate", lambda: writes.append(1) or True)
    controller._last_durable_signature = controller._current_durable_signature()

    job["status"] = "preparing"
    job["progress"] = 37.5
    job["downloaded_bytes"] = 123456
    assert server._persist_queue_state() is True
    assert writes == []

    # Cancellation intent is restart-significant and must still be written.
    job["status"] = "cancelling"
    assert server._persist_queue_state() is True
    assert writes == [1]


def test_progress_flood_is_bounded_but_terminal_progress_is_not_lost(
    isolated_queue_state,
    monkeypatch,
):
    state = isolated_queue_state
    controller = get_queue_performance_controller(server)
    job = queue_jobs.new_job("provider:movie", job_id="perf-progress-job")
    state.queue_jobs[job["job_id"]] = job
    state.queue_job_by_slug[job["slug"]] = job["job_id"]
    state.picked.add(job["slug"])

    events = []
    monkeypatch.setattr(server, "broadcast", events.append)
    monkeypatch.setattr(controller, "progress_event_interval", 60.0)
    monkeypatch.setattr(controller, "progress_persist_interval", 60.0)
    monkeypatch.setattr(controller, "_last_progress_persist_at", time.monotonic())
    monkeypatch.setattr(controller, "_persist_delegate", lambda: True)
    before_suppressed = controller.progress_events_suppressed

    for index in range(200):
        assert server.on_job_progress(
            float(index % 99),
            f"chunk {index}",
            "Movie",
            slug=job["slug"],
            job_id=job["job_id"],
            attempt_id=job["attempt_id"],
            downloaded_bytes=index * 256 * 1024,
            total_bytes=1024 * 1024 * 1024,
        ) is True

    # First update is immediate; the burst afterwards is collapsed.
    assert len(events) == 1
    assert controller.progress_events_suppressed - before_suppressed >= 199

    # Completion/progress 100 is always forced through and refreshes the
    # logical record even inside the throttle interval.
    assert server.on_job_progress(
        100,
        "done",
        "Movie",
        slug=job["slug"],
        job_id=job["job_id"],
        attempt_id=job["attempt_id"],
        downloaded_bytes=1024 * 1024 * 1024,
        total_bytes=1024 * 1024 * 1024,
    ) is True
    assert len(events) == 2
    assert events[-1]["pct"] == 100
    assert state.queue_jobs[job["job_id"]]["progress"] == 100


def test_preparation_queue_updates_are_coalesced(monkeypatch):
    controller = get_queue_performance_controller(server)
    payload_builds = []
    events = []

    with controller._queue_update_lock:
        if controller._queue_update_timer is not None:
            controller._queue_update_timer.cancel()
            controller._queue_update_timer = None
        controller._last_queue_update_at = 0.0

    monkeypatch.setattr(controller, "queue_update_interval", 0.05)
    monkeypatch.setattr(
        server,
        "build_queue_payload",
        lambda: payload_builds.append(1) or {"groups": [], "jobs": []},
    )
    monkeypatch.setattr(server, "broadcast", events.append)

    for _ in range(25):
        controller.request_queue_update()
    time.sleep(0.09)

    # One immediate snapshot plus one trailing snapshot represents the whole
    # burst; 25 preparation state changes must not serialize 25 full queues.
    assert len(payload_builds) == 2
    assert len(events) == 2
    assert all(event["type"] == "queue_update" for event in events)
