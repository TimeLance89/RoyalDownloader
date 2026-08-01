import threading
import time

from downloader import DownloadQueue


class _BlockingJob:
    def __init__(self, *, preparation=False, host_group=""):
        self.is_preparation_job = preparation
        self.host_group = host_group
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


def test_preparations_do_not_consume_download_capacity():
    queue = DownloadQueue(max_parallel=2, max_preparations=2, per_host_limit=1)
    preparations = [
        _BlockingJob(preparation=True, host_group="__series_preparation__")
        for _ in range(2)
    ]
    downloads = [
        _BlockingJob(host_group="cdn-one.invalid"),
        _BlockingJob(host_group="cdn-two.invalid"),
    ]
    for job in (*preparations, *downloads):
        queue.add(job)

    try:
        queue.start()
        assert _wait_until(lambda: all(job.started.is_set() for job in preparations))
        assert _wait_until(lambda: all(job.started.is_set() for job in downloads))
        assert queue.active_count() == 4
    finally:
        for job in (*preparations, *downloads):
            job.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)


def test_download_host_limit_still_applies_with_separate_preparations():
    queue = DownloadQueue(max_parallel=2, max_preparations=2, per_host_limit=1)
    preparation = _BlockingJob(
        preparation=True, host_group="__series_preparation__",
    )
    first = _BlockingJob(host_group="same.invalid")
    second = _BlockingJob(host_group="same.invalid")
    for job in (preparation, first, second):
        queue.add(job)

    try:
        queue.start()
        assert _wait_until(lambda: preparation.started.is_set() and first.started.is_set())
        assert not second.started.wait(0.2)
        first.release.set()
        assert _wait_until(lambda: second.started.is_set())
    finally:
        preparation.release.set()
        first.release.set()
        second.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)
