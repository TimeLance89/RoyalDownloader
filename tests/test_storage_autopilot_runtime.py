import json
import threading
from types import SimpleNamespace

import pytest

import application_services.storage_autopilot_runtime as runtime
import application_services.download_storage_guard as guard
import storage.storage_autopilot as autopilot
import storage.storage_inventory as inventory
from media.downloader import DownloadJob
from storage.storage_policy import GIB


@pytest.fixture
def destination(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "state_path", lambda: tmp_path / "autopilot.json")
    root = {"key": "movies", "path": str(tmp_path), "resolved_path": str(tmp_path), "available": True,
            "writable": True, "location_mode": "media", "volume_id": "disk", "label": "Disk",
            "total_bytes": 1000 * GIB, "free_bytes": 500 * GIB, "used_percent": 50}
    monkeypatch.setattr(autopilot, "storage_snapshot", lambda: {"roots": [dict(root)], "summary": {}})
    import storage.storage_move_runtime as moves
    monkeypatch.setattr(moves, "list_move_jobs", lambda: {"jobs": [], "history": [], "active_count": 0})
    monkeypatch.setattr(autopilot, "list_move_jobs", moves.list_move_jobs)
    monkeypatch.setattr(runtime, "queue_context", lambda: [])
    autopilot.save_policy({"mode": "automatic"})
    autopilot.save_volume("movies", {"reserve_gib": 50})
    job = DownloadJob("https://media.example/video.mp4", "mp4", tmp_path / "Movie.mp4", job_id="logical", provider="filmpalast", queue_slug="movie:movie")
    def reserve(document):
        document["reservations"][job.job_id] = {"root": "movies", "size_bytes": 8 * GIB,
                                               "path": str(job.out_path), "volume_id": "disk"}
    inventory.transact(reserve)
    return root, job


def test_actual_reserve_blocks_start_and_updates_remaining_known_size(destination, monkeypatch):
    root, job = destination
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=57 * GIB))
    assert "Speicherreserve" in guard._storage_budget_check(job, force=True)
    prepared, message = guard._prepare_staging(job)
    assert not prepared and job.failure_kind == "storage" and not job.staging_dir.exists()
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * GIB))
    job.total_bytes = 30 * GIB
    job.downloaded_bytes = 10 * GIB
    assert guard._storage_budget_check(job, force=True) == ""
    reservation = inventory.read_state()["reservations"][job.job_id]
    assert reservation["size_bytes"] == 20 * GIB and reservation["expected_total_bytes"] == 30 * GIB


def test_actual_reserve_includes_other_jobs_and_stops_on_offline_mount(destination, monkeypatch):
    root, job = destination
    inventory.transact(lambda document: document["reservations"].update({"other": {"root": "movies", "size_bytes": 45 * GIB}}))
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * GIB))
    assert guard._storage_budget_check(job, force=True)
    root["available"] = False
    assert "offline" in guard._storage_budget_check(job, force=True)


def test_cross_volume_staging_retains_entire_target_reservation(destination, monkeypatch):
    root, job = destination
    monkeypatch.setattr(guard, "_same_filesystem", lambda *_paths: False)
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * GIB))
    job.total_bytes = 30 * GIB
    job.downloaded_bytes = 29 * GIB
    assert guard._storage_budget_check(job, force=True) == ""
    reservation = inventory.read_state()["reservations"][job.job_id]
    assert reservation["size_bytes"] == 30 * GIB
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=79 * GIB))
    assert guard._storage_budget_check(job, force=True)


def test_publication_uses_exact_copy_budget_and_preserves_source_when_unsafe(destination, monkeypatch):
    root, job = destination
    source = job.out_path.parent / "verified.mp4"
    source.write_bytes(b"validated media")
    monkeypatch.setattr(guard, "_same_filesystem", lambda *_paths: False)
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=50 * GIB + source.stat().st_size - 1))
    with pytest.raises(OSError, match="Speicherreserve"):
        guard._commit_file(job, source, job.out_path)
    assert source.exists() and not job.out_path.exists() and job.failure_kind == "storage"
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=50 * GIB + source.stat().st_size))
    assert guard._storage_budget_check(job, force=True, publishing_source=source) == ""
    assert inventory.read_state()["reservations"][job.job_id]["size_bytes"] == source.stat().st_size


def test_same_volume_publication_drops_unknown_estimate_without_second_copy(destination, monkeypatch):
    root, job = destination
    source = job.out_path.parent / "verified.mp4"
    source.write_bytes(b"validated media")
    monkeypatch.setattr(guard, "_same_filesystem", lambda *_paths: True)
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=50 * GIB))
    assert guard._storage_budget_check(job, force=True, publishing_source=source) == ""
    assert inventory.read_state()["reservations"][job.job_id]["size_bytes"] == 0


def test_corrupt_safety_data_cannot_silently_lower_reserve(destination):
    root, job = destination
    inventory.state_path().write_text("broken", encoding="utf-8")
    assert guard._storage_budget_check(job, force=True)
    with pytest.raises(ValueError, match="Sicherheitsdaten"):
        runtime.place_download({"job_id": job.job_id, "media_type": "movie"}, job.out_path)


def test_monitor_keeps_legacy_guard_and_optional_inventory_cannot_break_commit(destination, monkeypatch):
    root, job = destination
    autopilot.save_policy({"mode": "monitor"})
    monkeypatch.setattr(guard, "_MIN_FREE_BYTES", 5 * GIB)
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=4 * GIB))
    assert guard._storage_budget_check(job, force=True) == ""
    assert not guard._prepare_staging(job)[0]
    monkeypatch.setattr(guard.shutil, "disk_usage", lambda _path: SimpleNamespace(free=6 * GIB))
    monkeypatch.setattr(guard, "_ORIGINAL_PREPARE_STAGING", lambda _job: (True, "legacy"))
    assert guard._prepare_staging(job) == (True, "legacy")
    monkeypatch.setattr(guard, "_ORIGINAL_COMMIT_FILE", lambda *_args: job.out_path)
    monkeypatch.setattr(runtime, "record_publication", lambda *_args: (_ for _ in ()).throw(OSError("metadata unavailable")))
    assert guard._commit_file(job, job.out_path, job.out_path) == job.out_path


def test_publication_records_actual_collision_name_and_releases_reservation(destination):
    root, job = destination
    path = job.out_path.with_name("Movie~collision.mp4")
    path.write_bytes(b"verified")
    runtime.record_publication(job, path)
    document = inventory.read_state()
    item = next(iter(document["inventory"].values()))
    assert item["relative_path"] == path.name and item["owned"]
    assert item["owned_files"] == {path.name: 8}
    assert item["owned_stamps"][path.name] == [path.stat().st_mtime_ns, path.stat().st_ino]
    assert job.job_id not in document["reservations"]


def test_worker_fallback_classifies_real_media_and_reconciles_stale_reservation(destination, monkeypatch):
    root, movie = destination
    episode = DownloadJob("https://media.example/video.mp4", "mp4", movie.out_path.parent / "Show/Episode.mp4", provider="aniworld", queue_slug="show:s1e2", job_id="episode")
    state = SimpleNamespace(queue_claim_lock=threading.RLock(), queue_jobs={},
                            dl_queue=SimpleNamespace(active_jobs=lambda: [movie], pending_jobs=lambda: [episode]))
    monkeypatch.setattr(runtime, "backend_value", lambda _key: state)
    # Undo only the fixture's queue seam for this test.
    # The real function is retained below independently of the fixture seam.
    jobs = _REAL_QUEUE_CONTEXT()
    assert [job["media_type"] for job in jobs] == ["movie", "anime"]
    runtime.reconcile_reservations([jobs[1]])
    assert inventory.read_state()["reservations"] == {}


_REAL_QUEUE_CONTEXT = runtime.queue_context


@pytest.mark.parametrize("url", ["file:///secret", "ftp://host", "http://[invalid"])
def test_playback_check_rejects_unsafe_or_invalid_config_without_network(monkeypatch, url):
    monkeypatch.setattr(runtime.appconfig, "load_jellyfin", lambda: {"url": url, "api_key": "secret"})
    assert runtime.playback_idle() is False


@pytest.mark.parametrize("evidence,expected", [(True, False), (False, True), (None, False)])
def test_playback_check_is_fail_safe(monkeypatch, evidence, expected):
    monkeypatch.setattr(runtime.appconfig, "load_jellyfin", lambda: {"url": "http://jellyfin:8096", "api_key": "secret"})
    monkeypatch.setattr(runtime.JellyfinClient, "has_active_playback", lambda _self: evidence)
    assert runtime.playback_idle() is expected


@pytest.mark.parametrize("payload,expected", [([], False), ([{"NowPlayingItem": {"Id": "movie"}}], True),
                                             ([{"TranscodingInfo": {"Bitrate": 10}}], True), ({"Items": []}, None), (["invalid"], None)])
def test_jellyfin_sessions_contract_is_bounded_and_validated(monkeypatch, payload, expected):
    from integrations.jellyfin_client import JellyfinClient
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return json.dumps(payload).encode()
    monkeypatch.setattr("integrations.jellyfin_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    assert JellyfinClient("http://jellyfin:8096", "secret").has_active_playback() is expected
