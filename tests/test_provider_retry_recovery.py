"""Ensure provider retry work cannot become a rapid thread-crash loop."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import server  # noqa: F401 - registers the composed service backend
from application_services import download_lifecycle as lifecycle


@pytest.mark.parametrize("fault", ["health_error", "bad_deadline"])
def test_provider_retry_worker_recovers_from_fault_without_spawning_another_worker(
    monkeypatch, fault,
):
    state = lifecycle.state
    saved = dict(state.provider_waiting_jobs)
    previous_running = state.provider_retry_worker_running
    try:
        with state.queue_claim_lock:
            state.provider_waiting_jobs.clear()
            state.provider_waiting_jobs["wait-1"] = {
                "slug": "wait-1", "next_retry_at": "unparseable" if fault == "bad_deadline" else 0,
            }
            state.provider_retry_worker_running = True

        attempts = []
        logs = []
        class FakeHealth:
            def status(self, provider):
                assert provider == "serienstream"
                attempts.append(provider)
                raise RuntimeError("temporary health failure")

        if fault == "health_error":
            monkeypatch.setattr(state, "provider_health", FakeHealth())
        monkeypatch.setattr(lifecycle, "log", lambda *args: logs.append(args))
        monkeypatch.setattr(lifecycle, "_ensure_provider_retry_worker",
                            lambda: pytest.fail("worker must not respawn itself"))

        delays = []
        def recover_after_backoff(seconds):
            delays.append(seconds)
            with state.queue_claim_lock:
                state.provider_waiting_jobs.clear()

        monkeypatch.setattr(lifecycle, "time", SimpleNamespace(
            monotonic=lambda: 1000.0,
            time=lambda: 2000.0,
            sleep=recover_after_backoff,
        ))
        lifecycle._provider_retry_worker()

        assert delays == [10]
        assert len(logs) == 1
        assert state.provider_retry_worker_running is False
        if fault == "health_error":
            assert attempts == ["serienstream"]
    finally:
        with state.queue_claim_lock:
            state.provider_waiting_jobs.clear()
            state.provider_waiting_jobs.update(saved)
            state.provider_retry_worker_running = previous_running
