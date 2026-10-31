"""Missing movies use normal automation; only existing copies use upgrade hours."""

import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401 - compose the production services
import api.api_library_router as library
from application_services import movie_subscription_quality as quality
from features import smart_automation as policy
from providers.models import FilmpalastMovie


@pytest.fixture
def acquisition(monkeypatch):
    movie = FilmpalastMovie('Street Fighter', 'https://example.test/street-fighter')
    state = SimpleNamespace(
        automation={'auto_download': True, 'movie_upgrades_night_only': True,
                    'movie_upgrade_window_start': 1, 'movie_upgrade_window_end': 3,
                    'min_free_space_gb': 0},
        movie_subscriptions=[], movie_subscription_check_lock=threading.Lock(),
        movie_subscriptions_lock=threading.RLock(), queue_lifecycle_lock=threading.RLock(),
        queue_claim_lock=threading.RLock(), jellyfin_cfg={}, picked=set(), fp_movies={},
    )
    calls, queued = [], []
    clock = SimpleNamespace(tm_hour=8, tm_wday=5)
    monkeypatch.setattr(policy.time, 'localtime', lambda *_: clock)
    monkeypatch.setattr(library, 'state', state)
    monkeypatch.setattr(library, 'get_jellyfin_client', lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(library, '_movie_subscription_jellyfin_item', lambda *_: None)
    monkeypatch.setattr(library, '_movie_subscription_sources', lambda e: calls.append(e['key']) or [movie])
    monkeypatch.setattr(library, '_prepare_movie_subscription_upgrade', lambda *_: (movie, [], 1080, '1080p'))
    monkeypatch.setattr(library, '_persist_new_queue_claims', lambda *_: True)
    monkeypatch.setattr(library, '_persist_movie_subscriptions_background', lambda: True)
    monkeypatch.setattr(library, 'movie_subscriptions_payload', lambda: {})
    monkeypatch.setattr(library, 'broadcast', lambda *_: None)
    monkeypatch.setattr(library, 'log', lambda *_: None)
    monkeypatch.setattr(library, 'is_within_download_window',
                        lambda: policy.schedule_is_open(state.automation, clock.tm_wday, clock.tm_hour))
    monkeypatch.setattr(library, '_enqueue_automatic_downloads',
                        lambda slugs, **_: queued.extend(slugs) or set(slugs))
    return state, calls, queued, clock


def _entry(key='missing', **overrides):
    return {'key': key, 'source_slug': key, 'title': key,
            'current_quality_rank': 0, 'upgrade_enabled': True, **overrides}


def test_daytime_mixed_batch_acquires_missing_movie_and_defers_upgrades(acquisition):
    state, calls, queued, _ = acquisition
    missing = _entry()
    owned = _entry('owned', current_quality_rank=720)
    state.movie_subscriptions = [owned, missing]

    assert quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS() == 2
    assert calls == queued == ['missing']
    assert missing['pending_slug'] == 'missing'
    assert 'Nachtfenster' in owned['deferred_reason']
    # A second pass does not duplicate the already claimed download.
    quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS()
    assert queued == ['missing']


@pytest.mark.parametrize('evidence', [
    {'existing_path': '/movies/owned.mp4'}, {'last_upgraded': 123},
])
def test_existing_copy_without_quality_is_not_a_new_acquisition(acquisition, evidence):
    state, calls, queued, _ = acquisition
    state.movie_subscriptions = [_entry(**evidence)]
    quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS()
    assert calls == queued == []


def test_library_discovery_prevents_daytime_upgrade_of_a_previously_missing_movie(acquisition, monkeypatch):
    state, calls, queued, _ = acquisition
    state.movie_subscriptions = [_entry()]
    monkeypatch.setattr(library, '_movie_subscription_jellyfin_item',
                        lambda *_: {'quality_rank': 720, 'path': '/movies/found.mp4'})
    quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS()
    assert state.movie_subscriptions[0]['current_quality_rank'] == 720
    assert calls == queued == []


def test_existing_movie_still_upgrades_in_night_window(acquisition):
    state, calls, queued, clock = acquisition
    clock.tm_hour = 2
    state.movie_subscriptions = [_entry(current_quality_rank=720)]
    quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS()
    assert calls == queued == ['missing']


@pytest.mark.parametrize('restriction', ['disabled', 'normal-window', 'no-source', 'disk'])
def test_acquisitions_keep_automation_source_and_storage_guards(acquisition, monkeypatch, restriction):
    state, calls, queued, _ = acquisition
    state.movie_subscriptions = [_entry()]
    if restriction == 'disabled':
        state.automation['auto_download'] = False
    elif restriction == 'normal-window':
        state.automation.update(weekend_window_start=1, weekend_window_end=3)
    elif restriction == 'no-source':
        monkeypatch.setattr(library, '_prepare_movie_subscription_upgrade', lambda *_: (None, [], 0, ''))
    else:
        monkeypatch.setattr(policy, 'storage_status', lambda *_: {'ok': False, 'error': 'Speicher offline'})
    quality._ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS()
    assert queued == []
    assert not state.picked
    if restriction == 'disk':
        assert calls == []
