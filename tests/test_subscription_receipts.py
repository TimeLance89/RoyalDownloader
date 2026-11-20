"""Rejected/deleted episodes must not remain successful unread inbox items."""
import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401
from api import api_library_router as library
from core.config import _normalize_download_notifications
from features.subscription_receipts import reconcile_download_receipts, record_download_receipt


def receipt(slug='huhu:42:show-s01e01', downloaded_at=10):
    return {'slug': slug, 'season': 1, 'episode': 1, 'downloaded_at': downloaded_at, 'read': False}


def test_absent_rejected_episode_receipts_are_removed_but_german_file_is_kept():
    rejected = [receipt(f'huhu:42:show-s01e{i:02}', i) for i in range(1, 6)]
    good = receipt('serienstream:show-s01e06') | {'episode': 6}
    entry = {'downloaded_episode_notifications': [*rejected, good]}
    reconcile_download_receipts(entry, {(1, 6)}, {(1, i) for i in range(1, 7)}, 100)
    assert entry['downloaded_episode_notifications'] == [good]


@pytest.mark.parametrize('audio', ['confirmed', 'unclear', 'unavailable'])
def test_present_file_retains_its_actual_verification_result_after_restart(audio):
    note = receipt()
    entry = {'downloaded_episode_notifications': [note]}
    history = [{'slug': note['slug'], 'status': 'completed', 'completed_at': 9,
                'audio_check_status': audio}]
    reconcile_download_receipts(entry, {(1, 1)}, {(1, 1)}, 100, history)
    restored = _normalize_download_notifications(entry['downloaded_episode_notifications'])
    assert restored[0]['audio_check_status'] == audio
    assert not restored[0]['read']


def test_concurrent_success_after_inventory_started_is_not_lost():
    note = receipt(downloaded_at=101)
    entry = {'downloaded_episode_notifications': [note]}
    reconcile_download_receipts(entry, set(), {(1, 1)}, 100)
    assert entry['downloaded_episode_notifications'] == [note]


def test_provider_gap_does_not_erase_unevaluated_receipt():
    note = receipt()
    entry = {'downloaded_episode_notifications': [note]}
    reconcile_download_receipts(entry, set(), {(2, 1)}, 100)
    assert entry['downloaded_episode_notifications'] == [note]


def test_wrong_language_attempt_does_not_replace_valid_success_evidence():
    note = receipt()
    entry = {'downloaded_episode_notifications': [note]}
    history = [
        {'slug': note['slug'], 'status': 'completed', 'completed_at': 9, 'audio_check_status': 'confirmed'},
        {'slug': note['slug'], 'status': 'failed', 'completed_at': 20, 'audio_check_status': 'mismatch'},
    ]
    reconcile_download_receipts(entry, {(1, 1)}, {(1, 1)}, 100, history)
    assert entry['downloaded_episode_notifications'][0]['audio_check_status'] == 'confirmed'


def test_provider_switch_does_not_count_same_episode_twice():
    entry = {'downloaded_episode_notifications': [receipt()]}
    record_download_receipt(entry, 'serienstream:show-s01e01', 20, 'confirmed')
    assert len(entry['downloaded_episode_notifications']) == 1
    assert entry['downloaded_episode_notifications'][0]['audio_check_status'] == 'confirmed'


def test_cleanup_history_is_not_proof_of_current_availability(monkeypatch):
    from providers.models import FilmpalastSeries, SeriesEpisode
    series = FilmpalastSeries('Show', 'show', 'https://fixture.invalid',
        seasons={1: [SeriesEpisode(1, 1, 'show-s01e01', 'https://fixture.invalid/ep')]})
    entry = {'base_slug': 'show', 'cleanup_history': ['1:1'], 'downloaded_episode_notifications': [receipt('show-s01e01')]}
    monkeypatch.setattr(library, 'state', SimpleNamespace(
        queue_claim_lock=threading.RLock(), queue_history=[], content_languages={'de'},
        subscription_content_languages={}, picked=set(), watchlist_new_slugs={}))
    monkeypatch.setattr(library, 'compute_downloaded_episodes', lambda _: set())
    monkeypatch.setattr(library, '_unreleased_episode_slugs', lambda *_: set())
    monkeypatch.setattr(library, '_watchlist_episode_language_evidence', lambda *_: (None, {}))
    calculated = library._calculate_watchlist_entry_state(entry, series, SimpleNamespace(configured=False), None, None)
    assert calculated['receipt_inventory']['present'] == set()
    library._apply_watchlist_entry_state(entry, calculated)
    assert entry['downloaded_episode_notifications'] == []
