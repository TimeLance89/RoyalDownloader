"""Recovery regressions for the long-lived scheduled integration workers."""

from __future__ import annotations

import pytest

from application_services import automation, seerr


class _StopAfterProbe(BaseException):
    pass


def test_watchlist_scheduler_invalid_interval_stays_bounded():
    assert automation._watchlist_auto_check_delay(1, 1, "invalid") == 1800
    assert automation._watchlist_auto_check_delay(1, 1, None) == 1800
    assert automation._watchlist_auto_check_delay(1, 1, -100) == 300
    assert automation._watchlist_auto_check_delay(1, 1, 50000) == 24 * 3600


def test_watchlist_worker_retries_instead_of_dying_on_jellyfin_exception(monkeypatch):
    def fail_jellyfin():
        raise OSError("simulated Jellyfin network failure")

    intervals = []
    monkeypatch.setattr(automation, "get_jellyfin_client", fail_jellyfin)
    monkeypatch.setattr(automation, "log", lambda *_args: None)

    def stop_after_wait(interval):
        intervals.append(interval)
        raise _StopAfterProbe

    monkeypatch.setattr(automation, "wait_for_watchlist_auto_check", stop_after_wait)
    with pytest.raises(_StopAfterProbe):
        automation.watchlist_auto_check_loop()
    assert intervals == [60]


def test_watchlist_worker_keeps_movie_checks_separate_from_failed_series(monkeypatch):
    movies = []
    intervals = []
    monkeypatch.setattr(automation, "get_jellyfin_client", lambda: type("JF", (), {"configured": False})())
    monkeypatch.setattr(automation, "_watchlist_auto_check_once",
                        lambda: (_ for _ in ()).throw(OSError("series offline")))
    monkeypatch.setattr(automation, "check_movie_subscriptions", lambda: movies.append(True))
    monkeypatch.setattr(automation, "log", lambda *_args: None)

    def stop_after_wait(interval):
        intervals.append(interval)
        raise _StopAfterProbe

    monkeypatch.setattr(automation, "wait_for_watchlist_auto_check", stop_after_wait)
    with pytest.raises(_StopAfterProbe):
        automation.watchlist_auto_check_loop()
    assert movies == [True]
    assert intervals == [60]


@pytest.mark.parametrize("value,expected", [
    ("bad", 60), (None, 60), (0, 60), (-10, 15),
    ("7", 15), (120, 120), (99999999, 86400),
])
def test_seerr_interval_recovers_malformed_settings(monkeypatch, value, expected):
    monkeypatch.setattr(seerr.state, "seerr_cfg", {
        "enabled": True, "poll_interval_seconds": value,
    })
    assert seerr._seerr_poll_interval() == expected


class _FiniteStop:
    def __init__(self, iterations):
        self.iterations = iterations
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls > self.iterations


class _FakeWake:
    def __init__(self):
        self.delays = []

    def wait(self, duration):
        self.delays.append(duration)

    def clear(self):
        pass


def test_seerr_worker_retries_failed_hydration_then_processes_requests(monkeypatch):
    attempts = []
    polls = []
    wake = _FakeWake()
    monkeypatch.setattr(seerr.state, "seerr_cfg", {
        "enabled": True, "poll_interval_seconds": "bad",
    })
    monkeypatch.setattr(seerr, "_seerr_stop_event", _FiniteStop(2))
    monkeypatch.setattr(seerr, "_seerr_wake_event", wake)
    monkeypatch.setattr(seerr, "log", lambda *_args: None)

    def hydrate():
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("simulated stale request state")

    monkeypatch.setattr(seerr, "_hydrate_seerr_jobs", hydrate)
    monkeypatch.setattr(seerr, "seerr_poll_once", lambda: polls.append(True) or {"ok": True})
    seerr.seerr_poll_loop()

    assert len(attempts) == 2
    assert polls == [True]
    assert wake.delays == [60, 60]


def test_seerr_worker_is_not_killed_by_unexpected_poll_exception(monkeypatch):
    wake = _FakeWake()
    calls = []
    monkeypatch.setattr(seerr.state, "seerr_cfg", {
        "enabled": True, "poll_interval_seconds": 20,
    })
    monkeypatch.setattr(seerr, "_seerr_stop_event", _FiniteStop(2))
    monkeypatch.setattr(seerr, "_seerr_wake_event", wake)
    monkeypatch.setattr(seerr, "_hydrate_seerr_jobs", lambda: None)
    monkeypatch.setattr(seerr, "log", lambda *_args: None)

    def intermittent():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("remote error")
        return {"ok": True}

    monkeypatch.setattr(seerr, "seerr_poll_once", intermittent)
    seerr.seerr_poll_loop()
    assert len(calls) == 2
    assert wake.delays == [20, 20]
