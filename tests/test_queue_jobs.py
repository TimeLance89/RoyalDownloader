import asyncio
import json
from collections import OrderedDict
from pathlib import Path

import pytest
from fastapi import HTTPException

import api.api_queue_router as api_queue_router
import core.queue_jobs as queue_jobs
from core.personal_requests import PersonalRequestStore
import server
from application_services import download_lifecycle
from media.downloader import DownloadQueue


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
    failed.update({
        "status": "failed",
        "completed_at": 10,
        "error": "provider down",
        "source_retry_count": 10,
        "wait_reason": "source_unavailable",
        "next_retry_at": 999,
    })
    failed_attempt_id = failed["attempt_id"]
    server.state.queue_history.append(failed)

    retried = server._retry_queue_job("stable-job")

    assert retried["job_id"] == "stable-job"
    assert retried["slug"] == "provider:movie"
    assert retried["status"] == "queued"
    assert retried["attempt_id"] != failed_attempt_id
    assert retried["source_retry_count"] == 0
    assert retried["wait_reason"] == ""
    assert retried["next_retry_at"] == 0
    assert server.state.queue_job_by_slug["provider:movie"] == "stable-job"
    assert "provider:movie" in server.state.picked


def test_existing_retryable_episode_failures_are_recovered_after_update(monkeypatch):
    retryable = queue_jobs.new_job(
        "serienstream:sailor-moon-s04e19", job_id="old-source-failure",
    )
    retryable.update({
        "status": "failed",
        "completed_at": 20,
        "error": "kein Hoster extrahierbar",
    })
    permanent = queue_jobs.new_job(
        "serienstream:sailor-moon-s04e20", job_id="permanent-failure",
    )
    permanent.update({
        "status": "failed",
        "completed_at": 19,
        "error": "Speicherziel nicht verfügbar: volume offline",
    })
    movie = queue_jobs.new_job("filmpalast:movie", job_id="movie-source-failure")
    movie.update({
        "status": "failed",
        "completed_at": 18,
        "error": "kein Hoster extrahierbar",
    })
    server.state.queue_history.extend([retryable, permanent, movie])
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    recovered = server._recover_retryable_source_history()

    assert recovered == 1
    active = server.state.queue_jobs["old-source-failure"]
    assert active["slug"] == "serienstream:sailor-moon-s04e19"
    assert active["status"] == "queued"
    assert active["source_retry_count"] == 0
    assert active["wait_reason"] == ""
    assert active["next_retry_at"] == 0
    assert active["slug"] in server.state.picked
    assert {job["job_id"] for job in server.state.queue_history} == {
        "permanent-failure", "movie-source-failure",
    }


def test_exhausted_new_source_retry_is_not_revived_on_restart(monkeypatch):
    slug = "serienstream:sailor-moon-s04e21"
    exhausted = queue_jobs.new_job(slug, job_id="exhausted-source")
    exhausted.update({
        "status": "failed",
        "completed_at": 30,
        "error": "kein Hoster extrahierbar – automatisches Retry-Budget ausgeschöpft",
        "source_retry_count": 10,
        "wait_reason": "source_unavailable",
    })
    server.state.queue_history.append(exhausted)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    assert server._recover_retryable_source_history() == 0
    assert "exhausted-source" not in server.state.queue_jobs
    assert server.state.queue_history[0]["job_id"] == "exhausted-source"


def test_existing_retryable_failure_is_not_duplicated_when_slug_is_active(monkeypatch):
    slug = "serienstream:sailor-moon-s04e19"
    active = queue_jobs.new_job(slug, job_id="active-job")
    server.state.queue_jobs[active["job_id"]] = active
    server.state.queue_job_by_slug[slug] = active["job_id"]
    server.state.picked.add(slug)

    old = queue_jobs.new_job(slug, job_id="old-failure")
    old.update({
        "status": "failed",
        "completed_at": 10,
        "error": "alle Anbieter und Filmquellen ausgeschöpft",
    })
    server.state.queue_history.append(old)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    assert server._recover_retryable_source_history() == 0
    assert list(server.state.queue_jobs) == ["active-job"]
    assert server.state.queue_history[0]["job_id"] == "old-failure"


@pytest.mark.parametrize("checked_at,expected_retry", [(0, 1000.0), (900.0, 2000.0)])
def test_restart_reconstructs_waiting_source_job_and_retry_worker(monkeypatch, checked_at, expected_retry):
    slug = "serienstream:sailor-moon-s04e19"
    monkeypatch.setattr(api_queue_router.time, "time", lambda: 1000.0)
    waiting = queue_jobs.new_job(slug, job_id="waiting-source")
    waiting["language_checked_at"] = checked_at
    waiting.update({
        "status": "waiting_provider",
        "source_retry_count": 2,
        "wait_reason": "source_unavailable",
        "next_retry_at": 2_000.0,
    })
    server.state.queue_jobs[waiting["job_id"]] = waiting
    server.state.queue_job_by_slug[slug] = waiting["job_id"]
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.clear()
    monkeypatch.setattr(server.state, "total_jobs", 0)

    class Placeholder:
        title = "Sailor Moon S04E19"
        hosters = []

    placeholder = Placeholder()
    monkeypatch.setitem(server.state.fp_movies, slug, placeholder)
    monkeypatch.setattr(server, "_episode_placeholder", lambda _slug: placeholder)
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)
    worker_starts = []
    monkeypatch.setattr(
        server,
        "_ensure_provider_retry_worker",
        lambda: worker_starts.append(True),
    )

    server.restore_persisted_queue()

    restored = server.state.provider_waiting_jobs[slug]
    assert restored["wait_reason"] == "source_unavailable"
    assert restored["next_retry_at"] == expected_retry
    assert slug in server.state.counted_queue_slugs
    assert server.state.total_jobs == 1
    assert worker_starts == [True]


def test_evicted_legacy_personal_episode_failure_is_recovered_once(monkeypatch, tmp_path):
    request_file = tmp_path / "personal_requests.json"
    request_file.write_text(
        json.dumps({
            "schema_version": 1,
            "requests": [{
                "id": "legacy-request",
                "user_id": "user-a",
                "job_id": "evicted-source-failure",
                "media_key": "serienstream:sailor-moon-s04e19",
                "media_type": "series",
                "title": "Sailor Moon S04E19",
                "request_source": "web",
                "status": "failed",
                "requested_at": 10,
                "failed_at": 20,
                "updated_at": 20,
            }],
        }),
        encoding="utf-8",
    )
    store = PersonalRequestStore(request_file, clock=lambda: 100.0)
    monkeypatch.setattr(server.state, "personal_requests", store)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    assert server._recover_evicted_personal_episode_failures() == 1

    job = server.state.queue_jobs["evicted-source-failure"]
    assert job["slug"] == "serienstream:sailor-moon-s04e19"
    assert job["status"] == "queued"
    assert job["requested_by_user_id"] == "user-a"
    assert job["request_source"] == "web"
    assert job["slug"] in server.state.picked
    request = store.recent_for_user("user-a")[0]
    assert request["status"] == "queued"
    assert "source_retry_generation" not in request
    persisted_request = json.loads(request_file.read_text(encoding="utf-8"))["requests"][0]
    assert persisted_request["source_retry_generation"] == 1

    assert server._recover_evicted_personal_episode_failures() == 0


def test_personal_recovery_does_not_override_exact_history_classification(monkeypatch, tmp_path):
    slug = "serienstream:sailor-moon-s04e20"
    request_file = tmp_path / "personal_requests.json"
    request_file.write_text(
        json.dumps({
            "schema_version": 1,
            "requests": [{
                "id": "legacy-request",
                "user_id": "user-a",
                "job_id": "still-in-history",
                "media_key": slug,
                "media_type": "series",
                "title": "Sailor Moon S04E20",
                "request_source": "web",
                "status": "failed",
                "requested_at": 10,
                "failed_at": 20,
                "updated_at": 20,
            }],
        }),
        encoding="utf-8",
    )
    store = PersonalRequestStore(request_file, clock=lambda: 100.0)
    monkeypatch.setattr(server.state, "personal_requests", store)
    terminal = queue_jobs.new_job(slug, job_id="still-in-history")
    terminal.update({
        "status": "failed",
        "completed_at": 20,
        "error": "Speicherziel nicht verfügbar: volume offline",
    })
    server.state.queue_history.append(terminal)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)

    assert server._recover_retryable_source_history() == 0
    assert server._recover_evicted_personal_episode_failures() == 0
    assert "still-in-history" not in server.state.queue_jobs
    assert server.state.queue_history[0]["error"].startswith("Speicherziel")

    # Once the exact terminal row is later evicted by HISTORY_LIMIT, the durable
    # request must stay classified and must not be revived as an unknown legacy
    # source failure.
    server.state.queue_history.clear()
    assert server._recover_evicted_personal_episode_failures() == 0


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


@pytest.mark.parametrize("pending,failed,base_slug,known_slugs", [
    (True, False, "serienstream:show", []),
    (False, False, "serienstream:show", []),
    (False, True, "serienstream:show", []),
    (False, False, "old-provider:show", ["serienstream:show-s01e02"]),
])
def test_successful_subscription_download_notifies_after_pending_was_cleared(
    monkeypatch, pending, failed, base_slug, known_slugs,
):
    slug = "serienstream:show-s01e02"
    entry = {
        "base_slug": base_slug, "title": "Show", "known_slugs": known_slugs,
        "failed_downloads": {slug: {"attempts": 1}} if failed else {},
    }
    unrelated = {"base_slug": "serienstream:other", "title": "Other"}
    monkeypatch.setattr(server.state, "watchlist", [entry, unrelated])
    monkeypatch.setattr(server.state, "watchlist_new_slugs", {base_slug: {slug}} if pending else {})
    monkeypatch.setattr(server.state, "done_slugs", set())
    monkeypatch.setattr(server.state, "done_jobs", 0)
    monkeypatch.setattr(server.state, "total_jobs", 1)
    monkeypatch.setattr(server.state, "telegram_jobs", {})
    monkeypatch.setattr(server.state, "seerr_jobs", {})
    job = queue_jobs.new_job(slug)
    server.state.queue_jobs[job["job_id"]] = job
    server.state.queue_job_by_slug[slug] = job["job_id"]
    server.state.counted_queue_slugs.add(slug)
    server.state.picked.add(slug)
    events = []
    saved = []
    monkeypatch.setattr(server, "broadcast", events.append)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: True)
    monkeypatch.setattr(server, "_persist_watchlist_background", lambda: saved.append(True))
    monkeypatch.setattr(server, "refresh_jellyfin_after_download", lambda: None)

    assert server.on_job_done(True, "ok", "Show S01E02", Path("show.mp4"), slug=slug)
    notification = entry["downloaded_episode_notifications"][0]
    assert notification["slug"] == slug
    assert notification["read"] is False
    assert entry["failed_downloads"] == {}
    assert "downloaded_episode_notifications" not in unrelated
    assert saved == [True]
    snapshot = next(event for event in events if event["type"] == "watchlist_update")
    assert snapshot["watchlist"][0]["downloaded_count"] == 1
    assert snapshot["watchlist"][0]["last_unread_downloaded_episode"]["episode"] == 2
    assert not server.on_job_done(True, "duplicate", "Show", Path("show.mp4"), slug=slug)
    assert len(entry["downloaded_episode_notifications"]) == 1
