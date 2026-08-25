import asyncio
import json
from collections import OrderedDict
from pathlib import Path

import pytest
from fastapi import HTTPException

import api_queue_router
import queue_jobs
import server
from application_services import download_lifecycle
from downloader import DownloadQueue


@pytest.fixture(autouse=True)
def isolated_queue_state(monkeypatch):
    picked = set(server.state.picked)
    jobs = server.state.queue_jobs.copy()
    by_slug = dict(server.state.queue_job_by_slug)
    history = list(server.state.queue_history)
    counted = set(server.state.counted_queue_slugs)
    waiting = dict(server.state.provider_waiting_jobs)
    server.state.picked.clear()
    server.state.queue_jobs.clear()
    server.state.queue_job_by_slug.clear()
    server.state.queue_history.clear()
    server.state.counted_queue_slugs.clear()
    server.state.provider_waiting_jobs.clear()
    monkeypatch.setattr(server, "broadcast", lambda *_args, **_kwargs: None)
    yield
    server.state.picked.clear()
    server.state.picked.update(picked)
    server.state.queue_jobs = jobs
    server.state.queue_job_by_slug = by_slug
    server.state.queue_history = history
    server.state.counted_queue_slugs.clear()
    server.state.counted_queue_slugs.update(counted)
    server.state.provider_waiting_jobs.clear()
    server.state.provider_waiting_jobs.update(waiting)


def test_legacy_queue_migration_keeps_stable_id_after_restart(tmp_path):
    path = tmp_path / "download_queue.json"
    path.write_text(json.dumps(["provider:movie", "provider:show-s01e02"]), encoding="utf-8")

    first, migrated = queue_jobs.load_document(path)
    queue_jobs.atomic_save(path, first)
    second, migrated_again = queue_jobs.load_document(path)

    assert migrated is True
    assert migrated_again is False
    assert [job["job_id"] for job in second["jobs"]] == [
        job["job_id"] for job in first["jobs"]
    ]
    assert [job["slug"] for job in second["jobs"]] == [
        "provider:movie", "provider:show-s01e02",
    ]
    assert second["jobs"][1]["media_type"] == "series"


def test_atomic_queue_write_preserves_previous_document_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "download_queue.json"
    original = {"schema_version": 2, "jobs": [queue_jobs.new_job("movie:a")], "history": []}
    queue_jobs.atomic_save(path, original)
    previous = path.read_bytes()
    monkeypatch.setattr(queue_jobs.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(OSError):
        queue_jobs.atomic_save(path, {"schema_version": 2, "jobs": [], "history": []})

    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_restart_requeues_active_states_without_changing_identity():
    raw = queue_jobs.new_job("provider:movie", job_id="stable-job")
    raw.update({"status": "downloading", "attempts": 2, "progress": 41})

    document, _migrated = queue_jobs.normalize_document({
        "schema_version": 2, "jobs": [raw], "history": [],
    })

    assert document["jobs"][0]["job_id"] == "stable-job"
    assert document["jobs"][0]["status"] == "queued"
    assert document["jobs"][0]["attempts"] == 2
    assert document["jobs"][0]["progress"] == 41


def test_failed_job_retry_reuses_job_id_and_slug(monkeypatch):
    failed = queue_jobs.new_job("provider:movie", job_id="stable-job")
    failed.update({"status": "failed", "completed_at": 10, "error": "provider down"})
    failed_attempt_id = failed["attempt_id"]
    server.state.queue_history.append(failed)

    retried = server._retry_queue_job("stable-job")

    assert retried["job_id"] == "stable-job"
    assert retried["slug"] == "provider:movie"
    assert retried["status"] == "queued"
    assert retried["attempt_id"] != failed_attempt_id
    assert server.state.queue_job_by_slug["provider:movie"] == "stable-job"
    assert "provider:movie" in server.state.picked


def test_history_is_bounded_to_latest_500_jobs():
    history = []
    for index in range(520):
        job = queue_jobs.new_job(f"movie:{index}", job_id=f"job-{index}")
        job.update({"status": "completed", "completed_at": index})
        history.append(job)

    document, _migrated = queue_jobs.normalize_document({
        "schema_version": 2, "jobs": [], "history": history,
    })

    assert len(document["history"]) == 500
    assert document["history"][0]["job_id"] == "job-519"
    assert document["history"][-1]["job_id"] == "job-20"


def test_duplicate_active_content_is_collapsed_without_losing_first_id():
    first = queue_jobs.new_job("provider:movie", job_id="first")
    duplicate = queue_jobs.new_job("provider:movie", job_id="second")

    document, _migrated = queue_jobs.normalize_document({
        "schema_version": 2, "jobs": [first, duplicate], "history": [],
    })

    assert [(job["job_id"], job["slug"]) for job in document["jobs"]] == [
        ("first", "provider:movie"),
    ]


def test_download_queue_moves_only_pending_job():
    class Job:
        def __init__(self, name):
            self.name = name

    queue = DownloadQueue()
    queue.add(Job("one"))
    queue.add(Job("two"))
    queue.add(Job("three"))

    assert queue.move_pending(lambda job: job.name == "two", "up") is True
    assert [job.name for job in queue.pending_jobs()] == ["two", "one", "three"]
    assert queue.move_pending(lambda job: job.name == "two", "down") is True
    assert [job.name for job in queue.pending_jobs()] == ["one", "two", "three"]


def test_job_cancel_is_persisted_and_retained_in_history(monkeypatch):
    job = queue_jobs.new_job("provider:movie", job_id="cancel-me")
    server.state.queue_jobs = OrderedDict([(job["job_id"], job)])
    server.state.queue_job_by_slug[job["slug"]] = job["job_id"]
    server.state.picked.add(job["slug"])
    server.state.counted_queue_slugs.add(job["slug"])
    monkeypatch.setattr(server.appconfig, "save_queue", lambda _document: True)
    monkeypatch.setattr(server, "_telegram_terminal_without_job", lambda *_args: None)
    monkeypatch.setattr(server, "_seerr_terminal_without_job", lambda *_args: None)

    response = asyncio.run(api_queue_router.api_queue_job_cancel("cancel-me"))

    assert response["accepted"] is True
    assert response["job"]["status"] == "cancelled"
    assert server.state.queue_history[0]["job_id"] == "cancel-me"
    assert "provider:movie" not in server.state.picked


def test_active_cancel_blocks_retry_and_late_attempt_callbacks(monkeypatch):
    job = queue_jobs.new_job("provider:movie", job_id="race-job")
    old_attempt_id = job["attempt_id"]
    server.state.queue_jobs = OrderedDict([(job["job_id"], job)])
    server.state.queue_job_by_slug[job["slug"]] = job["job_id"]
    server.state.picked.add(job["slug"])
    server.state.counted_queue_slugs.add(job["slug"])

    class PhysicalJob:
        queue_slug = job["slug"]
        job_id = job["job_id"]
        attempt_id = old_attempt_id

        def cancel(self):
            self.cancelled = True

    physical = PhysicalJob()

    class ActiveQueue:
        def remove_pending(self, _predicate):
            return []

        def cancel_active(self, predicate):
            if predicate(physical):
                physical.cancel()
                return [physical]
            return []

        def active_jobs(self):
            return [physical]

        def active_count(self):
            return 1

        def pending_count(self):
            return 0

    monkeypatch.setattr(server.state, "dl_queue", ActiveQueue())
    monkeypatch.setattr(server.appconfig, "save_queue", lambda _document: True)

    response = asyncio.run(api_queue_router.api_queue_job_cancel("race-job"))

    assert response["job"]["status"] == "cancelling"
    assert not server.state.queue_history
    assert job["slug"] in server.state.picked
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_queue_router.api_queue_job_retry("race-job"))
    assert exc.value.detail["code"] == "queue_job_cancelling"

    assert server.on_job_done(
        False, "worker stopped", "Movie", Path(""),
        slug=job["slug"], job_id=job["job_id"], attempt_id=old_attempt_id,
    ) is True
    assert server.state.queue_history[0]["status"] == "cancelled"

    retried = server._retry_queue_job(job["job_id"])
    assert retried["attempt_id"] != old_attempt_id
    assert server.on_job_progress(
        90, "late progress", "Movie",
        slug=job["slug"], job_id=job["job_id"], attempt_id=old_attempt_id,
    ) is False
    assert server.on_job_done(
        True, "late completion", "Movie", Path("late.mp4"),
        slug=job["slug"], job_id=job["job_id"], attempt_id=old_attempt_id,
    ) is False
    assert server.state.queue_jobs[job["job_id"]]["status"] == "queued"


def test_restart_finalizes_cancelling_attempt_in_history():
    job = queue_jobs.new_job("provider:movie", job_id="cancel-on-restart")
    job["status"] = "cancelling"

    document, _migrated = queue_jobs.normalize_document({
        "schema_version": queue_jobs.SCHEMA_VERSION,
        "jobs": [job],
        "history": [],
    })

    assert document["jobs"] == []
    assert document["history"][0]["status"] == "cancelled"


def test_rest_aliases_and_pause_contract_are_additive():
    pairs = {
        (method, route.path)
        for route in server.app.routes
        for method in (getattr(route, "methods", None) or [])
    }
    for suffix, method in (
        ("/queue/jobs", "GET"),
        ("/queue/history", "GET"),
        ("/queue/jobs/{job_id}/cancel", "POST"),
        ("/queue/jobs/{job_id}/retry", "POST"),
        ("/queue/jobs/{job_id}/move", "POST"),
        ("/queue/jobs/{job_id}/resume", "POST"),
    ):
        assert (method, f"/api{suffix}") in pairs
        assert (method, f"/api/v1{suffix}") in pairs


def test_versioned_websocket_snapshot_contains_complete_job_ids():
    job = queue_jobs.new_job("provider:movie", job_id="snapshot-job")
    server.state.queue_jobs = OrderedDict([(job["job_id"], job)])
    server.state.queue_job_by_slug[job["slug"]] = job["job_id"]
    server.state.picked.add(job["slug"])

    snapshot = server.websocket_snapshot_payload()

    assert snapshot["type"] == "snapshot"
    assert snapshot["queue"]["jobs"][0]["job_id"] == "snapshot-job"


def test_progress_event_and_persistent_record_share_job_id(monkeypatch):
    job = queue_jobs.new_job("provider:movie", job_id="progress-job")
    server.state.queue_jobs = OrderedDict([(job["job_id"], job)])
    server.state.queue_job_by_slug[job["slug"]] = job["job_id"]
    server.state.picked.add(job["slug"])
    events = []
    monkeypatch.setattr(server, "broadcast", events.append)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    server.on_job_progress(
        25,
        "256 MiB",
        "Movie",
        slug=job["slug"],
        job_id=job["job_id"],
        downloaded_bytes=256 * 1024 * 1024,
        total_bytes=1024 * 1024 * 1024,
        speed_bps=4 * 1024 * 1024,
        eta_seconds=180,
    )

    assert events[-1]["job_id"] == "progress-job"
    assert events[-1]["job"]["job_id"] == "progress-job"
    assert server.state.queue_jobs["progress-job"]["status"] == "downloading"
    assert server.state.queue_jobs["progress-job"]["downloaded_bytes"] == 256 * 1024 * 1024


def test_migration_preserves_slug_based_telegram_and_seerr_correlations():
    slug = "provider:show-s01e02"
    document, _migrated = queue_jobs.normalize_document([slug])
    telegram = {slug: {"request_id": 7}}
    seerr = {slug: [{"request_id": 9}]}

    assert document["jobs"][0]["slug"] in telegram
    assert document["jobs"][0]["slug"] in seerr


def test_completed_subscription_episode_creates_bounded_unread_receipt(monkeypatch):
    entry = {"downloaded_episode_notifications": [
        {
            "slug": f"show-s01e{episode:02d}",
            "season": 1,
            "episode": episode,
            "downloaded_at": float(episode),
            "read": True,
        }
        for episode in range(1, 21)
    ]}
    monkeypatch.setattr(download_lifecycle.time, "time", lambda: 1234.0)

    assert download_lifecycle._record_watchlist_download_notification(
        entry, "show-s02e03",
    ) is True

    notifications = entry["downloaded_episode_notifications"]
    assert len(notifications) == 20
    assert notifications[0] == {
        "slug": "show-s02e03",
        "season": 2,
        "episode": 3,
        "downloaded_at": 1234.0,
        "read": False,
    }
    assert download_lifecycle._record_watchlist_download_notification(
        entry, "movie-without-episode",
    ) is False
