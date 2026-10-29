"""Regression tests for scan producers and read-only recognition consumers."""
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import server  # register the existing composition root
from application_services import download_lifecycle as lifecycle, seerr, telegram_requests as telegram
from application_services import media_scans
from integrations.seerr_client import SeerrRequest


@pytest.fixture
def telegram_runtime(monkeypatch):
    state = SimpleNamespace(
        jellyfin_cache_lock=threading.RLock(), jellyfin_config_generation=1,
        jellyfin_movie_data_generation=1, jellyfin_episode_data_generation=1,
        jellyfin_library_available=True, jellyfin_episodes_available=True,
        jellyfin_series_available=True,
    )
    client = SimpleNamespace(configured=True, match=lambda *args, **kwargs: True,
                             series_ids_for=lambda *args, **kwargs: {"series-id"},
                             has_episode=lambda *args, **kwargs: True)
    requests, messages, reads = [], [], []
    monkeypatch.setattr(telegram, "state", state)
    monkeypatch.setattr(server, "get_jellyfin_client", lambda: client)
    monkeypatch.setattr(server, "log", lambda *args: None)
    monkeypatch.setattr(server, "_telegram_send", lambda chat, message: messages.append(message))
    monkeypatch.setattr(telegram, "request_media_scan", lambda *args, **kwargs: requests.append((args, kwargs)))
    def cached(*, force=False):
        reads.append(force)
        return []
    for name in ("get_jellyfin_library", "get_jellyfin_episodes", "get_jellyfin_series"):
        monkeypatch.setattr(server, name, cached)
    return requests, messages, reads


def test_telegram_movie_hands_off_final_path_without_direct_scan(telegram_runtime):
    requests, messages, reads = telegram_runtime
    telegram._telegram_finish_job({"chat_id": 1, "title": "Movie", "tmdb_id": "42"}, True, "ok", Path("final.mkv"))
    assert requests[0][0] == ("telegram", Path("final.mkv"))
    assert requests[0][1]["evidence"]["tmdb_id"] == "42"
    assert reads == [False]
    assert "jetzt in Jellyfin" in messages[-1]


def test_telegram_failed_download_never_hands_off(telegram_runtime):
    requests, messages, reads = telegram_runtime
    telegram._telegram_finish_job({"chat_id": 1, "title": "Movie"}, False, "bad", Path("bad.mkv"))
    assert requests == reads == []
    assert "fehlgeschlagen" in messages[-1]


def test_telegram_series_only_hands_off_successful_episodes(telegram_runtime):
    requests, messages, reads = telegram_runtime
    telegram._telegram_finish_series_request({"chat_id": 1, "title": "Series", "tmdb_id": "42",
        "completed": [{"path": "episode.mkv", "season": 1, "episode": 2}], "failed": ["S01E03: failed"]})
    assert len(requests) == 1
    assert requests[0][1]["evidence"]["episode"] == 2
    assert reads == [False, False]
    assert "jetzt in Jellyfin" in messages[-1]
    assert "1 fehlgeschlagen" in messages[-1]


@pytest.mark.parametrize("paths", [[], ["final.mkv"]])
def test_seerr_status_retries_are_persistently_bounded_and_have_backoff(monkeypatch, paths):
    previous = {"completed_paths": paths}
    requests, updates = [], []
    clock = [10000.0]
    monkeypatch.setattr(seerr.time, "time", lambda: clock[0])
    monkeypatch.setattr(seerr, "request_media_scan", lambda *args: requests.append(args) or "deduplicated")
    def update(request_id, **changes):
        previous.update(changes)
        updates.append(changes)
    monkeypatch.setattr(server, "_seerr_update_record", update)
    request = SeerrRequest(1, "movie", 42)
    for _ in range(20):
        seerr._seerr_retry_completed_scan(request, previous)
        seerr._seerr_retry_completed_scan(request, previous)
        clock[0] += 10000
    assert len(updates) == 3
    assert previous["scan_retry_attempts"] == 3
    assert requests == ([("seerr", "final.mkv")] * 3 if paths else [])
    assert previous["status"] == "completed"
    # Simulated restart reads the persisted budget rather than resetting it.
    seerr._seerr_retry_completed_scan(request, dict(previous))
    assert len(updates) == 3


@pytest.mark.parametrize("ok", [True, False])
def test_seerr_persists_only_successful_final_paths(monkeypatch, ok):
    record = {"pending_slugs": ["movie"]}
    state = SimpleNamespace(seerr_requests_lock=threading.RLock(), seerr_requests={"1": record})
    monkeypatch.setattr(seerr, "state", state)
    monkeypatch.setattr(server, "_save_seerr_requests_locked", lambda: None)
    monkeypatch.setattr(server, "log", lambda *args: None)
    seerr._seerr_job_result({"request_id": 1}, "movie", ok, "result", Path("final.mkv"))
    assert record.get("completed_paths", []) == (["final.mkv"] if ok else [])
    assert record["status"] == ("completed" if ok else "failed")


@pytest.mark.parametrize("ok", [True, False])
def test_lifecycle_handoff_is_only_after_success(monkeypatch, ok):
    state = SimpleNamespace(queue_claim_lock=threading.RLock(), download_state_lock=threading.RLock(),
                            done_jobs=0, total_jobs=1, done_slugs=set(),
                            dl_queue=SimpleNamespace(active_count=lambda: 0, pending_count=lambda: 0))
    calls = []
    monkeypatch.setattr(lifecycle, "state", state)
    monkeypatch.setattr(lifecycle, "request_media_scan", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(server, "log", lambda *args: None)
    monkeypatch.setattr(server, "broadcast", lambda event: None)
    monkeypatch.setattr(lifecycle, "_ensure_jellyfin_media_readable", lambda path: None)
    lifecycle.on_job_done(ok, "result", "Movie", Path("final.mkv"))
    assert len(calls) == int(ok)
    if ok:
        assert calls[0][0] == ("download", Path("final.mkv"))


def test_missing_catalog_metadata_does_not_lose_valid_media_request(monkeypatch):
    calls = []
    fake = SimpleNamespace(request=lambda *args: calls.append(args) or "queued", start=lambda: None)
    monkeypatch.setattr(media_scans, "media_scan_manager", lambda: fake)
    def broken(slug):
        raise KeyError("catalog refreshed")
    monkeypatch.setattr(media_scans, "_download_evidence", broken)
    assert media_scans.request_media_scan("download", "final.mkv", slug="movie") == "queued"
    assert calls == [("download", "final.mkv", {})]


def test_recognition_uses_existing_movie_and_series_identity_rules(monkeypatch):
    from integrations.jellyfin_client import JellyfinClient
    backend = {
        "state": SimpleNamespace(jellyfin_cache_lock=threading.RLock(), jellyfin_config_generation=1,
                                 jellyfin_library_available=True, jellyfin_episodes_available=True,
                                 jellyfin_series_available=True),
        "get_jellyfin_client": lambda: JellyfinClient("http://jf.invalid", "key"),
        "get_jellyfin_library": lambda: [{"name": "Movie", "year": 2020, "tmdb_id": "42"}],
        "get_jellyfin_series": lambda: [{"id": "series-id", "name": "Series", "tmdb_id": "43"}],
        "get_jellyfin_episodes": lambda: [{"series_id": "series-id", "season": 1, "episode": 2}],
    }
    monkeypatch.setattr(media_scans, "backend_value", backend.__getitem__)
    assert media_scans._recognized({"title": "Movie", "kind": "movie", "year": "2020", "tmdb_id": "42"})
    assert not media_scans._recognized({"title": "Movie", "kind": "movie", "year": "2024", "tmdb_id": "99"})
    assert media_scans._recognized({"title": "Series", "kind": "series", "tmdb_id": "43", "season": 1, "episode": 2})
    assert not media_scans._recognized({"title": "Series", "kind": "series", "tmdb_id": "43", "season": 1, "episode": 3})
    backend["state"].jellyfin_library_available = False
    assert media_scans._recognized({"title": "Movie", "kind": "movie", "year": "2020", "tmdb_id": "42"}) is None


def test_scan_storage_failure_keeps_web_startup_available_and_diagnostics_safe(monkeypatch, caplog):
    def broken():
        raise OSError("private-key /private/path")
    monkeypatch.setattr(media_scans, "media_scan_manager", broken)
    media_scans.start_media_scans()
    assert media_scans.media_scan_diagnostics() == {"phase": "storage_unavailable"}
    assert media_scans.request_media_scan("download", "final.mkv") == "handoff_failed"
    assert "private-key" not in caplog.text
    assert "/private/path" not in caplog.text

def test_late_completion_during_shutdown_is_persisted_without_restarting_worker(monkeypatch):
    calls = []
    fake = SimpleNamespace(request=lambda *args: calls.append('persist') or 'queued',
                           start=lambda: calls.append('start'), stop=lambda: calls.append('stop'))
    monkeypatch.setattr(media_scans, '_manager', fake)
    monkeypatch.setattr(media_scans, '_closing', False)
    media_scans.stop_media_scans()
    assert media_scans.request_media_scan('download', 'final.mkv') == 'queued'
    assert calls == ['stop', 'persist']
    media_scans.start_media_scans()
    assert calls == ['stop', 'persist', 'start']
