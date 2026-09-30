import json
from copy import deepcopy

import pytest

import storage.storage_autopilot as autopilot
import storage.storage_inventory as inventory
from storage.storage_placement import reserve_download, reserved_by_volume
from storage.storage_planner import plan_recommendations
from storage.storage_policy import GIB


@pytest.fixture
def disks(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "state_path", lambda: tmp_path / "autopilot.json")
    roots = []
    for key, name, free in (("movies", "main", 600), ("location:overflow", "overflow", 600), ("location:archive", "archive", 700)):
        path = tmp_path / name
        path.mkdir()
        roots.append({"key": key, "label": name, "path": str(path), "resolved_path": str(path),
                      "available": True, "writable": True, "location_mode": "media", "volume_id": name,
                      "free_bytes": free * GIB, "total_bytes": 1000 * GIB, "used_percent": 100 - free / 10})
    monkeypatch.setattr(autopilot, "storage_snapshot", lambda: {"roots": deepcopy(roots), "summary": {"volume_count": 3}})
    monkeypatch.setattr(autopilot, "list_move_jobs", lambda: {"jobs": [], "history": [], "active_count": 0})
    autopilot.save_volume("location:overflow", {"role": "overflow"})
    autopilot.save_volume("location:archive", {"role": "archive"})
    return roots


def test_default_monitor_and_advisor_do_not_change_path(disks):
    from pathlib import Path
    path = str(Path(disks[0]["path"]) / "Movie.mp4")
    assert reserve_download("one", Path(path), "movies", disks, [], [])["path"] == path
    autopilot.save_policy({"mode": "advisor"})
    assert not reserve_download("two", Path(path), "movies", disks, [], [])["changed"]
    assert inventory.read_state()["reservations"] == {}


def test_primary_then_overflow_and_retry_is_idempotent(disks):
    from pathlib import Path
    autopilot.save_policy({"mode": "automatic"})
    source = Path(disks[0]["path"]) / "Movie.mp4"
    first = reserve_download("one", source, "movies", disks, [], [])
    assert first["root"] == "movies"
    repeated = reserve_download("one", source, "movies", disks, [], [])
    assert repeated["path"] == first["path"]
    assert len(inventory.read_state()["reservations"]) == 1
    disks[0].update(free_bytes=180 * GIB, used_percent=82)
    second = reserve_download("two", source.with_name("Other.mp4"), "movies", disks, [], [])
    assert second["root"] == "location:overflow"
    assert any("Ausweichspeicher" in reason for reason in second["reasons"])


def test_custom_media_roots_on_same_volume_keep_movies_and_series_separate(disks):
    from pathlib import Path

    autopilot.save_policy({"mode": "automatic"})
    disks[0].update(free_bytes=180 * GIB, used_percent=82)

    shared = Path(disks[1]["path"])
    movie_target = shared / "movies"
    series_target = shared / "series"
    series_source_path = Path(disks[0]["path"]).parent / "series-main"
    movie_target.mkdir()
    series_target.mkdir()
    series_source_path.mkdir()

    disks[1].update(
        key="location:movies2", label="Filme Volume 2",
        path=str(movie_target), resolved_path=str(movie_target),
        volume_id="large-disk", free_bytes=900 * GIB, used_percent=10,
        allowed_media_types=["movies"],
    )
    disks[2].update(
        key="location:series2", label="Serien Volume 2",
        path=str(series_target), resolved_path=str(series_target),
        volume_id="large-disk", free_bytes=900 * GIB, used_percent=10,
        allowed_media_types=["series", "anime"],
    )
    disks.append({
        **disks[0],
        "key": "series",
        "label": "Serien",
        "path": str(series_source_path),
        "resolved_path": str(series_source_path),
    })

    movie = reserve_download(
        "movie-vol2", Path(disks[0]["path"]) / "Movie.mkv", "movies", disks, [], [],
    )
    series = reserve_download(
        "series-vol2", series_source_path / "Show" / "Season 1" / "E01.mkv",
        "series", disks, [], [],
    )

    assert movie["root"] == "location:movies2"
    assert Path(movie["path"]).parent == movie_target
    assert series["root"] == "location:series2"
    assert Path(series["path"]).relative_to(series_target) == Path("Show/Season 1/E01.mkv")


def test_same_physical_roots_share_budget_and_strictest_reserve(disks):
    alias = {**disks[0], "key": "series", "label": "series"}
    disks.append(alias)
    autopilot.save_volume("series", {"reserve_gib": 100})
    current = autopilot.get_autopilot()
    assert all(root["policy"]["reserve_gib"] == 100 for root in current["roots"] if root["volume_id"] == "main")
    document = inventory.read_state()
    document["reservations"] = {"one": {"root": "movies", "size_bytes": 10 * GIB}, "two": {"root": "series", "size_bytes": 20 * GIB}}
    assert reserved_by_volume(document, disks, [], []) == {"main": 30 * GIB}


def test_queue_and_move_reservations_cannot_overcommit(disks):
    document = inventory.read_state()
    document["reservations"] = {"one": {"root": "movies", "size_bytes": 40 * GIB}}
    queue = [{"job_id": "one", "media_type": "movie", "total_bytes": 40 * GIB},
             {"job_id": "two", "media_type": "movie", "total_bytes": 90 * GIB}]
    moves = [{"destination_root": "movies", "size_bytes": 70 * GIB}]
    assert reserved_by_volume(document, disks, queue, moves) == {"main": 200 * GIB}


def test_offline_mount_identity_is_retained_and_requires_confirmation(disks):
    autopilot.observe_volumes()
    old = inventory.read_state()["observations"]["location:archive"]
    disks[2]["available"] = False
    assert autopilot.get_autopilot()["roots"][2]["pressure"] == "offline"
    assert inventory.read_state()["observations"]["location:archive"] == old
    disks[2].update(available=True, volume_id="container-fallback")
    assert not autopilot.get_autopilot()["roots"][2]["available"]
    autopilot.save_volume("location:archive", {}, confirm_mount=True)
    assert autopilot.get_autopilot()["roots"][2]["available"]


def test_advisor_proposes_pressure_relief_and_dismiss_has_cooldown(disks):
    autopilot.save_policy({"mode": "advisor"})
    disks[0].update(used_percent=91, free_bytes=90 * GIB)
    item_id = inventory.identity("movies", "Movie.mp4")
    def seed(document):
        document["inventory"][item_id] = {"id": item_id, "root": "movies", "relative_path": "Movie.mp4",
                                         "name": "Movie", "size_bytes": 100 * GIB, "media_type": "movies", "owned": False}
    inventory.transact(seed)
    proposals = autopilot.refresh_recommendations()
    assert len(proposals) == 1
    assert proposals[0]["after_percent"] < proposals[0]["before_percent"]
    assert proposals[0]["automatic_eligible"] is False
    autopilot.dismiss_recommendation(proposals[0]["id"])
    assert all(item["state"] == "dismissed" for item in autopilot.refresh_recommendations())


def test_healthy_volume_and_cooldown_do_not_shuffle_content(disks):
    document = inventory.read_state()
    document["policy"]["mode"] = "automatic"
    item_id = inventory.identity("movies", "Movie.mp4")
    document["inventory"][item_id] = {"id": item_id, "root": "movies", "relative_path": "Movie.mp4",
                                      "name": "Movie", "size_bytes": 100 * GIB, "media_type": "movies", "owned": True}
    assert plan_recommendations(disks, document, now=1_000_000) == []
    disks[0].update(used_percent=91, free_bytes=90 * GIB)
    document["inventory"][item_id]["last_moved_at"] = 999_999
    assert plan_recommendations(disks, document, now=1_000_000) == []


def test_healthy_archives_are_not_periodically_rearchived(disks):
    document = inventory.read_state()
    document["policy"]["mode"] = "full"
    document["volumes"]["location:overflow"]["role"] = "archive"
    key = inventory.identity("location:overflow", "Old.mp4")
    document["inventory"][key] = {"id": key, "root": "location:overflow", "relative_path": "Old.mp4",
                                  "name": "Old", "size_bytes": 100 * GIB, "media_type": "movies",
                                  "owned": True, "modified_at": 1}
    assert plan_recommendations(disks, document, now=100_000_000) == []


def test_corrupt_state_is_fail_closed_and_not_overwritten(disks):
    path = inventory.state_path()
    path.write_text("broken", encoding="utf-8")
    assert inventory.read_state()["storage_error"]
    with pytest.raises(ValueError):
        autopilot.save_policy({"mode": "full"})
    assert path.read_text(encoding="utf-8") == "broken"


def test_delete_requires_explicit_preview_confirmation(disks):
    with pytest.raises(ValueError, match="Vorschau"):
        autopilot.save_policy({"auto_delete": True, "delete_categories": ["royal_partials"]})
    assert inventory.read_state()["policy"]["auto_delete"] is False
    autopilot.save_policy({"auto_delete": True, "delete_categories": ["royal_partials"]}, delete_confirmed=True)
    autopilot.save_policy({"mode": "monitor"})
    assert inventory.read_state()["policy"]["auto_delete"] is True
    assert json.loads(inventory.state_path().read_text())["policy"]["auto_delete"] is True


def test_affinity_survives_retry_and_only_splits_on_hard_limit(disks):
    from pathlib import Path
    autopilot.save_policy({"mode": "automatic"})
    disks[0]["key"] = "series"
    autopilot.save_volume("series", {"media_types": ["series"]})
    key = inventory.identity("series", "Show")
    inventory.transact(lambda document: document["inventory"].update({key: {
        "id": key, "root": "series", "series_name": "Show", "relative_path": "Show",
        "name": "Show", "size_bytes": 1024, "media_type": "series",
    }}))
    path = Path(disks[0]["path"]) / "Show" / "Season 2" / "Episode.mp4"
    disks[0].update(free_bytes=180 * GIB, used_percent=82)
    assert reserve_download("episode", path, "series", disks, [], [])["root"] == "series"
    disks[0].update(free_bytes=2 * GIB, used_percent=99.8)
    result = reserve_download("episode", path, "series", disks, [], [])
    assert result["root"] == "location:overflow"
    assert Path(result["path"]).relative_to(Path(disks[1]["path"])) == Path("Show/Season 2/Episode.mp4")
    assert len(inventory.read_state()["reservations"]) == 1


def test_offline_original_root_uses_registered_overflow_without_remount(disks):
    from pathlib import Path
    autopilot.save_policy({"mode": "automatic"})
    disks[0]["available"] = False
    result = reserve_download("one", Path(disks[0]["path"]) / "Movie.mp4", "movies", disks, [], [])
    assert result["root"] == "location:overflow"


def test_pending_final_paths_and_busy_jobs_are_accounted_on_actual_volume(disks):
    from pathlib import Path
    jobs = [{"job_id": "one", "media_type": "movie", "status": "queued", "total_bytes": 40 * GIB,
             "downloaded_bytes": 5 * GIB, "final_path": str(Path(disks[1]["path"]) / "Movie.mp4")}]
    assert reserved_by_volume(inventory.read_state(), disks, jobs, []) == {"overflow": 35 * GIB}
    assert autopilot.get_autopilot(queue_jobs=jobs)["roots"][1]["active_jobs"] == 1


def test_archive_is_full_only_and_protection_prevents_actions(disks):
    document = inventory.read_state()
    document["policy"]["mode"] = "automatic"
    key = inventory.identity("movies", "Old.mp4")
    document["inventory"][key] = {"id": key, "root": "movies", "relative_path": "Old.mp4", "name": "Old",
                                  "size_bytes": 100 * GIB, "media_type": "movies", "owned": True, "modified_at": 1}
    assert plan_recommendations(disks, document, now=100_000_000) == []
    document["policy"]["mode"] = "full"
    proposals = plan_recommendations(disks, document, now=100_000_000)
    assert len(proposals) == 1 and proposals[0]["destination_root"] == "location:archive"
    for flag in ("no_move", "no_archive", "keep_volume"):
        document["protections"][key] = {flag: True}
        assert plan_recommendations(disks, document, now=100_000_000) == []


@pytest.fixture
def balancing(disks, monkeypatch, tmp_path):
    from pathlib import Path
    import storage.storage_actions as actions
    import storage.storage_move as move
    import storage.storage_move_runtime as runtime
    monkeypatch.setattr(runtime, "JOB_PATH", tmp_path / "move-jobs.json")
    monkeypatch.setattr(runtime, "_enqueue", lambda _job: None)
    monkeypatch.setattr(runtime, "_ACTIVE", {})
    monkeypatch.setattr(runtime, "_HISTORY", [])
    monkeypatch.setattr(move, "_volume_signature", lambda path: (str(path), 1000 * GIB))
    monkeypatch.setattr(actions, "media_paths", lambda: {"movies": disks[0]["path"], "series": disks[0]["path"]})
    monkeypatch.setattr(actions, "load_storage_locations", lambda: [
        {"id": "overflow", "mode": "media", "path": disks[1]["path"], "label": "Overflow"},
        {"id": "archive", "mode": "media", "path": disks[2]["path"], "label": "Archive"}])
    monkeypatch.setattr(autopilot, "list_move_jobs", runtime.list_move_jobs)
    autopilot.save_policy({"mode": "automatic", "window_enabled": False})
    disks[0].update(used_percent=91, free_bytes=90 * GIB)
    source = Path(disks[0]["path"]) / "Movie.mp4"
    source.write_bytes(b"media" * 256)
    key = inventory.identity("movies", "Movie.mp4")
    inventory.transact(lambda document: document["inventory"].update({key: {
        "id": key, "root": "movies", "relative_path": source.name, "name": "Movie", "size_bytes": source.stat().st_size,
        "media_type": "movies", "owned": True, "owned_files": {source.name: source.stat().st_size},
        "owned_stamps": {source.name: [source.stat().st_mtime_ns, source.stat().st_ino]},
    }}))
    proposal = autopilot.refresh_recommendations()[0]
    return actions, runtime, source, key, proposal


def test_balancing_uses_existing_serial_runtime_and_recovers_without_duplicate(balancing):
    actions, runtime, source, key, proposal = balancing
    job = actions.apply_recommendation(proposal["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    assert source.exists() and job["autopilot_id"] == proposal["id"]
    assert job["minimum_reserve_bytes"] == 5 * GIB
    assert len(runtime.list_move_jobs()["jobs"]) == 1
    # Crash between persisted runtime submission and attaching recommendation.
    inventory.transact(lambda document: document["recommendations"][proposal["id"]].update(state="available", job_id=""))
    same = actions.apply_recommendation(proposal["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    assert same["job_id"] == job["job_id"]
    assert len(runtime.list_move_jobs()["jobs"]) == 1
    assert sum(entry["action"] == "move_planned" for entry in inventory.read_state()["activity"]) == 2


@pytest.mark.parametrize("case", ["queue", "playback", "unknown_playback", "protected", "foreign", "mutated", "collision", "offline", "revoked", "queue_race"])
def test_balancing_safety_rejects_without_creating_job(balancing, monkeypatch, case):
    actions, runtime, source, key, proposal = balancing
    queue = [{"job_id": "active"}] if case == "queue" else []
    playback = (lambda: None) if case == "unknown_playback" else (lambda: case != "playback")
    if case == "protected":
        inventory.protect_item(key, {"no_move": True})
    if case == "foreign":
        inventory.transact(lambda document: document["inventory"][key].update(owned=False, owned_files={}))
    if case == "mutated":
        source.write_bytes(b"changed")
    if case == "collision":
        from pathlib import Path
        target = next(root for root in autopilot.get_autopilot()["roots"] if root["key"] == proposal["destination_root"])
        (Path(target["path"]) / source.name).write_bytes(b"existing")
    if case == "offline":
        monkeypatch.setattr(actions, "get_autopilot", lambda **_kw: {"roots": []})
    if case == "revoked":
        original = actions.fresh_candidate
        def revoke(item):
            result = original(item)
            autopilot.save_policy({"mode": "monitor"})
            return result
        monkeypatch.setattr(actions, "fresh_candidate", revoke)
    with pytest.raises(ValueError):
        actions.apply_recommendation(proposal["id"], queue_jobs=queue, playback_check=playback, automatic=True,
                                     queue_check=lambda: [{"job_id": "new"}] if case == "queue_race" else [])
    assert source.exists() and runtime.list_move_jobs()["active_count"] == 0


def test_series_ownership_requires_all_actual_files(balancing, disks):
    actions, runtime, source, key, proposal = balancing
    folder = source.parent / "Show"
    folder.mkdir()
    owned = folder / "Owned.mp4"; owned.write_bytes(b"owned")
    foreign = folder / "Foreign.mp4"; foreign.write_bytes(b"foreign")
    disks.append({**disks[0], "key": "series"})
    new_key = inventory.identity("series", "Show")
    def update(document):
        document["inventory"].clear()
        document["inventory"][new_key] = {"id": new_key, "root": "series", "relative_path": "Show", "name": "Show",
                                         "size_bytes": 12, "media_type": "series", "owned": False, "owned_files": {"Show/Owned.mp4": 5}}
    inventory.transact(update)
    recommendation = autopilot.refresh_recommendations()[0]
    with pytest.raises(ValueError, match="nicht bestätigte"):
        actions.apply_recommendation(recommendation["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    inventory.transact(lambda document: document["inventory"][new_key]["owned_files"].update({"Show/Foreign.mp4": 7}))
    inventory.transact(lambda document: document["inventory"][new_key].update(owned_stamps={
        "Show/Owned.mp4": [owned.stat().st_mtime_ns, owned.stat().st_ino],
        "Show/Foreign.mp4": [foreign.stat().st_mtime_ns, foreign.stat().st_ino]}))
    job = actions.apply_recommendation(recommendation["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    assert job["source_name"] == "Show"


def test_completed_move_updates_inventory_protection_once(balancing):
    actions, runtime, source, key, proposal = balancing
    inventory.protect_item(key, {"no_delete": True})
    job = actions.apply_recommendation(proposal["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    job.update(status="completed", moved_bytes=source.stat().st_size)
    inventory.record_move_completion(job)
    inventory.record_move_completion(job)
    document = inventory.read_state()
    new_key = inventory.identity(job["destination_root"], source.name)
    assert key not in document["inventory"] and document["inventory"][new_key]["last_moved_at"] > 0
    assert document["protections"][new_key]["no_delete"]
    assert sum(entry["action"] == "move_finished" for entry in document["activity"]) == 1


def test_automatic_transfer_verifies_target_then_updates_inventory(balancing, monkeypatch):
    from pathlib import Path
    actions, runtime, source, key, proposal = balancing
    monkeypatch.setattr(runtime, "_same_volume", lambda *_args: False)
    expected = source.read_bytes()
    job = actions.apply_recommendation(proposal["id"], queue_jobs=[], playback_check=lambda: True, automatic=True)
    # Execute the actual existing worker against two fixture roots.
    runtime._run(job["job_id"])
    final = runtime.list_move_jobs()["history"][0]
    assert final["status"] == "completed"
    destination = Path(final["destination_path"])
    assert destination.read_bytes() == expected and not source.exists()
    item = next(iter(inventory.read_state()["inventory"].values()))
    assert item["root"] == final["destination_root"]
    assert item["owned_stamps"][destination.name] == [destination.stat().st_mtime_ns, destination.stat().st_ino]


def test_advisor_queue_advice_never_modifies_placement_or_reservations(disks):
    from pathlib import Path
    autopilot.save_policy({"mode": "advisor"})
    disks[0].update(free_bytes=180 * GIB, used_percent=82)
    jobs = [{"job_id": "pending", "title": "Movie", "media_type": "movie", "status": "queued",
             "final_path": str(Path(disks[0]["path"]) / "Movie.mp4")}]
    original = deepcopy(jobs)
    advice = autopilot.get_autopilot(queue_jobs=jobs)["placement_advice"]
    assert len(advice) == 1 and advice[0]["destination_root"] == "location:overflow"
    assert jobs == original and inventory.read_state()["reservations"] == {}


def test_time_window_has_midnight_semantics_and_next_deadline():
    from datetime import datetime
    from storage.storage_actions import in_window, next_window_start
    policy = inventory.read_state()["policy"]
    policy.update(window_enabled=True, window_start="22:00", window_end="06:00")
    assert in_window(policy, datetime(2026, 9, 28, 23, 0))
    assert in_window(policy, datetime(2026, 9, 28, 5, 59))
    assert not in_window(policy, datetime(2026, 9, 28, 6, 0))
    assert next_window_start(policy, datetime(2026, 9, 28, 12, 0)) == datetime(2026, 9, 28, 22, 0).timestamp()
