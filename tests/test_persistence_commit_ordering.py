"""Concurrent commits must not revive or erase another generation's retry."""
import threading

import pytest
import server


@pytest.fixture
def isolated_retries():
    state = server.state
    with state.persistence_status_lock:
        saved = (dict(state.persistence_pending), dict(state.persistence_errors),
                 dict(state.persistence_generations), set(state.persistence_retrying))
        state.persistence_pending.clear()
        state.persistence_errors.clear()
        state.persistence_generations.clear()
        # No retry workers: these tests control the commit interleaving.
        state.persistence_retrying.update(state.persistence_write_locks)
    yield
    with state.persistence_status_lock:
        for target, original in zip((state.persistence_pending, state.persistence_errors,
                                     state.persistence_generations, state.persistence_retrying), saved):
            target.clear()
            target.update(original)


def _race(old_call, new_call, paused, release):
    errors = []
    new_done = threading.Event()

    def run(call, done=None):
        try:
            call()
        except BaseException as exc:
            errors.append(exc)
        finally:
            if done:
                done.set()

    old = threading.Thread(target=run, args=(old_call,))
    new = threading.Thread(target=run, args=(new_call, new_done))
    old.start()
    try:
        assert paused.wait(2)
        new.start()
        # Baseline permits the new commit to overtake the paused bookkeeping.
        # Fixed code serializes both with the existing resource write lock.
        new_done.wait(0.1)
    finally:
        release.set()
        old.join(2)
        if new.ident is not None:
            new.join(2)
    assert not old.is_alive() and not new.is_alive()
    assert not errors


@pytest.mark.parametrize('resource', ['queue', 'watchlist', 'movie_subscriptions'])
def test_failed_old_commit_cannot_revive_retry_after_new_success(resource, isolated_retries, monkeypatch):
    paused, release = threading.Event(), threading.Event()
    original = server._write_persistent_snapshot
    written = []

    def save(snapshot):
        written.append(snapshot)
        return snapshot == {"jobs": [], "history": [], "revision": 2}

    monkeypatch.setattr(server, '_persistence_saver', lambda _resource: save)
    monkeypatch.setattr(server, 'log', lambda *_args: None)

    def pause_old_write(key, snapshot):
        result = original(key, snapshot)
        if snapshot == {"jobs": [], "history": [], "revision": 1}:
            paused.set()
            assert release.wait(2)
        return result

    monkeypatch.setattr(server, '_write_persistent_snapshot', pause_old_write)
    _race(lambda: server._persist_background_snapshot(resource, {"jobs": [], "history": [], "revision": 1}),
          lambda: server._require_persistent_snapshot(resource, {"jobs": [], "history": [], "revision": 2}), paused, release)
    assert written == [{"jobs": [], "history": [], "revision": 1}, {"jobs": [], "history": [], "revision": 2}]
    assert server._persistence_status(resource)['pending_retry'] is False
    assert server._persistence_status(resource)['ok'] is True


@pytest.mark.parametrize('resource', ['queue', 'watchlist', 'movie_subscriptions'])
def test_old_success_cannot_erase_new_failed_commit_retry(resource, isolated_retries, monkeypatch):
    paused, release = threading.Event(), threading.Event()
    original = server._mark_persistence_success
    monkeypatch.setattr(server, '_persistence_saver',
                        lambda _resource: lambda snapshot: snapshot == {"jobs": [], "history": [], "revision": 1})
    monkeypatch.setattr(server, 'log', lambda *_args: None)

    def pause_success(key):
        paused.set()
        assert release.wait(2)
        original(key)

    monkeypatch.setattr(server, '_mark_persistence_success', pause_success)
    _race(lambda: server._persist_background_snapshot(resource, {"jobs": [], "history": [], "revision": 1}),
          lambda: server._persist_background_snapshot(resource, {"jobs": [], "history": [], "revision": 2}), paused, release)
    status = server._persistence_status(resource)
    assert status['pending_retry'] is True
    assert status['ok'] is False
    assert server.state.persistence_pending[resource]['snapshot'] == {"jobs": [], "history": [], "revision": 2}
