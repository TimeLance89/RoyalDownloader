"""Offline queue benchmark. Run the same harness against baseline and candidate.

No provider sessions, real downloads, ASGI lifespan or integration credentials.
Wall-clock measurements are diagnostic; structural counters are CI budgets.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc


def timed(function, repeat=7):
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000)
    return {'median_ms': statistics.median(samples), 'max_ms': max(samples), 'samples_ms': samples}


def measure(root, size):
    import offline_guard
    offline_guard.pytest_configure(None)
    sys.path.insert(0, str(root))
    scratch = tempfile.TemporaryDirectory(prefix='royal-benchmark-')
    os.environ['SERIENDL_DATA_DIR'] = scratch.name
    import server
    from core import queue_jobs
    from core.queue_performance import get_queue_performance_controller
    from media.downloader import DownloadQueue
    from providers.models import FilmpalastMovie

    # No external state and no background integration startup.
    state = server.state
    state.picked.clear()
    state.queue_jobs.clear()
    state.queue_job_by_slug.clear()
    state.queue_history.clear()
    state.watchlist = []
    state.movie_subscriptions = []
    state.fp_movies.clear()
    for i in range(size):
        slug = f'fixture:movie-{i}'
        job = queue_jobs.new_job(slug, job_id=f'job-{i}', title=f'Fixture movie {i}')
        job['attempt_id'] = f'attempt-{i}'
        state.queue_jobs[job['job_id']] = job
        state.queue_job_by_slug[slug] = job['job_id']
        state.picked.add(slug)
        state.fp_movies[slug] = FilmpalastMovie(title=job['title'], url='https://fixture.invalid/', provider='fixture')
    controller = get_queue_performance_controller(server)
    controller._last_durable_signature = controller._current_durable_signature()
    result = {'size': size, 'thread_count_before': threading.active_count()}
    cpu = time.process_time()
    started = time.perf_counter()
    result['queue_payload'] = timed(server.build_queue_payload)
    result['durable_signature'] = timed(controller._current_durable_signature)
    result['snapshot'] = timed(server._queue_state_snapshot)
    snapshot = server._queue_state_snapshot()
    # Keep the useful #500 history workload, at the canonical three sizes.
    history = []
    for i in range(500):
        entry = queue_jobs.new_job(f'fixture:history-{i}', job_id=f'history-{i}')
        entry.update(status='completed', completed_at=float(i + 1))
        history.append(entry)
    with_history = dict(snapshot, history=history)
    def normalize_history():
        normalized, _ = queue_jobs.normalize_document(with_history)
        assert len(normalized['jobs']) == size
        assert len(normalized['history']) == 500
        return normalized
    result['normalize_with_history'] = timed(normalize_history, repeat=3)
    path = Path(scratch.name) / 'benchmark-queue.json'
    result['atomic_persist'] = timed(lambda: queue_jobs.atomic_save(path, snapshot), repeat=3)
    result['recovery'] = timed(lambda: queue_jobs.load_document(path), repeat=3)
    result['snapshot_bytes'] = path.stat().st_size
    recovered, _ = queue_jobs.load_document(path)
    assert len(recovered['jobs']) == size
    assert {job['job_id'] for job in recovered['jobs']} == set(state.queue_jobs)
    # Count actual fsync calls and complete-file replacements for one save.
    counts = {'fsync_calls': 0, 'replacements': 0}
    real_fsync, real_replace = queue_jobs.os.fsync, queue_jobs.os.replace
    def fsync(fd):
        counts['fsync_calls'] += 1
        return real_fsync(fd)
    def replace(src, dst):
        counts['replacements'] += 1
        return real_replace(src, dst)
    queue_jobs.os.fsync, queue_jobs.os.replace = fsync, replace
    try:
        queue_jobs.atomic_save(path, snapshot)
    finally:
        queue_jobs.os.fsync, queue_jobs.os.replace = real_fsync, real_replace
    result['persist_operations_per_save'] = counts
    delegate_calls = []
    controller._persist_delegate = lambda: delegate_calls.append(1) or True
    before_writes, before_skips = controller.persistence_writes, controller.persistence_skips
    result['volatile_persist_100'] = timed(lambda: [controller.persist_queue_state() for _ in range(100)], repeat=1)
    assert not delegate_calls
    first = next(iter(state.queue_jobs.values()))
    first['status'] = 'cancelling'
    assert controller.persist_queue_state()
    assert len(delegate_calls) == 1
    result['durable_writes'] = controller.persistence_writes - before_writes
    result['volatile_skips'] = controller.persistence_skips - before_skips
    first['status'] = 'queued'

    # A blocked host exercises the real scheduler without any network transfer.
    release = threading.Event()
    running = threading.Event()
    class Blocked:
        is_preparation_job = False
        host_group = 'fixture.invalid'
        queue_priority = 100
        def start(self):
            def work():
                running.set()
                release.wait(3)
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            return thread
        def cancel(self):
            release.set()
    queue = DownloadQueue(max_parallel=4, per_host_limit=1)
    enqueued_at = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _i: queue.add(Blocked()), range(size)))
    result['enqueue_ms'] = (time.perf_counter() - enqueued_at) * 1000
    first_at = time.perf_counter()
    queue.start()
    assert running.wait(2)
    result['first_dispatch_ms'] = (time.perf_counter() - first_at) * 1000
    assert queue.active_count() == 1
    result['scheduler_lock_response'] = timed(queue.pending_count)
    scans = queue._perf_pending_scan_items
    idle_cpu = time.process_time()
    time.sleep(0.65)
    result['blocked_idle_cpu_seconds'] = time.process_time() - idle_cpu
    result['blocked_additional_scans'] = queue._perf_pending_scan_items - scans
    result['scheduler_scanned_items'] = queue._perf_pending_scan_items
    result['peak_observed_threads'] = threading.active_count()
    cancel_at = time.perf_counter()
    queue.cancel_all()
    queue._scheduler_thread.join(2)
    until = time.monotonic() + 2
    while queue.active_count() and time.monotonic() < until:
        time.sleep(0.01)
    result['cancel_ms'] = (time.perf_counter() - cancel_at) * 1000
    assert queue.active_count() == queue.pending_count() == 0
    result['thread_count_after'] = threading.active_count()
    assert result['blocked_additional_scans'] == 0
    result['cpu_seconds'] = time.process_time() - cpu
    result['elapsed_seconds'] = time.perf_counter() - started
    result['cpu_percent_one_core'] = 100 * result['cpu_seconds'] / result['elapsed_seconds']
    result['peak_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    # Allocation tracing is a separate memory probe. It must not contaminate
    # production wall/CPU timings as it did in the old Stability Lab budget.
    tracemalloc.start()
    try:
        normalize_history()
        result['python_allocated_peak_mib'] = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    finally:
        tracemalloc.stop()
    result['completed_synthetic_operations'] = size
    # This is metadata processing, not measured media-download bandwidth.
    scratch.cleanup()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--size', type=int)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.size:
        print(json.dumps(measure(args.root.resolve(), args.size)))
        return
    rows = []
    for size in (650, 1000, 5000):
        for repeat in range(args.repeats):
            call = subprocess.run([sys.executable, __file__, '--root', str(args.root.resolve()),
                                   '--size', str(size)], capture_output=True, text=True, timeout=120)
            if call.returncode:
                raise RuntimeError(call.stderr[-5000:])
            row = json.loads(call.stdout)
            row['repeat'] = repeat + 1
            rows.append(row)
    commit = subprocess.check_output(['git', '-C', str(args.root), 'rev-parse', 'HEAD'], text=True).strip()
    payload = {'commit': commit, 'python': platform.python_version(), 'platform': platform.platform(),
               'cpu_count': os.cpu_count(), 'repeats': args.repeats, 'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'rows': len(rows), 'commit': commit}))


if __name__ == '__main__':
    main()
