"""Provider catalog changes must not cancel or duplicate active episode jobs."""

import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401
from api import api_library_router as library, api_queue_router as queue


OLD = "serienstream:i-am-a-killer-s01e06"
ALTERNATE = "vidrift:81337-s1e6"
BASE = "serienstream:i-am-a-killer"


@pytest.fixture
def subscription(monkeypatch):
    entry = {"base_slug": BASE, "known_slugs": [OLD], "episode_states": {OLD: "available"}}
    state = SimpleNamespace(
        picked={OLD}, watchlist=[entry], watchlist_new_slugs={BASE: {OLD}},
        content_languages={"de"}, subscription_content_languages={},
        auto_download_lock=threading.RLock(), queue_lifecycle_lock=threading.RLock(),
        queue_claim_lock=threading.RLock(), watchlist_lock=threading.RLock(),
    )
    monkeypatch.setattr(library, "state", state)
    monkeypatch.setattr(queue, "state", state)
    cancellations = []
    monkeypatch.setattr(queue, "_cancel_queue_slugs", lambda slugs, reason: cancellations.extend(slugs))
    return entry, state, cancellations


@pytest.mark.parametrize("source", [OLD, ALTERNATE])
@pytest.mark.parametrize("status", ["available", "language_pending", "waiting_for_language"])
def test_recheck_preserves_one_active_queue_identity(subscription, source, status):
    entry, state, cancelled = subscription
    calculated = {
        "mode": "all", "cleanup_mode": "keep", "known_slugs": [source],
        "episode_states": {source: status},
        "missing_slugs": {source} if status == "available" else set(),
        "episode_language_checks": {source: {"languages": ["de"], "checked_at": 1}},
        "waiting_language_slugs": {source} if status == "waiting_for_language" else set(),
    }
    withdrawn = library._apply_watchlist_entry_state(entry, calculated)
    assert not withdrawn
    assert state.watchlist_new_slugs[BASE] == {OLD}
    assert entry["known_slugs"] == [OLD]
    assert entry["episode_states"] == {OLD: "available"}
    assert not entry["language_pending_slugs"]
    assert not entry["waiting_language_slugs"]
    if source != OLD:
        assert not entry["episode_language_checks"], "source language proof must not be relabelled"
    assert not queue._cancel_withdrawn_watchlist_slugs({OLD}, "subscription recheck")
    assert not cancelled


@pytest.mark.parametrize("status", ["available", "language_pending", "waiting_for_language"])
def test_cancel_rechecks_episode_identity_after_another_snapshot(subscription, status):
    entry, state, cancelled = subscription
    entry["known_slugs"] = [ALTERNATE]
    entry["episode_states"] = {ALTERNATE: status}
    state.watchlist_new_slugs.clear()
    assert not queue._cancel_withdrawn_watchlist_slugs({OLD}, "subscription recheck")
    assert not cancelled


def test_completed_or_out_of_scope_episode_can_still_be_cancelled(subscription):
    entry, state, cancelled = subscription
    withdrawn = library._apply_watchlist_entry_state(entry, {
        "mode": "all", "cleanup_mode": "keep", "known_slugs": [ALTERNATE],
        "missing_slugs": set(), "episode_states": {}, "episode_language_checks": {},
    })
    assert withdrawn == {OLD}
    assert queue._cancel_withdrawn_watchlist_slugs(withdrawn, "already in library") == {OLD}
    assert cancelled == [OLD]


def test_unrelated_series_cannot_protect_same_episode_number(subscription):
    entry, state, cancelled = subscription
    entry.update(base_slug="serienstream:other-show", known_slugs=["vidrift:999-s1e6"],
                 episode_states={"vidrift:999-s1e6": "available"})
    state.watchlist_new_slugs.clear()
    assert queue._cancel_withdrawn_watchlist_slugs({OLD}, "subscription recheck") == {OLD}
    assert cancelled == [OLD]


def test_manually_cancelled_episode_is_not_restored(subscription):
    entry, state, cancelled = subscription
    entry["manual_cancelled_episodes"] = ["1:6"]
    state.watchlist_new_slugs.clear()
    assert queue._cancel_withdrawn_watchlist_slugs({OLD}, "manual cancellation") == {OLD}
    assert cancelled == [OLD]


def test_unknown_language_does_not_schedule_a_fresh_download(subscription):
    entry, state, _ = subscription
    state.picked.clear()
    library._apply_watchlist_entry_state(entry, {
        "mode": "all", "cleanup_mode": "keep", "known_slugs": [ALTERNATE],
        "missing_slugs": set(), "episode_states": {ALTERNATE: "language_pending"},
        "episode_language_checks": {},
    })
    assert not state.watchlist_new_slugs.get(BASE)
    assert entry["episode_states"] == {ALTERNATE: "language_pending"}


def test_pending_probe_can_remove_pending_marker_without_losing_active_job(subscription):
    entry, state, cancelled = subscription
    library._update_watchlist_language_states(entry, {OLD: None})
    assert OLD not in state.watchlist_new_slugs.get(BASE, set())
    assert OLD in state.picked

    withdrawn = library._apply_watchlist_entry_state(entry, {
        "mode": "all", "cleanup_mode": "keep", "known_slugs": [ALTERNATE],
        "missing_slugs": {ALTERNATE}, "episode_states": {ALTERNATE: "available"},
        "episode_language_checks": {},
    })
    assert not withdrawn
    assert state.watchlist_new_slugs[BASE] == {OLD}
    assert entry["known_slugs"] == [OLD]
    assert not queue._cancel_withdrawn_watchlist_slugs({OLD}, "subscription recheck")
    assert not cancelled
