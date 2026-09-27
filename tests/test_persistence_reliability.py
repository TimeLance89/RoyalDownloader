import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server
from api import api_library_router
from providers.models import FilmpalastMovie, HosterInfo


@pytest.fixture(autouse=True)
def isolated_persistence_state(monkeypatch):
    class _DeferredThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(server.threading, "Thread", _DeferredThread)
    previous_watchlist = server.state.watchlist
    previous_movies = server.state.movie_subscriptions
    previous_picked = set(server.state.picked)
    previous_queue_jobs = server.state.queue_jobs.copy()
    previous_queue_job_by_slug = dict(server.state.queue_job_by_slug)
    previous_queue_history = list(server.state.queue_history)
    previous_fp_movies = dict(server.state.fp_movies)
    previous_watchlist_new_slugs = {
        key: set(value) for key, value in server.state.watchlist_new_slugs.items()
    }
    with server.state.persistence_status_lock:
        server.state.persistence_pending.clear()
        server.state.persistence_errors.clear()
        server.state.persistence_generations.clear()
        server.state.persistence_retrying.clear()
    monkeypatch.setattr(server, "broadcast", lambda *_args, **_kwargs: None)
    yield
    server.state.watchlist = previous_watchlist
    server.state.movie_subscriptions = previous_movies
    server.state.picked.clear()
    server.state.picked.update(previous_picked)
    server.state.queue_jobs = previous_queue_jobs
    server.state.queue_job_by_slug = previous_queue_job_by_slug
    server.state.queue_history = previous_queue_history
    server.state.fp_movies.clear()
    server.state.fp_movies.update(previous_fp_movies)
    server.state.watchlist_new_slugs.clear()
    server.state.watchlist_new_slugs.update(previous_watchlist_new_slugs)
    with server.state.persistence_status_lock:
        server.state.persistence_pending.clear()
        server.state.persistence_errors.clear()
        server.state.persistence_generations.clear()


def _assert_persistence_error(exc: HTTPException, resource: str):
    assert exc.status_code == 503
    assert exc.detail["code"] == "state_persistence_failed"
    assert exc.detail["resource"] == resource


def test_movie_subscription_remove_rolls_back_on_save_failure(monkeypatch):
    original = {"key": "tmdb:1", "title": "Film", "pending_slug": ""}
    server.state.movie_subscriptions = [original]
    monkeypatch.setattr(server.appconfig, "save_movie_subscriptions", lambda _items: False)
    events = []
    monkeypatch.setattr(server, "broadcast", events.append)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_movie_subscriptions_remove(
            server.MovieSubscriptionKeysBody(keys=["tmdb:1"]),
        ))

    _assert_persistence_error(raised.value, "movie_subscriptions")
    assert server.state.movie_subscriptions == [original]
    assert events == []


def test_movie_subscription_save_and_remove_broadcast_committed_snapshots(monkeypatch):
    server.state.movie_subscriptions = []
    monkeypatch.setattr(server.appconfig, "save_movie_subscriptions", lambda _items: True)
    monkeypatch.setattr(api_library_router, "_personal_taste_store", lambda _request: (None, ""))
    events = []
    monkeypatch.setattr(server, "broadcast", events.append)

    saved = asyncio.run(server.api_movie_subscription_save(server.MovieSubscriptionBody(
        source_slug="movie", title="Film", tmdb_id=1,
    )))
    assert len(saved["movie_subscriptions"]) == 1
    assert events == [{"type": "movie_subscriptions_update", **saved}]
    key = saved["movie_subscriptions"][0]["key"]
    removed = asyncio.run(server.api_movie_subscriptions_remove(
        server.MovieSubscriptionKeysBody(keys=[key]),
    ))
    assert removed["movie_subscriptions"] == []
    assert removed["persistence"]["ok"] is True
    assert events[-1] == {"type": "movie_subscriptions_update", **removed}


def test_movie_subscription_add_rolls_back_on_save_failure(monkeypatch):
    server.state.movie_subscriptions = []
    monkeypatch.setattr(server.appconfig, "save_movie_subscriptions", lambda _items: False)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_movie_subscription_save(server.MovieSubscriptionBody(
            source_slug="movie", title="Film", tmdb_id=1,
        )))

    _assert_persistence_error(raised.value, "movie_subscriptions")
    assert server.state.movie_subscriptions == []


def test_watchlist_add_and_mode_roll_back_on_save_failure(monkeypatch):
    server.state.watchlist = []
    monkeypatch.setattr(server.appconfig, "save_watchlist", lambda _items: False)
    add = server.WatchlistAddBody(
        base_slug="show", title="Show", sample_url="https://example.invalid/show",
        known_slugs=[],
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_watchlist_add(add))
    _assert_persistence_error(raised.value, "watchlist")
    assert server.state.watchlist == []

    original = {
        "base_slug": "show", "title": "Show", "sample_url": "https://example.invalid/show",
        "known_slugs": [], "download_mode": server.WATCH_MODE_DEFAULT,
        "cleanup_mode": server.CLEANUP_MODE_KEEP, "mode_generation": 0,
        "check_generation": 0, "last_error": "",
    }
    expected = deepcopy(original)
    server.state.watchlist = [original]
    alternative = next(
        mode for mode in server.WATCH_MODE_LABELS if mode != server.WATCH_MODE_DEFAULT
    )
    with pytest.raises(HTTPException):
        asyncio.run(server.api_watchlist_mode(server.WatchlistModeBody(
            base_slug="show", download_mode=alternative,
        )))
    assert server.state.watchlist == [expected]


def test_watchlist_remove_keeps_auxiliary_state_on_save_failure(monkeypatch):
    entry = {
        "base_slug": "show", "title": "Show", "sample_url": "https://example.invalid/show",
        "known_slugs": [],
    }
    server.state.watchlist = [entry]
    server.state.watchlist_new_slugs["show"] = {"show-s01e01"}
    monkeypatch.setattr(server.appconfig, "save_watchlist", lambda _items: False)
    events = []
    monkeypatch.setattr(server, "broadcast", events.append)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_watchlist_remove(
            server.WatchlistRemoveBody(base_slugs=["show"]),
        ))

    _assert_persistence_error(raised.value, "watchlist")
    assert server.state.watchlist == [entry]
    assert server.state.watchlist_new_slugs["show"] == {"show-s01e01"}
    assert events == []


def test_watchlist_removal_broadcasts_the_committed_snapshot(monkeypatch):
    server.state.watchlist = [{"base_slug": "removed"}, {"base_slug": "retained"}]
    monkeypatch.setattr(server.state, "series_cache", {})
    monkeypatch.setattr(server.state, "watchlist_new_slugs", {})
    monkeypatch.setattr(server.state, "dl_queue", SimpleNamespace(
        remove_pending=lambda _predicate: [], cancel_active=lambda _predicate: None,
    ))
    monkeypatch.setattr(server.appconfig, "save_watchlist", lambda _items: True)
    monkeypatch.setattr(server, "build_queue_payload", lambda: {"groups": []})
    monkeypatch.setattr(server, "watchlist_payload", lambda: {"watchlist": deepcopy(server.state.watchlist)})
    monkeypatch.setattr(server, "_release_removed_queue_slugs", lambda _slugs: None)
    events = []
    monkeypatch.setattr(server, "broadcast", events.append)

    payload = asyncio.run(server.api_watchlist_remove(
        server.WatchlistRemoveBody(base_slugs=["removed"]),
    ))

    assert payload == {"watchlist": [{"base_slug": "retained"}]}
    assert events == [
        {"type": "queue_update", "queue": {"groups": []}},
        {"type": "watchlist_update", **payload},
    ]


def test_queue_add_releases_claim_when_initial_persistence_fails(monkeypatch):
    slug = "filmpalast:test"
    server.state.picked.clear()
    server.state.fp_movies[slug] = FilmpalastMovie(
        title="Test", url="https://example.invalid/test",
        hosters=[HosterInfo("Direct", "https://cdn.example.invalid/test.mp4")],
    )
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server.appconfig, "save_queue", lambda _items: False)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=[slug])))

    _assert_persistence_error(raised.value, "queue")
    assert slug not in server.state.picked


def test_background_queue_claim_is_not_started_as_durable_on_failure(monkeypatch):
    slug = "series:show-s01e01"
    server.state.picked.clear()
    server.state.picked.add(slug)
    monkeypatch.setattr(server.appconfig, "save_queue", lambda _items: False)

    assert server._persist_new_queue_claims({slug}) is False

    assert slug not in server.state.picked
    with server.state.persistence_status_lock:
        snapshot = server.state.persistence_pending["queue"]["snapshot"]
        assert snapshot["jobs"] == []
        assert snapshot["history"] == []


def test_background_failure_is_visible_and_retryable(monkeypatch):
    outcomes = iter((False, True))
    written = []

    def _save(items):
        written.append(list(items))
        return next(outcomes)

    monkeypatch.setattr(server.appconfig, "save_watchlist", _save)
    snapshot = [{"base_slug": "show"}]

    assert server._persist_background_snapshot("watchlist", snapshot) is False
    failed = server._persistence_status("watchlist")
    assert failed["ok"] is False
    assert failed["pending_retry"] is True
    assert server.watchlist_payload()["persistence"]["pending_retry"] is True

    assert server._retry_persistence_once("watchlist") is True
    assert server._persistence_status("watchlist")["ok"] is True
    assert written == [snapshot, snapshot]
