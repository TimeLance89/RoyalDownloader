"""Delete-first replacement uses only fake Jellyfin/media and temporary journals."""

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api import api_queue_router as routes
from application_services.movie_redownload import (
    ReplacementJournal,
    prepare_replacement,
    replacement_request,
)
from integrations.jellyfin_client import JellyfinClient
from providers.models import FilmpalastMovie, HosterInfo


@pytest.fixture
def setup(tmp_path, monkeypatch):
    events = []
    items = [
        {"id": "old-hd", "tmdb_id": "123", "name": "Film", "year": 2025},
        {"id": "old-4k", "tmdb_id": "123", "name": "Film", "year": 2025},
        {"id": "remake", "tmdb_id": "456", "name": "Film", "year": 2026},
    ]

    def delete(item_id):
        events.append(("delete", item_id))
        items[:] = [item for item in items if item["id"] != item_id]
        return True

    client = SimpleNamespace(configured=True, list_movies=lambda: list(items),
                             delete_item=delete, match=JellyfinClient("", "").match)
    movie = FilmpalastMovie("Film", "https://example.invalid/film", year="2025",
                           hosters=[HosterInfo("voe", "https://example.invalid/stream")])
    state = SimpleNamespace(
        auto_download_lock=threading.RLock(), queue_lifecycle_lock=threading.RLock(),
        queue_claim_lock=threading.RLock(), queue_jobs={}, picked=set(), queue_history=[],
        dl_queue=SimpleNamespace(active_jobs=list),
    )
    backend = SimpleNamespace(
        state=state, load_movie_for_slug=lambda slug: movie,
        _preferred_movie_sources=lambda *args: (movie, None), clean_movie_title=lambda title: title,
        get_tmdb_client=lambda: SimpleNamespace(movie_summary=lambda *args: {
            "tmdb_id": 123, "title": "Film", "year": "2025",
        }), get_jellyfin_client=lambda: client,
        queue_content_key=lambda slug: "movie:tmdb:123",
        get_jellyfin_library=lambda **kwargs: list(items),
        get_jellyfin_movie_identities=lambda **kwargs: list(items),
        request_jellyfin_live_refresh=lambda: events.append(("refresh",)),
    )
    body = routes.MovieRedownloadBody(slug="film", tmdb_id=123, request_id=uuid4())
    journal = ReplacementJournal(tmp_path / "movie_replacements.sqlite3")
    monkeypatch.setenv("SERIENDL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(routes, "_redownload_backend", backend)
    monkeypatch.setattr(routes, "state", state)
    monkeypatch.setattr(routes, "_taste_context", lambda request: ({"id": "admin", "role": "admin"}, None))

    async def enqueue(queue_body, request):
        events.append(("enqueue", queue_body))
        assert not any(item["tmdb_id"] == "123" for item in items)
        state.queue_history.append({"job_id": "replacement-job", "replacement_request_id": replacement_request.get()})
        return {"added": 1, "auto_started": 1}

    real_add = routes.api_queue_add
    monkeypatch.setattr(routes, "api_queue_add", enqueue)
    return SimpleNamespace(events=events, items=items, backend=backend, body=body,
                           journal=journal, client=client, movie=movie, state=state,
                           real_add=real_add)


def call(s):
    return asyncio.run(routes.api_movie_redownload(s.body, object()))


def test_delete_all_versions_before_enqueue_and_replay_after_restart(setup):
    s = setup
    result = call(s)
    assert result["deleted"] is True
    assert [event[0] for event in s.events] == ["delete", "delete", "refresh", "enqueue"]
    assert [item["id"] for item in s.items] == ["remake"]
    # A new file/version must survive retries, even with a fresh journal object.
    s.items.append({"id": "new-4k", "tmdb_id": "123"})
    s.journal = ReplacementJournal(s.journal.path)
    assert call(s) == result
    assert len(s.events) == 4


@pytest.mark.parametrize("failure", ["source", "identity", "year", "title", "offline", "missing", "episode", "active"])
def test_preflight_errors_never_delete_or_queue(setup, failure):
    s = setup
    if failure == "source":
        s.movie.hosters.clear()
    elif failure == "identity":
        s.body.tmdb_id = 456
    elif failure == "year":
        s.movie.year = "2026"
    elif failure == "title":
        s.movie.title = "Anderer Film"
    elif failure == "offline":
        s.client.list_movies = lambda: None
    elif failure == "missing":
        s.items[:] = [s.items[-1]]
    elif failure == "episode":
        s.body.slug = "serienstream:film-s01e01"
    else:
        s.state.picked.add("other-provider")
        s.state.queue_jobs["job"] = {"slug": "other-provider"}
    with pytest.raises(HTTPException):
        call(s)
    assert not s.events


def test_partial_delete_failure_blocks_enqueue_and_destructive_retry(setup):
    s = setup
    delete = s.client.delete_item
    s.client.delete_item = lambda item_id: delete(item_id) if item_id == "old-4k" else False
    with pytest.raises(HTTPException, match="502"):
        call(s)
    assert len(s.events) == 1
    with pytest.raises(HTTPException, match="409"):
        call(s)
    s.body.request_id = uuid4()
    with pytest.raises(HTTPException, match="409"):
        call(s)
    assert len(s.events) == 1


def test_queue_failure_retry_never_repeats_deletion(setup, monkeypatch):
    s = setup
    original = routes.api_queue_add

    async def failed(*args):
        return {"added": 0, "skipped_details": {"film": "Systemupdate läuft"}}

    monkeypatch.setattr(routes, "api_queue_add", failed)
    with pytest.raises(HTTPException, match="409"):
        call(s)
    assert s.journal.get(str(s.body.request_id))["phase"] == "deleted"
    monkeypatch.setattr(routes, "api_queue_add", original)
    assert call(s)["added"] == 1
    assert len([event for event in s.events if event[0] == "delete"]) == 2


def test_interrupted_admission_recovers_from_persisted_job(setup):
    s = setup
    record = prepare_replacement(s.backend, s.journal, s.body, "admin")
    record["phase"] = "queueing"
    s.journal.save(str(s.body.request_id), record)
    s.state.queue_history.append({"job_id": "persisted", "replacement_request_id": str(s.body.request_id)})
    assert call(s)["job_id"] == "persisted"
    assert len(s.events) == 2


def test_uncertain_admission_does_not_guess_or_delete(setup):
    s = setup
    record = prepare_replacement(s.backend, s.journal, s.body, "admin")
    record["phase"] = "queueing"
    s.journal.save(str(s.body.request_id), record)
    with pytest.raises(HTTPException, match="409"):
        call(s)
    assert len(s.events) == 2


def test_refresh_failure_retries_only_refresh_and_enqueue(setup):
    s = setup
    original = s.backend.get_jellyfin_library
    s.backend.get_jellyfin_library = lambda **kwargs: None
    with pytest.raises(HTTPException, match="503"):
        call(s)
    s.backend.get_jellyfin_library = original
    assert call(s)["added"] == 1
    assert len([event for event in s.events if event[0] == "delete"]) == 2


def test_request_id_bound_to_owner_and_selection(setup):
    s = setup
    call(s)
    s.body.preference.quality = "2160p"
    with pytest.raises(HTTPException, match="409"):
        call(s)
    assert len(s.events) == 4


def test_journal_failure_before_delete_keeps_files(setup, monkeypatch):
    s = setup
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(ReplacementJournal, "begin", fail)
    with pytest.raises(OSError):
        call(s)
    assert not s.events


def test_non_admin_cannot_delete(setup, monkeypatch):
    monkeypatch.setattr(routes, "_taste_context", lambda request: ({"id": "viewer", "role": "user"}, None))
    with pytest.raises(HTTPException, match="403"):
        call(setup)
    assert not setup.events


def test_cancelling_physical_job_still_blocks_deletion(setup):
    s = setup
    s.state.dl_queue.active_jobs = lambda: [SimpleNamespace(queue_slugs={"other-provider"})]
    with pytest.raises(HTTPException, match="409"):
        call(s)
    assert not s.events


def test_real_queue_admission_persists_operation_tag_before_enqueue(setup, monkeypatch):
    s = setup
    state = s.state
    state.download_state_lock = threading.RLock()
    state.counted_queue_slugs = set()
    state.fp_movies = {"film": s.movie}
    state.queue_job_by_slug = {}
    state.personal_requests = SimpleNamespace(record=lambda *args, **kwargs: True)
    state.done_jobs = state.total_jobs = 0
    snapshots = []

    def ensure(slug, movie):
        job = {"job_id": "queued-id", "slug": slug}
        state.queue_jobs["queued-id"] = job
        state.queue_job_by_slug[slug] = "queued-id"
        return job

    monkeypatch.setattr(routes, "_ensure_queue_job", ensure)
    monkeypatch.setattr(routes, "_scheduled_episode_reason", lambda slug: "")
    monkeypatch.setattr(routes, "wait_for_jellyfin_live_ready", lambda: True)
    monkeypatch.setattr(routes, "_content_already_available", lambda *args: (False, ""))
    monkeypatch.setattr(routes, "_preferred_movie_sources", lambda *args: (s.movie, None))
    monkeypatch.setattr(routes, "_queue_job_for_slug", lambda slug: state.queue_jobs.get("queued-id"))
    monkeypatch.setattr(routes, "_queue_state_snapshot", lambda: deepcopy(list(state.queue_jobs.values())))
    monkeypatch.setattr(routes, "_require_persistent_snapshot", lambda resource, snapshot: snapshots.append(snapshot))
    monkeypatch.setattr(routes, "build_queue_payload", list)

    def enqueue(slugs, **kwargs):
        assert snapshots[0][0]["replacement_request_id"] == str(s.body.request_id)
        return set(slugs)

    monkeypatch.setattr(routes, "_enqueue_automatic_downloads", enqueue)
    token = replacement_request.set(str(s.body.request_id))
    try:
        result = asyncio.run(s.real_add(routes.QueueAddBody(slugs=["film"]), object()))
    finally:
        replacement_request.reset(token)
    assert result["added"] == 1


def test_queue_operation_tag_survives_normalization():
    from core.queue_jobs import new_job, normalize_job
    job = new_job("film")
    job["replacement_request_id"] = str(uuid4())
    assert normalize_job(job, active=True)["replacement_request_id"] == job["replacement_request_id"]
