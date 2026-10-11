"""Invalid source deadlines must not starve unrelated waiting episodes."""

from __future__ import annotations

from collections import OrderedDict

import pytest

import server
from application_services import download_lifecycle as lifecycle


@pytest.mark.parametrize("invalid", [
    "not-a-timestamp",
    "nan",
    float("nan"),
    "inf",
    float("inf"),
    float("-inf"),
    {},
    [],
    -10,
])
def test_invalid_deadline_is_due_for_normal_source_recovery(invalid):
    item = {"slug": "example:episode", "next_retry_at": invalid}
    assert lifecycle._waiting_retry_due(item, now=1000.0) is True
    assert lifecycle._waiting_retry_at(item) == 0.0


def test_valid_future_deadline_remains_protected_from_early_retries():
    item = {"slug": "example:future", "next_retry_at": "2000.5"}
    assert lifecycle._waiting_retry_at(item) == 2000.5
    assert lifecycle._waiting_retry_due(item, now=2000.0) is False
    assert lifecycle._waiting_retry_due(item, now=2000.5) is True


def test_one_corrupt_deadline_does_not_block_other_due_episodes(monkeypatch):
    state = server.state
    old_waiting = OrderedDict(state.provider_waiting_jobs)
    old_running = state.provider_retry_worker_running
    recovered = []
    errors = []

    class HealthyProvider:
        def status(self, provider):
            assert provider == "serienstream"
            return {"state": server.HEALTHY}

    try:
        with state.queue_claim_lock:
            state.provider_waiting_jobs.clear()
            state.provider_waiting_jobs["invalid"] = {
                "slug": "invalid", "next_retry_at": "broken",
            }
            state.provider_waiting_jobs["due"] = {
                "slug": "due", "next_retry_at": 0,
            }
            state.provider_retry_worker_running = True

        monkeypatch.setattr(state, "provider_health", HealthyProvider())
        monkeypatch.setattr(server, "log", lambda *args: errors.append(args))

        def resume():
            with state.queue_claim_lock:
                recovered.extend(state.provider_waiting_jobs.keys())
                state.provider_waiting_jobs.clear()

        # Service calls are forwarded through server at runtime.
        monkeypatch.setattr(server, "_resume_waiting_provider_jobs", resume)
        monkeypatch.setattr(server, "_ensure_provider_retry_worker",
                            lambda: pytest.fail("unexpected replacement worker"))
        lifecycle._provider_retry_worker()
        assert recovered == ["invalid", "due"]
        assert not errors
        assert state.provider_retry_worker_running is False
    finally:
        with state.queue_claim_lock:
            state.provider_waiting_jobs.clear()
            state.provider_waiting_jobs.update(old_waiting)
            state.provider_retry_worker_running = old_running
