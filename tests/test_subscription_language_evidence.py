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
    monkeypatch.setattr("application_services.movie_catalog.provider_priority", lambda kind: ["serienstream"] if kind == "series" else [])
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
    assert len(checks) == 20 and all(record["languages"] is None for record in checks.values())
    entry["episode_language_checks"] = checks
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda *_: ["de"])
    languages, _ = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    assert languages[series.all_episodes[-1].slug] == ["de"]


def test_local_and_future_episodes_are_not_probed(monkeypatch, subscription):
    entry, series, _ = subscription
    series.all_episodes[1].release_at = "2099-01-01"
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


def test_incomplete_detail_check_wakes_subscription_retry_once(monkeypatch, subscription):
    entry, series, state = subscription
    failed, confirmed = (episode.slug for episode in series.all_episodes[:2])
    entry["episode_language_checks"] = {
        confirmed: {"languages": ["de"], "checked_at": library.time.time()},
    }
    wakes = []
    monkeypatch.setattr(automation, "wake_watchlist_auto_check", lambda: wakes.append(True))
    monkeypatch.setattr(library, "_persist_watchlist_background", lambda: None)
    monkeypatch.setattr(library, "watchlist_payload", lambda: {})
    monkeypatch.setattr(library, "broadcast", lambda _: None)

    library.record_watchlist_episode_language_pending([failed, confirmed])
    library.record_watchlist_episode_language_pending([failed, confirmed])

    assert wakes == [True]
    assert entry["episode_states"][failed] == "language_pending"
    assert entry["episode_language_checks"][failed]["languages"] is None
    assert failed not in state.watchlist_new_slugs[series.base_slug]
    assert entry["episode_states"][confirmed] == "available"


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



def test_queued_language_wait_is_shown_in_inbox(monkeypatch, subscription):
    entry, series, state = subscription
    slug = series.all_episodes[0].slug
    entry["episode_states"] = {slug: "available"}
    state.watchlist_new_slugs = {series.base_slug: {slug}}
    state.queue_claim_lock = threading.RLock()
    state.picked = {slug}
    state.automation = {"auto_download": False}
    state.jellyfin_cfg = {}
    state.watchlist_global_error = ""
    monkeypatch.setattr(persistence, "state", state)
    state.queue_jobs = {"job": {"slug": slug, "wait_reason": "language_unavailable"}}
    monkeypatch.setattr(persistence, "_persistence_status", lambda _: {"ok": True})
    item = persistence.watchlist_payload.__wrapped__()["watchlist"][0]
    assert item["waiting_language_count"] == 1
    assert item["queued_count"] == 0
    assert item["failed_count"] == 0
    assert item["status"] == "waiting_for_language"


@pytest.mark.parametrize("available", [True, False])
def test_switched_subscription_on_monolingual_source_checks_alternatives(monkeypatch, subscription, available):
    from application_services import download_lifecycle
    from providers.models import FilmpalastMovie, HosterInfo
    entry, series, state = subscription
    state.content_languages = {"en"}
    monkeypatch.setattr("application_services.movie_catalog.provider_priority", lambda kind: ["serienstream", "vidrift"] if kind == "series" else [])
    # A DE-only source may remain the identity of a subscription after switching.
    from providers import catalog
    monkeypatch.setattr(catalog, "provider_supports_languages", lambda key, langs: key != "serienstream")
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda *_: ["de"])
    alternative = FilmpalastMovie("Fixture", "https://vidrift.test/episode", provider="vidrift",
                                 hosters=[HosterInfo("VOE", "https://voe.test/episode", "en")])
    def fallback(*args, **kwargs):
        assert "serienstream" in kwargs["excluded_providers"]
        if not available:
            raise RuntimeError("Temporary alternate-source failure")
        return [alternative]
    monkeypatch.setattr(download_lifecycle, "find_episode_fallbacks", fallback)
    languages, checks = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    slug = series.all_episodes[0].slug
    assert languages[slug] == (["de", "en"] if available else ["de"])
    assert checks[slug]["languages"] == languages[slug]


def test_new_matching_source_releases_previous_audio_mismatch(subscription):
    entry, series, state = subscription
    slug = series.all_episodes[0].slug
    entry["episode_states"][slug] = "waiting_for_language"
    entry["waiting_language_slugs"] = [slug]
    entry["failed_downloads"] = {slug: {"audio_language_mismatch": True}}
    library._update_watchlist_language_states(entry, {slug: ["de"]})
    assert slug in state.watchlist_new_slugs[series.base_slug]
    assert entry["episode_states"][slug] == "available"
    assert not entry["waiting_language_slugs"]
    assert not entry["failed_downloads"]


def test_failed_alternative_does_not_erase_known_foreign_language(monkeypatch, subscription):
    from application_services import download_lifecycle
    entry, series, _ = subscription
    monkeypatch.setattr("application_services.movie_catalog.provider_priority",
                        lambda kind: ["huhu", "serienstream"] if kind == "series" else [])
    calls = []
    alternate_start = []
    monkeypatch.setattr(library, "episode_languages_for_slug", lambda p, s: calls.append(s) or ["en"])
    def unavailable(*args, **kwargs):
        # All primary episode checks precede the first alternative lookup.
        alternate_start.append(len(calls))
        raise RuntimeError("Alternative catalog offline")
    monkeypatch.setattr(download_lifecycle, "find_episode_fallbacks", unavailable)
    languages, _ = library._watchlist_episode_language_evidence(entry, series, entry["episode_states"])
    states = classify_subscription_episode_states(series.all_episodes, "all",
        enabled_content_languages={"de"}, exact_content_languages=languages)
    assert sum(value == "waiting_for_language" for value in states.values()) == 20
    assert sum(value == "language_pending" for value in states.values()) == 3
    assert alternate_start and alternate_start[0] == 20


@pytest.mark.parametrize("deadline,actionable", [(99, True), (100, True), (101, False), (None, True)])
def test_source_wait_becomes_actionable_when_retry_is_due(monkeypatch, deadline, actionable):
    slug = "fixture-s01e01"
    monkeypatch.setattr(automation.time, "time", lambda: 100)
    entry = {"waiting_release_slugs": [slug], "waiting_source_retries": {},
             "episode_states": {slug: "available"}}
    if deadline is not None:
        entry["waiting_source_retries"][slug] = deadline
    assert automation._watchlist_episode_is_actionable(entry, slug) is actionable


def test_manual_check_runs_automatic_dispatch_after_classifying(monkeypatch, subscription):
    import asyncio
    _, _, _state = subscription
    calls = []
    monkeypatch.setattr(library, "check_watchlist_entries", lambda *a, **k: calls.append("check") or 1)
    monkeypatch.setattr(automation, "_auto_download_new_episodes", lambda: calls.append("dispatch"))
    monkeypatch.setattr(library, "watchlist_payload", lambda: {})
    monkeypatch.setattr(library, "broadcast", lambda _: None)
    result = asyncio.run(library.api_watchlist_check(library.WatchlistCheckBody()))
    assert calls == ["check", "dispatch"]
    assert result["checked"] == 1


def test_manually_cancelled_episode_is_not_advertised_or_probed(monkeypatch, subscription):
    entry, series, _ = subscription
    slug = series.all_episodes[0].slug
    entry['manual_cancelled_episodes'] = ['1:1']
    monkeypatch.setattr(library, 'compute_downloaded_episodes', lambda _: set())
    monkeypatch.setattr(library, '_unreleased_episode_slugs', lambda *_: set())
    calls = []
    monkeypatch.setattr(library, 'episode_languages_for_slug', lambda p, s: calls.append(s) or ['de'])
    client = SimpleNamespace(configured=False)
    calculated = library._calculate_watchlist_entry_state(entry, series, client, None, None)
    assert slug not in calculated['episode_states']
    assert slug not in calculated['missing_slugs']
    assert slug not in calls


def test_accepted_subscription_is_saved_before_next_provider_failure(monkeypatch, subscription):
    from copy import deepcopy
    entry, series, state = subscription
    entry.update(title='Fixture', sample_url='first', last_checked=1)
    second = {'base_slug': 'second', 'title': 'Second', 'sample_url': 'second', 'last_checked': 2}
    state.watchlist.append(second)
    state.jellyfin_cache_lock = threading.RLock()
    state.jellyfin_config_generation = state.jellyfin_episode_data_generation = 1
    state.jellyfin_cfg = {}
    state.jellyfin_episodes_available = state.jellyfin_series_available = False
    state.jellyfin_user_episodes_available = False
    state.series_cache = {}
    state.picked = set()
    saved, events = [], []
    def get_series(value, title):
        if value == 'first':
            return series
        assert saved and saved[0][0]['last_checked'] > 1
        assert events, 'The UI must receive first-subscription progress before the second lookup'
        raise RuntimeError('second provider unavailable')
    monkeypatch.setattr(library, 'media_client', lambda _: SimpleNamespace(configured=False))
    monkeypatch.setattr(library, 'get_series_for_value', get_series)
    monkeypatch.setattr(library, 'get_tmdb_series', lambda *_: None)
    monkeypatch.setattr(library, '_calculate_watchlist_entry_state', lambda *_: {
        'mode': 'all', 'cleanup_mode': 'keep', 'known_slugs': [], 'missing_slugs': set(), 'episode_states': {},
    })
    monkeypatch.setattr(library, '_persist_watchlist_background', lambda: saved.append(deepcopy(state.watchlist)))
    monkeypatch.setattr(library, 'watchlist_payload', dict)
    monkeypatch.setattr(library, 'broadcast', events.append)
    monkeypatch.setattr(library, 'log', lambda *_: None)
    assert library._check_watchlist_entries_impl([second, entry]) == 1
    assert not entry['last_error']
    assert second['last_error'] == 'second provider unavailable'
