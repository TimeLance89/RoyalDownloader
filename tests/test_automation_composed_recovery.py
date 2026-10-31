"""Exercise the final composed workers, not an obsolete pre-wrapper loop."""
import pytest
import server
from application_services import movie_subscription_runtime_hardening as runtime
from application_services import smart_automation


class EndCycle(BaseException):
    pass


def test_composed_watchlist_retries_jellyfin_failure_without_starting_real_workers(monkeypatch):
    delays = []
    monkeypatch.setattr(runtime, '_ensure_movie_loop', lambda: None)
    monkeypatch.setattr(server, 'get_jellyfin_client',
                        lambda: (_ for _ in ()).throw(OSError('Jellyfin offline')))
    monkeypatch.setattr(server, 'log', lambda *_args: None)

    def stop(delay):
        delays.append(delay)
        raise EndCycle

    monkeypatch.setattr(server, 'wait_for_watchlist_auto_check', stop)
    with pytest.raises(EndCycle):
        server.watchlist_auto_check_loop()
    assert delays == [60]


@pytest.mark.parametrize('interval', ['broken', None, float('inf')])
def test_movie_worker_recovers_invalid_interval_and_check_failure(monkeypatch, interval):
    delays = []
    monkeypatch.setattr(server.state, 'automation', {'check_interval_min': interval})
    monkeypatch.setattr(server, 'check_movie_subscriptions',
                        lambda: (_ for _ in ()).throw(OSError('subscription check offline')))
    monkeypatch.setattr(server, 'log', lambda *_args: None)

    def stop(delay):
        delays.append(delay)
        raise EndCycle

    monkeypatch.setattr(smart_automation, 'time', type('Clock', (), {
        'monotonic': staticmethod(lambda: 1), 'sleep': staticmethod(stop),
    }))
    with pytest.raises(EndCycle):
        server.movie_subscription_auto_check_loop()
    assert delays == [60]


def test_movie_worker_checks_missing_movies_outside_upgrade_night_window(monkeypatch):
    calls, delays = [], []
    monkeypatch.setattr(server.state, 'automation', {
        'check_interval_min': 30, 'movie_upgrades_night_only': True,
        'movie_upgrade_window_start': 1, 'movie_upgrade_window_end': 3,
    })
    monkeypatch.setattr(server, 'check_movie_subscriptions', lambda: calls.append(True))
    monkeypatch.setattr(smart_automation.smart_policy.time, 'localtime',
                        lambda: type('LocalTime', (), {'tm_hour': 8})())
    assert not smart_automation.smart_policy.automatic_movie_upgrade_decision(server.state)[0]

    def stop(delay):
        delays.append(delay)
        raise EndCycle

    monkeypatch.setattr(smart_automation, 'time', type('Clock', (), {
        'monotonic': staticmethod(lambda: 1), 'sleep': staticmethod(stop),
    }))
    with pytest.raises(EndCycle):
        server.movie_subscription_auto_check_loop()
    assert calls == [True]
    assert delays == [1800]


def test_movie_worker_can_retry_thread_start_failure(monkeypatch):
    class CannotStart:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError('cannot start new thread')

    monkeypatch.setattr(runtime, '_movie_loop_started', False)
    monkeypatch.setattr(runtime, 'threading', type('Threads', (), {'Thread': CannotStart}))
    with pytest.raises(RuntimeError, match='cannot start'):
        runtime._ensure_movie_loop()
    assert runtime._movie_loop_started is False
