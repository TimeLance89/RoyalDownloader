"""Exercise subscription classification, retries and dispatch as one flow."""
import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401
from api import api_library_router as library
from application_services import automation, smart_automation
from providers.models import FilmpalastMovie, HosterInfo


@pytest.fixture
def flow(monkeypatch):
    slug = 'vidrift:42-s1e3'
    entry = {'base_slug': 'serienstream:fixture', 'title': 'Fixture', 'tmdb_id': '42',
             'known_slugs': [slug], 'episode_states': {slug: 'language_pending'}}
    state = SimpleNamespace(
        watchlist=[entry], watchlist_new_slugs={}, watchlist_lock=threading.RLock(),
        auto_download_lock=threading.RLock(), queue_lifecycle_lock=threading.RLock(),
        queue_claim_lock=threading.RLock(), download_state_lock=threading.RLock(),
        automation={'auto_download': True}, watchlist_global_error='',
        content_languages={'de'}, subscription_content_languages={},
        picked=set(), counted_queue_slugs=set(), fp_movies={},
        dl_queue=SimpleNamespace(active_jobs=list),
    )
    monkeypatch.setattr(automation, 'state', state)
    monkeypatch.setattr(smart_automation, 'state', state)
    monkeypatch.setattr(library, 'state', state)
    enqueued, persisted, logs = [], [], []
    for name in ['log', 'broadcast', '_persist_watchlist_background', '_persist_queue_state']:
        monkeypatch.setattr(automation, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(automation, 'log', lambda *args: logs.append(args))
    monkeypatch.setattr(automation, 'is_within_download_window', lambda: True)
    monkeypatch.setattr(automation, '_watchlist_retry_allowed', lambda _: True)
    monkeypatch.setattr(automation, '_content_already_available', lambda *_: (False, ''))
    monkeypatch.setattr(automation, 'watchlist_payload', dict)
    monkeypatch.setattr(automation, '_persist_new_queue_claims', lambda slugs: persisted.append(list(slugs)) or True)
    monkeypatch.setattr(automation, '_enqueue_automatic_downloads', lambda slugs, **kwargs: enqueued.extend(slugs) or set(slugs))
    movie = FilmpalastMovie('Fixture S01E03', 'https://fixture.invalid/episode',
                           hosters=[HosterInfo('VOE', 'https://fixture.invalid/hoster', 'de')])
    monkeypatch.setattr(automation, 'load_movie_for_slug', lambda _: movie)
    return SimpleNamespace(slug=slug, entry=entry, state=state, enqueued=enqueued,
                           persisted=persisted, logs=logs, movie=movie)


def test_new_de_evidence_dispatches_once_and_preserves_requested_language(flow):
    library._update_watchlist_language_states(flow.entry, {flow.slug: ['de']})
    automation._auto_download_new_episodes()
    automation._auto_download_new_episodes()
    assert flow.enqueued == [flow.slug]
    assert flow.persisted == [[flow.slug]]
    assert flow.movie._subscription_content_languages == ['de']
    assert flow.state.picked == {flow.slug}


@pytest.mark.parametrize('status', ['language_pending', 'waiting_for_language', 'upcoming'])
def test_stale_pending_list_cannot_bypass_episode_admission(flow, status):
    flow.state.watchlist_new_slugs[flow.entry['base_slug']] = {flow.slug}
    flow.entry['episode_states'][flow.slug] = status
    automation._auto_download_new_episodes()
    assert not flow.enqueued and not flow.persisted and not flow.state.picked


def test_source_absence_waits_then_retries_and_dispatches_once(monkeypatch, flow):
    clock = [100.0]
    monkeypatch.setattr(automation.time, 'time', lambda: clock[0])
    library._update_watchlist_language_states(flow.entry, {flow.slug: ['de']})
    monkeypatch.setattr(automation, 'load_movie_for_slug', lambda _: None)
    monkeypatch.setattr(automation, 'find_episode_fallbacks', lambda *a, **k: [])
    automation._auto_download_new_episodes()
    deadline = flow.entry['waiting_source_retries'][flow.slug]
    assert not flow.enqueued and flow.slug not in flow.state.picked
    monkeypatch.setattr(automation, 'load_movie_for_slug', lambda _: flow.movie)
    clock[0] = deadline - 1
    automation._auto_download_new_episodes()
    assert not flow.enqueued
    clock[0] = deadline
    automation._auto_download_new_episodes()
    automation._auto_download_new_episodes()
    assert flow.enqueued == [flow.slug]
    assert flow.slug not in flow.entry['waiting_release_slugs']
    assert flow.slug not in flow.entry['waiting_source_retries']


def test_changed_provider_fallback_uses_subscription_identity_and_language(monkeypatch, flow):
    flow.state.subscription_content_languages[flow.entry['base_slug']] = {'en'}
    flow.state.watchlist_new_slugs[flow.entry['base_slug']] = {flow.slug}
    calls = []
    monkeypatch.setattr(automation, 'find_episode_fallbacks', lambda *a, **k: calls.append((a, k)) or [flow.movie])
    assert automation._playable_episode_source(flow.slug, None) is flow.movie
    assert calls[0][1].get('content_languages') == ['en']
    assert calls[0][1].get('tmdb_id') == '42'


def test_queue_persistence_failure_never_dispatches(monkeypatch, flow):
    from application_services import persistence
    library._update_watchlist_language_states(flow.entry, {flow.slug: ['de']})
    flow.state.preparing_queue_slugs = set()
    flow.state.provider_waiting_jobs = {}
    flow.state.queue_job_by_slug = {}
    flow.state.queue_jobs = {}
    monkeypatch.setattr(persistence, 'state', flow.state)
    monkeypatch.setattr(persistence, '_persist_queue_state', lambda: False)
    monkeypatch.setattr(automation, '_persist_new_queue_claims', persistence._persist_new_queue_claims.__wrapped__)
    automation._auto_download_new_episodes()
    assert not flow.enqueued
    assert not flow.state.picked
    monkeypatch.setattr(persistence, '_persist_queue_state', lambda: True)
    automation._auto_download_new_episodes()
    assert flow.enqueued == [flow.slug]


def test_newly_confirmed_language_does_not_repeatedly_wake_scheduler(monkeypatch, flow):
    wakes = []
    monkeypatch.setattr(automation, 'wake_watchlist_auto_check', lambda: wakes.append(True))
    monkeypatch.setattr(library, '_persist_watchlist_background', lambda: None)
    monkeypatch.setattr(library, 'watchlist_payload', dict)
    monkeypatch.setattr(library, 'broadcast', lambda _: None)
    library.record_watchlist_episode_languages({flow.slug: ['de']})
    library.record_watchlist_episode_languages({flow.slug: ['de']})
    assert wakes == [True]


def test_concurrent_checks_dispatch_one_logical_episode(flow):
    from concurrent.futures import ThreadPoolExecutor
    library._update_watchlist_language_states(flow.entry, {flow.slug: ['de']})
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in [pool.submit(automation._auto_download_new_episodes) for _ in range(12)]:
            result.result(timeout=5)
    assert flow.enqueued == [flow.slug]
    assert flow.persisted == [[flow.slug]]


def test_cancellation_during_source_lookup_releases_claim_without_dispatch(monkeypatch, flow):
    library._update_watchlist_language_states(flow.entry, {flow.slug: ['de']})
    def cancel(_):
        flow.entry['manual_cancelled_episodes'] = ['1:3']
        return flow.movie
    monkeypatch.setattr(automation, 'load_movie_for_slug', cancel)
    automation._auto_download_new_episodes()
    assert not flow.enqueued and not flow.persisted and not flow.state.picked


def test_late_language_result_cannot_reopen_manually_cancelled_episode(monkeypatch, flow):
    flow.entry['manual_cancelled_episodes'] = ['1:3']
    wakes = []
    monkeypatch.setattr(automation, 'wake_watchlist_auto_check', lambda: wakes.append(True))
    monkeypatch.setattr(library, '_persist_watchlist_background', lambda: None)
    monkeypatch.setattr(library, 'watchlist_payload', dict)
    monkeypatch.setattr(library, 'broadcast', lambda _: None)
    library.record_watchlist_episode_languages({flow.slug: ['de']})
    assert flow.slug not in flow.state.watchlist_new_slugs.get(flow.entry['base_slug'], set())
    assert not wakes
