"""Execute complete synthetic queues at NAS backlog scales, without I/O."""
import concurrent.futures
from collections import Counter
import threading
import time
from types import SimpleNamespace

import pytest
import server
from core import queue_jobs, queue_performance
from media.downloader import DownloadQueue


@pytest.mark.parametrize('size', [650, 1000, 5000])
def test_all_synthetic_jobs_complete_once_with_bounded_parallelism(size, monkeypatch):
    # Compress only scheduler polling, preserving real worker threads/locks.
    # This is a correctness test, not physical-download throughput measurement.
    monkeypatch.setattr(queue_performance, 'time', SimpleNamespace(
        monotonic=time.monotonic, sleep=lambda _seconds: time.sleep(0.001),
    ))
    queue = DownloadQueue(max_parallel=4, per_host_limit=1)
    lock = threading.Lock()
    starts, ends = Counter(), Counter()
    active, hosts, peak = 0, Counter(), 0
    violations = []
    done = threading.Event()
    queue.on_queue_done = done.set

    class Synthetic:
        is_preparation_job = False
        queue_priority = 100
        def __init__(self, ordinal):
            self.ordinal = ordinal
            self.host_group = f'fixture-{ordinal % 5}.invalid'
        def start(self):
            def work():
                nonlocal active, peak
                with lock:
                    starts[self.ordinal] += 1
                    active += 1
                    hosts[self.host_group] += 1
                    peak = max(peak, active)
                    if active > 4 or hosts[self.host_group] > 1:
                        violations.append((active, hosts[self.host_group]))
                time.sleep(0.001)
                with lock:
                    active -= 1
                    hosts[self.host_group] -= 1
                    ends[self.ordinal] += 1
            thread = threading.Thread(target=work)
            thread.start()
            return thread
        def cancel(self):
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda ordinal: queue.add(Synthetic(ordinal)), range(size)))
    queue.start()
    try:
        assert done.wait(75), f'{size}: stalled with {queue.pending_count()} pending'
        queue._scheduler_thread.join(2)
        assert starts == ends == Counter(range(size))
        assert not violations
        assert peak <= 4
        assert queue.pending_count() == queue.active_count() == 0
    finally:
        queue.cancel_all()


@pytest.mark.parametrize('size', [650, 1000, 5000])
def test_large_crash_snapshot_recovers_identity_retry_and_corruption(size, tmp_path):
    jobs = [queue_jobs.new_job(f'fixture:{i}', job_id=f'job-{i}') for i in range(size)]
    for i, job in enumerate(jobs):
        job.update(status=('downloading', 'preparing', 'waiting_provider')[i % 3],
                   source_retry_count=i % 7, next_retry_at=100 + i)
    document = {'schema_version': queue_jobs.SCHEMA_VERSION, 'revision': 42,
                'jobs': jobs, 'history': []}
    path = tmp_path / 'queue.json'
    queue_jobs.atomic_save(path, document)
    restored, _ = queue_jobs.load_document(path)
    assert len(restored['jobs']) == size
    assert [j['job_id'] for j in restored['jobs']] == [j['job_id'] for j in jobs]
    assert [j['attempt_id'] for j in restored['jobs']] == [j['attempt_id'] for j in jobs]
    assert [j['source_retry_count'] for j in restored['jobs']] == [j['source_retry_count'] for j in jobs]
    assert all(j['status'] == ('waiting_provider' if i % 3 == 2 else 'queued')
               for i, j in enumerate(restored['jobs']))
    path.write_bytes(b'{partial power-loss write')
    restored, recovered = queue_jobs.load_document(path)
    assert recovered and len(restored['jobs']) == size and restored['revision'] == 42
    duplicated = dict(document, jobs=jobs + [dict(j, job_id='duplicate-' + j['job_id']) for j in jobs])
    normalized, _ = queue_jobs.normalize_document(duplicated)
    assert len(normalized['jobs']) == size


@pytest.mark.parametrize('size', [650, 1000, 5000])
def test_parallel_logical_duplicate_claims_have_one_identity(size):
    state = server.state
    with state.queue_claim_lock:
        saved = state.queue_jobs, state.queue_job_by_slug
        state.queue_jobs, state.queue_job_by_slug = {}, {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda i: server._ensure_queue_job(f'fixture:{i % size}'), range(size * 2)))
        assert len(state.queue_jobs) == size
        assert len({j['job_id'] for j in claims}) == size
        assert all(claims[i]['job_id'] == claims[i + size]['job_id'] for i in range(size))
    finally:
        with state.queue_claim_lock:
            state.queue_jobs, state.queue_job_by_slug = saved
