"""Deterministic scan safety tests: no network, sleep or real media required."""
import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from integrations.jellyfin_scans import ScanManager, dispatch_lock
from integrations.jellyfin_client import JellyfinClient
import integrations.jellyfin_client as jellyfin


class Client:
    configured = True
    base_url = "http://jellyfin.invalid"
    def __init__(self):
        self.task = {"Id": "library", "State": "Idle", "last_start": 0}
        self.starts = 0
        self.status_reads = 0
        self.accepted = True
    def library_scan_task(self):
        self.status_reads += 1
        return self.task
    def start_library_scan(self, task_id):
        assert task_id == "library"
        self.starts += 1
        return self.accepted


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    client = Client()
    manager = ScanManager(tmp_path / "scans.sqlite3", lambda: client,
                          validate=lambda path: True, clock=lambda: now[0])
    def media(name="movie.mkv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"completed")
        return path
    return manager, client, now, media


def test_single_download_debounces_and_preserves_recognition(setup):
    manager, client, now, media = setup
    path = media()
    assert manager.request("download", path, {"title": "Movie", "kind": "movie"}) == "queued"
    manager.tick()
    assert client.status_reads == 0
    now[0] += 60
    manager.tick()
    assert client.starts == 1
    assert manager.snapshot()["counts"] == {"submitted": 1}
    manager.recognized = lambda evidence: evidence["title"] == "Movie"
    now[0] += 120
    manager.tick()
    assert manager.snapshot()["counts"] == {"recognized": 1}
    assert manager.request("seerr", path) == "deduplicated"
    now[0] += 500
    manager.tick()
    assert client.starts == 1


def test_parallel_completions_and_managers_coalesce_without_starvation(setup):
    manager, client, now, media = setup
    files = [media(f"{i}.mkv") for i in range(32)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(result == "queued" for result in pool.map(lambda path: manager.request("download", path), files))
    now[0] += 59
    manager.request("telegram", media("late.mkv"))
    now[0] += 1
    other = ScanManager(manager.path, lambda: client, validate=lambda path: True, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: (manager if i % 2 else other).tick(), range(16)))
    assert client.starts == 1
    assert manager.snapshot()["counts"] == {"submitted": 33}
    assert manager.snapshot()["avoided"] == 32


@pytest.mark.parametrize("state", ["Running", "Cancelling"])
def test_requests_during_running_scan_are_retained_then_automatically_started(setup, state):
    manager, client, now, media = setup
    client.task["State"] = state
    manager.request("download", media())
    now[0] += 60
    for _ in range(10):
        manager.tick()
    assert client.starts == 0
    assert manager.snapshot()["counts"] == {"pending": 1}
    client.task["State"] = "Idle"
    manager.tick()
    assert client.starts == 1
    manager.request("download", media("next.mkv"))
    now[0] += 299
    manager.tick()
    assert client.starts == 1
    now[0] += 1
    manager.tick()
    assert client.starts == 2


def test_external_scan_start_also_enforces_cooldown(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    client.task["last_start"] = now[0]
    now[0] += 60
    manager.tick()
    assert manager.snapshot()["phase"] == "server_scan_cooldown"
    now[0] += 240
    manager.tick()
    assert client.starts == 1


@pytest.mark.parametrize("failure", ["status", "post"])
def test_unreachable_server_and_repeated_requests_have_finite_budget(setup, failure):
    manager, client, now, media = setup
    path = media()
    if failure == "status":
        client.task = None
    else:
        client.accepted = False
    manager.request("download", path)
    for _ in range(12):
        now[0] += 1000
        manager.tick()
        manager.request("seerr", path)
    assert manager.snapshot()["counts"] == {"failed": 1}
    assert manager.snapshot()["recent_failures"][0]["attempts"] == 3
    assert client.starts == (0 if failure == "status" else 3)
    assert client.status_reads <= 6


def test_backoff_does_not_retry_early_and_recovers(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    now[0] += 60
    client.accepted = False
    manager.tick()
    now[0] += 299
    manager.tick()
    assert client.starts == 1
    now[0] += 1
    client.accepted = True
    manager.tick()
    assert client.starts == 2
    assert manager.snapshot()["counts"] == {"submitted": 1}


@pytest.mark.parametrize("reason", ["invalid", "modified", "deleted", "during_probe"])
def test_invalid_or_unstable_files_never_scan_and_are_never_deleted(setup, reason):
    manager, client, now, media = setup
    path = media()
    manager.request("download", path)
    if reason == "invalid":
        manager.validate = lambda path: False
    elif reason == "modified":
        path.write_bytes(b"still merging")
    elif reason == "deleted":
        path.unlink()
    else:
        def mutate(value):
            path.write_bytes(b"changed during ffprobe")
            return True
        manager.validate = mutate
    now[0] += 60
    manager.tick()
    assert client.starts == 0
    assert manager.snapshot()["counts"] == {"failed": 1}
    assert path.exists() == (reason != "deleted")


@pytest.mark.parametrize("name", [".downloading/file.mkv", "file.part", "file.mp4.tmp", "missing.mkv"])
def test_staging_and_missing_files_are_rejected_before_probing(setup, name):
    manager, client, now, media = setup
    path = media(name)
    if name == "missing.mkv":
        path.unlink()
    assert manager.request("download", path) == "invalid_final_file"
    now[0] += 1000
    manager.tick()
    assert client.status_reads == 0


def test_existing_media_validator_rejects_tiny_file_without_deleting_it(setup):
    manager, client, now, media = setup
    path = media()
    path.write_bytes(b"x" * 49)
    manager.validate = ScanManager._validate
    manager.request("download", path)
    now[0] += 60
    manager.tick()
    assert client.starts == 0
    assert path.read_bytes() == b"x" * 49


def test_restart_preserves_pending_work_and_ambiguous_dispatch_cooldown(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    now[0] += 60
    manager = ScanManager(manager.path, lambda: client, validate=lambda path: True, clock=lambda: now[0])
    # Simulate process death after durable dispatch reservation, before its result.
    with manager.db() as db:
        db.execute("UPDATE media SET state='dispatching',attempts=1,due=?", (now[0] + 300,))
        db.execute("UPDATE scans SET last_attempt=?", (now[0],))
    manager.tick()
    assert client.starts == 0
    now[0] += 300
    manager.tick()
    assert client.starts == 1
    assert manager.snapshot()["counts"] == {"submitted": 1}


@pytest.mark.parametrize("present", [False, None])
def test_accepted_scan_without_recognition_never_becomes_scan_loop(setup, present):
    manager, client, now, media = setup
    manager.recognized = lambda evidence: present
    path = media()
    manager.request("download", path)
    now[0] += 60
    manager.tick()
    for _ in range(35):
        now[0] += 60
        manager.request("telegram", path)
        manager.tick()
    assert client.starts == 1
    assert manager.snapshot()["counts"] == {"failed": 1}


def test_scan_becoming_active_during_validation_is_not_restarted(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    def validate(path):
        client.task = {"Id": "library", "State": "Running"}
        return True
    manager.validate = validate
    now[0] += 60
    manager.tick()
    assert client.starts == 0
    assert manager.snapshot()["counts"] == {"pending": 1}


def test_pending_work_eventually_expires_without_indefinite_status_polling(setup):
    manager, client, now, media = setup
    client.task["State"] = "Running"
    manager.request("download", media())
    now[0] += 86401
    manager.tick()
    assert manager.snapshot()["counts"] == {"failed": 1}
    assert client.status_reads == 0


def test_plex_subclass_does_not_call_inherited_jellyfin_endpoints(setup):
    from integrations.plex_client import PlexClient
    manager, client, now, media = setup
    plex = PlexClient("http://plex.invalid", "secret")
    calls = []
    plex.library_scan_task = lambda: pytest.fail("Plex must not use Jellyfin tasks")
    plex.refresh_library = lambda: calls.append(True) or True
    manager.get_client = lambda: plex
    manager.request("download", media())
    now[0] += 60
    manager.tick()
    assert calls == [True]


def _process_tick(database, counter, start):
    client = Client()
    def submit(task_id):
        with counter.get_lock():
            counter.value += 1
        return True
    client.start_library_scan = submit
    manager = ScanManager(database, lambda: client, validate=lambda path: True, clock=lambda: 1060)
    start.wait(10)
    manager.tick()


def test_real_processes_share_dispatch_reservation(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    context = multiprocessing.get_context("spawn")
    count = context.Value("i", 0)
    start = context.Event()
    processes = [context.Process(target=_process_tick, args=(str(manager.path), count, start)) for _ in range(3)]
    try:
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        assert count.value == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(3)


def _hold_lock(path, ready, release):
    with dispatch_lock(path) as acquired:
        ready.set()
        if acquired:
            release.wait(10)


def test_os_releases_lock_after_process_death(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    path = str(tmp_path / "scans.lock")
    process = context.Process(target=_hold_lock, args=(path, ready, release))
    process.start()
    try:
        assert ready.wait(10)
        with dispatch_lock(path) as acquired:
            assert not acquired
        process.terminate()
        process.join(5)
        with dispatch_lock(path) as acquired:
            assert acquired
    finally:
        if process.is_alive():
            process.terminate()
        process.join(5)


@contextmanager
def response(payload):
    yield SimpleNamespace(read=lambda limit=None: json.dumps(payload).encode())


@pytest.mark.parametrize("state", ["Idle", "Running", "Cancelling"])
def test_verified_scheduled_task_api_and_authentication(monkeypatch, state):
    client = JellyfinClient("http://jf.invalid", "private-key")
    calls = []
    def open_url(request, **kwargs):
        calls.append(request)
        return response([{"Key": "RefreshLibrary", "Id": "a/b", "State": state,
                          "LastExecutionResult": {"StartTimeUtc": "2026-10-01T12:00:00Z"}}])
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", open_url)
    task = client.library_scan_task()
    assert task["State"] == state
    assert task["last_start"] > 0
    assert client.start_library_scan(task["Id"])
    assert [call.full_url for call in calls] == ["http://jf.invalid/ScheduledTasks", "http://jf.invalid/ScheduledTasks/Running/a%2Fb"]
    assert [call.get_method() for call in calls] == ["GET", "POST"]
    assert all(call.get_header("Authorization") == 'MediaBrowser Token="private-key"' for call in calls)
    assert client.refresh_library() is False
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [{}, [], [None], [{"Key": "RefreshLibrary", "Id": "x", "State": "Unknown"}],
                                      [{"Key": "RefreshLibrary", "Id": 8, "State": "Idle"}],
                                      [{"Key": "RefreshLibrary", "Id": "x", "State": "Idle"}] * 2])
def test_invalid_status_responses_fail_closed(monkeypatch, payload):
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", lambda *args, **kwargs: response(payload))
    assert JellyfinClient("http://jf.invalid", "key").library_scan_task() is None


@pytest.mark.parametrize("failure", ["403", "500", "timeout", "json"])
def test_api_errors_do_not_expose_credentials(monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise ValueError(f"{failure} private-key http://secret.invalid")
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", fail)
    client = JellyfinClient("http://jf.invalid", "private-key")
    assert client.library_scan_task() is None
    assert client.start_library_scan("x") is False
    assert "private-key" not in caplog.text
    assert "secret.invalid" not in caplog.text

def test_restart_worker_drains_persisted_work_and_starts_only_one_thread(setup):
    import threading
    manager, client, now, media = setup
    manager.request("download", media())
    now[0] += 60
    submitted = threading.Event()
    restarted = ScanManager(manager.path, lambda: client, validate=lambda path: True,
                            clock=lambda: now[0], on_submitted=submitted.set)
    try:
        restarted.start()
        worker = restarted.thread
        restarted.start()
        assert restarted.thread is worker
        assert submitted.wait(2)
        assert client.starts == 1
    finally:
        restarted.stop()
    assert not restarted.thread.is_alive()


def test_restart_retains_successful_scan_cooldown(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    now[0] += 60
    manager.tick()
    manager.request("download", media("next.mkv"))
    restarted = ScanManager(manager.path, lambda: client, validate=lambda path: True, clock=lambda: now[0])
    now[0] += 60
    restarted.tick()
    assert client.starts == 1
    now[0] += 240
    restarted.tick()
    assert client.starts == 2


def test_changed_server_cannot_receive_old_server_requests(setup):
    manager, client, now, media = setup
    manager.request("download", media())
    old_url = client.base_url
    client.base_url = "http://other.invalid"
    now[0] += 60
    manager.tick()
    assert client.starts == 0
    client.base_url = old_url
    manager.tick()
    assert client.starts == 1


def test_real_http_and_decode_errors_fail_closed(monkeypatch):
    from urllib.error import HTTPError, URLError
    client = JellyfinClient("http://jf.invalid", "private-key")
    for error in [HTTPError(client.base_url, 403, "Forbidden", {}, None),
                  HTTPError(client.base_url, 500, "Error", {}, None),
                  URLError("timeout")]:
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr(jellyfin.urllib.request, "urlopen", fail)
        assert client.library_scan_task() is None
        assert client.start_library_scan("library") is False
    @contextmanager
    def invalid():
        yield SimpleNamespace(read=lambda limit: b"{malformed json")
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", lambda *args, **kwargs: invalid())
    assert client.library_scan_task() is None
