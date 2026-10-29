"""Shared inventory I/O must preserve freshness, isolation and queue safety."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time

import pytest
import server  # noqa: F401 - register service composition

from application_services.jellyfin_inventory import cached_inventory, publish_inventory, read_inventory, SPECS
from integrations.jellyfin_reads import InventoryReads, ReadResult, inventory_reads, scope_key


def state():
    result = SimpleNamespace(jellyfin_cache_lock=threading.RLock(), jellyfin_config_generation=1,
                             jellyfin_cfg={'user_id': 'alice'}, jellyfin_targeted_episodes={},
                             jellyfin_live_checked_at=time.time(), jellyfin_live_stale=False)
    for prefix, lock, counter, _method in SPECS.values():
        setattr(result, lock, threading.Lock())
        for suffix, value in [('', None), ('_time', 0), ('_available', False), ('_retry_after', 0)]:
            setattr(result, prefix + suffix, value)
        if counter:
            setattr(result, counter, 0)
    return result


def client(**methods):
    return SimpleNamespace(configured=True, base_url='http://jellyfin:8096', api_key='private', **methods)


def test_live_and_forced_reader_share_one_request_without_blocking_cached_ui():
    data = state()
    old = data.jellyfin_library = [{'id': 'cached'}]
    started, release = threading.Event(), threading.Event()
    calls = []

    def load():
        calls.append(True)
        started.set()
        assert release.wait(3)
        return [{'id': 'fresh', 'quality_rank': 2160}]

    jf = client(list_movies=load)
    with ThreadPoolExecutor(2) as pool:
        live = pool.submit(read_inventory, data, jf, 'movies', 1, background=True)
        assert started.wait(3)
        forced = pool.submit(cached_inventory, data, lambda: jf, 'movies', force=True)
        try:
            deadline = time.monotonic() + 2
            while inventory_reads(data).snapshot()['joined'] != 1 and time.monotonic() < deadline:
                threading.Event().wait(.001)
            assert inventory_reads(data).snapshot()['joined'] == 1
            # Normal reads use the published cache while I/O is in flight.
            data.jellyfin_library_available = True
            data.jellyfin_library_time = time.time()
            # Production live UI wrapper never waits for the legacy fetch lock.
            import application_services.jellyfin_live as module
            original_state, original_backend = module.state, module.backend_value
            module.state = data
            module.backend_value = lambda _name: lambda: jf
            try:
                assert module._cached_snapshot('jellyfin_library', False, lambda **_kw: pytest.fail('blocking read')) is old
            finally:
                module.state, module.backend_value = original_state, original_backend
        finally:
            release.set()
        result = live.result(timeout=3)
        assert forced.result(timeout=3) == result.value
    publish_inventory(data, 'movies', 1, result)
    assert len(calls) == 1
    assert data.jellyfin_movie_identities == [{'id': 'fresh', 'name': '', 'original_title': '',
                                            'sort_name': '', 'tmdb_id': '', 'year': None}]


def test_queued_request_reuses_completion_but_subsequent_force_is_fresh():
    now = [1.0]
    reader = InventoryReads(clock=lambda: now[0])
    calls = []
    key = (1, b'scope', 'movies', '')
    requested = reader.clock()
    now[0] = 2
    first = reader.read(key, lambda: calls.append(1) or [], requested=requested)
    assert reader.read(key, lambda: pytest.fail('queued duplicate'), requested=requested) is first
    now[0] = 3
    reader.read(key, lambda: calls.append(2) or [])
    assert calls == [1, 2]


def test_failure_budget_is_background_only_and_expires():
    now = [1.0]
    reader = InventoryReads(clock=lambda: now[0])
    key = (1, b'scope', 'movies', '')
    reader.read(key, lambda: None, background=True)
    now[0] = 2
    assert reader.read(key, lambda: pytest.fail('retry storm'), background=True).value is None
    assert reader.read(key, lambda: ['manual'], background=False).value == ['manual']
    now[0] = 3
    reader.read(key, lambda: None, background=True)
    now[0] = 34
    assert reader.read(key, lambda: ['recovered'], background=True).value == ['recovered']


@pytest.mark.parametrize('difference', ['user', 'generation', 'credential', 'origin', 'provider', 'library'])
def test_scope_never_shares_across_users_servers_or_configuration(difference):
    jf = client()
    before = scope_key(jf, 1, 'user_episodes', 'alice')
    gen, user = 1, 'alice'
    if difference == 'user':
        user = 'bob'
    elif difference == 'generation':
        gen = 2
    else:
        setattr(jf, {'credential': 'api_key', 'origin': 'base_url', 'provider': 'provider',
                     'library': 'libraries'}[difference], ['other'] if difference == 'library' else 'other')
    assert before != scope_key(jf, gen, 'user_episodes', user)


def test_old_config_or_out_of_order_publication_cannot_replace_newer_data():
    data = state()
    publish_inventory(data, 'movies', 1, ReadResult([{'id': 'new'}], 2, 2, 0))
    publish_inventory(data, 'movies', 1, ReadResult([{'id': 'old'}], 1, 1, 0))
    publish_inventory(data, 'movies', 0, ReadResult([{'id': 'wrong-server'}], 9, 9, 0))
    assert data.jellyfin_library == [{'id': 'new'}]
    assert data.jellyfin_movie_identities[0]['id'] == 'new'


def test_unavailable_movie_read_keeps_ui_rows_but_closes_ownership_safety_gate():
    data = state()
    jf = client(list_movies=lambda: [{'id': 'known'}])
    cached_inventory(data, lambda: jf, 'movies', force=True)
    jf.list_movies = lambda: None
    assert cached_inventory(data, lambda: jf, 'movies', force=True) == [{'id': 'known'}]
    assert data.jellyfin_library_available is False
    assert data.jellyfin_movie_identities_available is False


def test_exception_is_unavailable_and_does_not_wedge_singleflight():
    data = state()
    def unavailable():
        raise RuntimeError('network')
    jf = client(list_movies=unavailable)
    assert cached_inventory(data, lambda: jf, 'movies', force=True) is None
    jf.list_movies = lambda: []
    assert cached_inventory(data, lambda: jf, 'movies', force=True) == []
    assert inventory_reads(data).snapshot()['inflight'] == 0


def test_retained_snapshots_are_bounded_and_diagnostics_contain_no_secrets():
    reader = InventoryReads(max_entries=3)
    for user in range(10):
        reader.read(scope_key(client(), 1, 'user_episodes', str(user)), lambda: [])
    assert reader.snapshot()['retained_results'] == 3
    assert 'private' not in repr(reader.snapshot())


def test_stale_ui_wakeups_obey_probe_backoff_but_manual_refresh_can_retry(monkeypatch):
    import application_services.jellyfin_live as live
    data, jf, calls = state(), client(), []
    now = [1.0]
    data._jellyfin_inventory_reads = InventoryReads(clock=lambda: now[0])
    monkeypatch.setattr(live, 'state', data)
    monkeypatch.setattr(live, 'backend_value', lambda _name: lambda: jf)
    monkeypatch.setattr(live, '_failure_count', 0)
    monkeypatch.setattr(live, '_probe_library_revision', lambda _jf: calls.append(True))
    monkeypatch.setattr(live, 'request_jellyfin_live_refresh', lambda **_kw: None)
    assert live._monitor_cycle() == 'unavailable'
    now[0] = 1.1
    for _ in range(10):
        assert live._monitor_cycle() == 'unavailable'
    assert len(calls) == 1
    assert live._cached_snapshot('jellyfin_library', True, lambda **_kw: []) == []
    assert live._monitor_cycle() == 'unavailable'
    assert len(calls) == 2


def test_download_reconciliation_keeps_all_five_deadlines_and_user_reads(monkeypatch):
    import application_services.download_lifecycle as lifecycle
    from integrations.jellyfin_reads import is_background_read
    data = state()
    data.jellyfin_refresh_lock = threading.Lock()
    data.watchlist_lock, data.watchlist = threading.RLock(), []
    calls, waits = [], []
    clock = [0.0]
    def wait(delay):
        clock[0] += delay
        waits.append(clock[0])
        return False
    monkeypatch.setattr(lifecycle, 'state', data)
    monkeypatch.setattr(lifecycle, 'get_jellyfin_client', lambda: client())
    monkeypatch.setattr(lifecycle, 'media_scan_manager', lambda: SimpleNamespace(stop_event=SimpleNamespace(wait=wait)))
    monkeypatch.setattr(lifecycle.time, 'monotonic', lambda: clock[0])
    for name in ('log', '_persist_watchlist_background', 'broadcast', 'watchlist_payload'):
        monkeypatch.setattr(lifecycle, name, lambda *_args, **_kwargs: {})
    for name in ('library', 'episodes', 'series', 'user_episodes'):
        def read(*, force=False, dataset=name):
            assert force and is_background_read()
            calls.append(dataset)
        monkeypatch.setattr(lifecycle, 'get_jellyfin_' + name, read)
    monkeypatch.setattr(lifecycle, 'get_jellyfin_movie_identities', lambda **_kw: pytest.fail('redundant identity fetch'))
    lifecycle._refresh_jellyfin_after_download_once()
    assert waits == [5, 15, 30, 60, 120]
    assert calls == ['library', 'episodes', 'series', 'user_episodes'] * 5
    assert data.jellyfin_refresh_lock.acquire(blocking=False)
