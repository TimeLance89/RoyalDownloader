"""Restart-safe direct HTTP transfer without external network access."""

from __future__ import annotations

from pathlib import Path

import pytest

from media import downloader
from media.http_resume import HTTPResumeStore, range_matches, strong_etag


class FakeHTTPResponse:
    def __init__(self, body, *, status=200, etag='"v1"', total=None, start=0):
        self.status_code = status
        if total is None:
            total = len(body)
        self.headers = {
            "Content-Type": "video/mp4",
            "ETag": etag,
            "Content-Length": str(len(body)),
        }
        if status == 206:
            self.headers["Content-Range"] = (
                f"bytes {start}-{start + len(body) - 1}/{total}"
            )
        self.body = body
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=262144):
        del chunk_size
        yield self.body

    def close(self):
        self.closed = True


def make_job(tmp_path, attempt):
    job = downloader.DownloadJob(
        "https://media.example.test/test.mp4", "mp4",
        tmp_path / "test.mp4", queue_slug="movie:test",
        job_id="stable-logical-job", attempt_id=attempt, allow_slow=True,
    )
    job._fallback_staging_root = tmp_path / "fallback"
    return job


def test_only_strong_etags_allow_range_resume():
    assert strong_etag('"v1"') == '"v1"'
    assert not strong_etag('W/"v1"')
    assert not strong_etag("bare-etag")
    assert range_matches({
        "ETag": '"v1"', "Content-Range": "bytes 4-9/10",
        "Content-Length": "6",
    }, 4, 10, '"v1"')
    assert not range_matches({
        "ETag": '"v2"', "Content-Range": "bytes 4-9/10",
    }, 4, 10, '"v1"')
    assert not range_matches({
        "ETag": '"v1"', "Content-Range": "bytes 0-9/10",
    }, 4, 10, '"v1"')
    assert not range_matches({
        "ETag": '"v1"', "Content-Range": "bytes 4-9/11",
    }, 4, 10, '"v1"')


def test_direct_mp4_resumes_after_new_attempt_without_redownloading_prefix(monkeypatch, tmp_path):
    from core import egress_curl as curl

    calls = []
    responses = iter([
        FakeHTTPResponse(b"A" * 400, total=400),
        FakeHTTPResponse(b"B" * 624, status=206, start=400, total=1024),
    ])

    def fake_get(url, *, headers, **kwargs):
        del url, kwargs
        calls.append(dict(headers))
        return next(responses)

    monkeypatch.setattr(curl, "get", fake_get)
    monkeypatch.setattr(downloader, "ensure_public_http_url", lambda _url: None)
    monkeypatch.setattr(downloader, "request_proxy_kwargs", lambda _url: {})

    first = make_job(tmp_path, "attempt-one")
    # Simulates connection interruption: response announced the full entity,
    # but the first request supplied only 400 of 1024 bytes.
    original_get = curl.get
    def first_response(url, *, headers, **kwargs):
        resp = original_get(url, headers=headers, **kwargs)
        resp.headers["Content-Length"] = "1024"
        return resp
    monkeypatch.setattr(curl, "get", first_response)
    success, msg = first._download_direct()
    assert not success and "vorzeitig" in msg
    saved = first._http_resume_store().load()
    assert saved and saved.offset == 400 and saved.total == 1024
    monkeypatch.setattr(curl, "get", original_get)

    second = make_job(tmp_path, "attempt-two")
    success, msg = second._download_direct()
    assert success, msg
    assert second.staging_path.read_bytes() == b"A" * 400 + b"B" * 624
    assert second._http_resume_store().load() is None
    assert "Range" not in calls[0]
    assert calls[1]["Range"] == "bytes=400-"
    assert calls[1]["If-Range"] == '"v1"'


def test_changed_etag_refuses_to_append_and_starts_from_zero(monkeypatch, tmp_path):
    from core import egress_curl as curl

    calls = []
    responses = iter([
        FakeHTTPResponse(b"X" * 500, status=206, etag='"changed"', total=1024, start=400),
        FakeHTTPResponse(b"Y" * 1024, status=200, etag='"changed"'),
    ])
    def fake_get(url, *, headers, **kwargs):
        del url, kwargs
        calls.append(dict(headers))
        return next(responses)
    monkeypatch.setattr(curl, "get", fake_get)
    monkeypatch.setattr(downloader, "ensure_public_http_url", lambda _url: None)
    monkeypatch.setattr(downloader, "request_proxy_kwargs", lambda _url: {})

    job = make_job(tmp_path, "attempt-one")
    store = job._http_resume_store()
    part = store.prepare(total=1024, etag='"v1"')
    part.write_bytes(b"A" * 400)

    ok, msg = job._download_direct()
    assert ok, msg
    assert job.staging_path.read_bytes() == b"Y" * 1024
    assert calls[0]["Range"] == "bytes=400-"
    assert "Range" not in calls[1]


def test_unvalidated_partials_are_not_reused(tmp_path):
    job = make_job(tmp_path, "attempt-one")
    store = job._http_resume_store()
    part = store.prepare(total=1000, etag='"v1"')
    part.write_bytes(b"a" * 200)
    other_url = HTTPResumeStore(
        job.out_path, job.job_id, "https://media.example.test/other.mp4",
        job._fallback_staging_root,
    )
    assert other_url.load() is None
    assert store.load() is not None

    # Malformed metadata must never be treated as a valid checkpoint.
    (part.parent / "checkpoint.json").write_text("[]")
    assert store.load() is None
    assert part.read_bytes() == b"a" * 200


def test_full_checkpoint_is_revalidated_by_standard_finalize_path(monkeypatch, tmp_path):
    from core import egress_curl as curl

    job = make_job(tmp_path, "attempt-two")
    part = job._http_resume_store().prepare(total=1024, etag='"v1"')
    part.write_bytes(b"A" * 1024)
    monkeypatch.setattr(curl, "get", lambda *_a, **_k: pytest.fail("no HTTP call needed"))
    ok, msg = job._download_direct()
    assert ok, msg
    assert job.staging_path.read_bytes() == b"A" * 1024
    # _run() still calls _finalize(), which checks real video+audio before publish.


def test_symlinked_checkpoint_is_rejected(tmp_path):
    job = make_job(tmp_path, "attempt-one")
    store = job._http_resume_store()
    part = store.prepare(total=1024, etag='"v1"')
    part.write_bytes(b"A" * 200)
    part.unlink()
    part.symlink_to(tmp_path / "outside.mp4")
    assert store.load() is None
    # A symlink must never be dereferenced, even if another safe staging
    # location remains available as a fallback.
    store.prepare(total=1024, etag='"v1"')
    assert part.is_symlink()
    assert not (tmp_path / "outside.mp4").exists()


def test_expired_checkpoint_cleanup_preserves_current_and_foreign_files(tmp_path):
    import os
    import time
    from media.http_resume import cleanup_expired_http_resumes

    job = make_job(tmp_path, "attempt-one")
    store = job._http_resume_store()
    part = store.prepare(total=1024, etag='"v1"')
    part.write_bytes(b"A" * 200)
    root = part.parent.parent.parent
    foreign = root / "unrelated"
    foreign.mkdir()
    (foreign / "important.txt").write_text("keep")
    old = time.time() - 9 * 24 * 3600
    os.utime(part, (old, old))

    planned = cleanup_expired_http_resumes([root], preview=True)
    assert len(planned) == 1
    assert planned[0]["size_bytes"] == 200
    assert cleanup_expired_http_resumes([root]) == 1
    assert not part.exists()
    assert (foreign / "important.txt").read_text() == "keep"


def test_user_cancel_discards_checkpoint_but_update_restart_preserves_it(tmp_path):
    first = make_job(tmp_path, "user-cancel")
    store = first._http_resume_store()
    path = store.prepare(total=1024, etag='"v1"')
    path.write_bytes(b"A" * 200)
    first.cancel()
    first._run()
    assert store.load() is None

    second = make_job(tmp_path, "update-cancel")
    store = second._http_resume_store()
    path = store.prepare(total=1024, etag='"v1"')
    path.write_bytes(b"B" * 200)
    second.cancel(preserve_resume=True)
    second._run()
    assert store.load() is not None


def test_queue_restart_flag_only_changes_real_download_job_cancellation():
    from media.downloader import DownloadQueue

    class OtherWork:
        def __init__(self):
            self.was_cancelled = False
        def cancel(self):
            self.was_cancelled = True

    queue = DownloadQueue()
    movie = downloader.DownloadJob(
        "https://media.example.test/movie.mp4", "mp4", Path("/tmp/movie.mp4"),
        queue_slug="movie:123",
    )
    other = OtherWork()
    # Inspect the queue contract without starting background jobs.
    import threading
    with queue._lock:
        queue._active[1] = (movie, threading.Thread(), 0)
        queue._active[2] = (other, threading.Thread(), 0)
    # Avoid the reaper's join of never-started mock threads.
    queue._reap_cancelled = lambda _jobs: None
    queue.cancel_all(preserve_resume=True)
    assert movie._cancelled and movie._preserve_resume_on_cancel
    assert other.was_cancelled
