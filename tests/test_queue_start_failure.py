"""Thread exhaustion must leave jobs retryable and cancellation must unlock."""
import threading
import time
import subprocess
import sys

import pytest
import server  # noqa: F401 - install the live optimized scheduler
from media.downloader import DownloadQueue


class Job:
    is_preparation_job = False
    host_group = 'fixture.invalid'
    queue_priority = 100
    def __init__(self):
        self.fail = True
        self.started = threading.Event()
    def start(self):
        if self.fail:
            raise RuntimeError('cannot start new thread')
        thread = threading.Thread(target=self.started.set)
        thread.start()
        return thread
    def cancel(self):
        pass


def wait(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize('optimized', [False, True])
def test_worker_start_failure_preserves_pending_identity_and_can_restart(optimized):
    # Separate interpreters also exercise the class before runtime patching.
    code = """
import threading, time
from media.downloader import DownloadQueue
{install}
class Job:
    is_preparation_job = False
    host_group = 'fixture.invalid'
    queue_priority = 100
    fail = True
    def start(self):
        if self.fail:
            raise RuntimeError('cannot start new thread')
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread
queue = DownloadQueue()
job = Job()
queue.add(job)
queue.start()
queue._scheduler_thread.join(2)
assert not queue._scheduler_thread.is_alive()
assert queue.pending_jobs() == [job]
assert queue.active_count() == 0
assert queue._running is False
job.fail = False
queue.start()
queue._scheduler_thread.join(2)
assert not queue._scheduler_thread.is_alive()
assert queue.pending_count() == queue.active_count() == 0
""".replace("{install}", "import server" if optimized else "")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr


def test_scheduler_thread_start_failure_is_retryable(monkeypatch):
    queue = DownloadQueue()
    job = Job()
    job.fail = False
    queue.add(job)
    original = threading.Thread.start
    monkeypatch.setattr(threading.Thread, 'start', lambda _self: (_ for _ in ()).throw(RuntimeError('thread limit')))
    with pytest.raises(RuntimeError, match='thread limit'):
        queue.start()
    assert queue._running is False
    assert queue.pending_jobs() == [job]
    monkeypatch.setattr(threading.Thread, 'start', original)
    queue.start()
    assert job.started.wait(2)
    assert wait(lambda: not queue._running)


@pytest.mark.parametrize('method', ['cancel_all', 'cancel_active'])
def test_cancel_callback_can_acquire_queue_lock(method):
    queue = DownloadQueue()
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join()
    lock_available = []

    class Callback:
        def cancel(self):
            acquired = queue._lock.acquire(timeout=0.1)
            lock_available.append(acquired)
            if acquired:
                queue._lock.release()

    queue._active[1] = (Callback(), worker, time.monotonic())
    if method == 'cancel_active':
        queue.cancel_active(lambda _job: True)
    else:
        queue.cancel_all()
    assert lock_available == [True]
    assert wait(lambda: queue.active_count() == 0) if method == 'cancel_all' else True
