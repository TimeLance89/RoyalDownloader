"""Subscriptions use concrete hoster languages, without queuing unchecked episodes."""

import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401
from api import api_library_router as library
from application_services import persistence, automation
from providers.models import FilmpalastSeries, SeriesEpisode
from features.watchlist_policy import classify_subscription_episode_states


@pytest.fixture
def subscription(monkeypatch):
    episodes = [SeriesEpisode(1, i, f"serienstream:fixture-s01e{i:02d}", "https://s.to/episode") for i in range(1, 24)]
    series = FilmpalastSeries("Fixture", "serienstream:fixture", "https://s.to/serie/fixture", seasons={1: episodes})
    entry = {"base_slug": series.base_slug, "episode_states": {e.slug: "available" for e in episodes}}
    state = SimpleNamespace(watchlist=[entry], watchlist_lock=threading.RLock(),
                            watchlist_new_slugs={series.base_slug: {e.slug for e in episodes}},
                            content_languages={"de"})
    monkeypatch.setattr(library, "state", state)
    return entry, series, state


def test_exact_language_checks_are_bounded_and_unchecked_episodes_wait(monkeypatch, subscription):
    entry, series, _ = subscription
    calls = []
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda p, s: calls.append(s) or ["en"])
    languages, checks = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    states = classify_subscription_episode_states(series.all_episodes, "all",
        enabled_content_languages={"de"}, exact_content_languages=languages)
    assert len(calls) == 20
    assert set(states.values()) == {"waiting_for_language", "language_pending"}
    assert len(checks) == 20
    # Next check first inspects the remaining episodes; fresh evidence is reused.
    entry["episode_language_checks"] = checks
    library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    assert len(calls) == 23


def test_probe_failure_is_pending_and_retry_can_recover(monkeypatch, subscription):
    entry, series, _ = subscription
    def unavailable(*_):
        raise RuntimeError("Temporary provider failure")
    monkeypatch.setattr(library, "episode_languages_for_slug", unavailable)
    languages, checks = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    assert all(values is None for values in languages.values())
    assert checks == {}
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda *_: ["de"])
    languages, _ = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    assert languages[series.all_episodes[0].slug] == ["de"]


def test_local_and_future_episodes_are_not_probed(monkeypatch, subscription):
    entry, series, _ = subscription
    entry["episode_states"] = {series.all_episodes[1].slug: "upcoming"}
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda *_: pytest.fail("Unexpected probe"))
    assert library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])[0] == {}


def test_detail_probe_updates_inbox_and_clears_stale_language_failure(monkeypatch, subscription):
    entry, series, state = subscription
    slug = series.all_episodes[0].slug
    entry["failed_downloads"] = {slug: {"message": "stale failure"}}
    entry["waiting_release_slugs"] = [slug]
    writes, events = [], []
    monkeypatch.setattr(library, "_persist_watchlist_background", lambda: writes.append(True))
    monkeypatch.setattr(library, "watchlist_payload", lambda: {"watchlist": [entry]})
    monkeypatch.setattr(library, "broadcast", events.append)
    library.record_watchlist_episode_languages({slug: ["en"]})
    assert entry["episode_states"][slug] == "waiting_for_language"
    assert slug not in state.watchlist_new_slugs[series.base_slug]
    assert entry["failed_downloads"] == {}
    assert entry["waiting_release_slugs"] == []
    assert writes == [True] and len(events) == 1
    library.record_watchlist_episode_languages({slug: ["de"]})
    assert entry["episode_states"][slug] == "available"
    assert slug in state.watchlist_new_slugs[series.base_slug]


def test_new_detail_evidence_survives_an_older_subscription_snapshot(subscription):
    entry, series, state = subscription
    slug = series.all_episodes[0].slug
    import time
    entry["episode_language_checks"] = {slug: {"languages": ["en"], "checked_at": time.time()}}
    calculated = {"mode": "all", "cleanup_mode": "keep", "known_slugs": [slug],
                  "missing_slugs": {slug}, "episode_states": {slug: "available"},
                  "episode_language_checks": {slug: {"languages": ["de"], "checked_at": 1}}}
    library._apply_watchlist_entry_state(entry, calculated)
    assert entry["episode_states"][slug] == "waiting_for_language"
    assert slug not in state.watchlist_new_slugs.get(series.base_slug, set())


def test_pending_language_is_visible_but_never_a_download_failure(monkeypatch, subscription):
    entry, series, state = subscription
    slug = series.all_episodes[0].slug
    entry["episode_states"] = {slug: "language_pending"}
    entry["failed_downloads"] = {slug: {"message": "stale"}}
    state.watchlist_new_slugs = {series.base_slug: {slug}}
    state.queue_claim_lock = threading.RLock()
    state.picked = set()
    state.automation = {"auto_download": False}
    state.jellyfin_cfg = {}
    state.watchlist_global_error = ""
    monkeypatch.setattr(persistence, "state", state)
    monkeypatch.setattr(persistence, "_persistence_status", lambda _: {"ok": True})
    item = persistence.watchlist_payload.__wrapped__()["watchlist"][0]
    assert item["language_pending_count"] == 1
    assert item["open_count"] == item["failed_count"] == 0
    assert item["status"] == "language_pending"
    assert not automation._watchlist_episode_is_actionable(entry, slug)
