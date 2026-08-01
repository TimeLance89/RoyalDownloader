import threading
import time

from downloader import DownloadQueue


class _BlockingJob:
    def __init__(self, *, preparation=False, host_group="", queue_priority=100):
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


def test_movie_preparation_overtakes_series_backlog():
    queue = DownloadQueue(max_parallel=1, max_preparations=1, per_host_limit=1)
    series = [
        _BlockingJob(preparation=True, queue_priority=100)
        for _ in range(3)
    ]
    movie = _BlockingJob(preparation=True, queue_priority=0)
    for job in (*series, movie):
        queue.add(job)

    try:
        queue.start()
        assert _wait_until(lambda: movie.started.is_set())
        assert not any(job.started.is_set() for job in series)
    finally:
        movie.release.set()
        for job in series:
            job.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)


def test_later_series_cannot_push_prepared_movie_back():
    queue = DownloadQueue(max_parallel=1, max_preparations=1, per_host_limit=1)
    active = _BlockingJob(host_group="active.invalid")
    movie = _BlockingJob(host_group="movie.invalid", queue_priority=0)
    series = _BlockingJob(host_group="series.invalid", queue_priority=100)

    try:
        queue.add(active)
        queue.start()
        assert _wait_until(lambda: active.started.is_set())
        queue.add(movie)
        queue.add_front(series)
        active.release.set()
        assert _wait_until(lambda: movie.started.is_set())
        assert not series.started.is_set()
    finally:
        active.release.set()
        movie.release.set()
        series.release.set()
        assert _wait_until(lambda: queue.active_count() == 0)
