import threading
import time

import server  # noqa: F401 - registers the application service backend
from application_services import movie_catalog


def test_slow_movie_provider_continues_after_request_deadline(monkeypatch):
    release = threading.Event()

    def slow_provider(*_args):
        release.wait(timeout=1)
        return []

    monkeypatch.setattr(movie_catalog, "_fetch_movie_provider_page", slow_provider)
    timed_out = [False]
    started = time.monotonic()
    try:
        result = movie_catalog._load_movie_provider_pages(
            "new",
            "",
            [("filmpalast", 99)],
            deadline=time.monotonic() + 0.04,
            timed_out=timed_out,
        )
    finally:
        release.set()

    assert time.monotonic() - started < 0.3
    assert result == {}
    assert timed_out == [True]
