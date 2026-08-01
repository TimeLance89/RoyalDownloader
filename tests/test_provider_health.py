import json
import threading

from provider_health import COOLDOWN, HEALTHY, PROBING, ProviderHealth


class Clock:
    def __init__(self, value=1_000.0):
        self.value = value

    def __call__(self):
        return self.value


def manager(tmp_path, clock, **kwargs):
    return ProviderHealth(
        tmp_path / "health.json",
        clock=clock,
        initial_cooldown=kwargs.get("initial", 900),
        maximum_cooldown=kwargs.get("maximum", 21_600),
        multiplier=kwargs.get("multiplier", 2),
    )


def test_provider_starts_healthy(tmp_path):
    health = manager(tmp_path, Clock())
    assert health.request_allowed("serienstream")
    assert health.status("serienstream")["state"] == HEALTHY


def test_gate_sets_persistent_cooldown(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    status = health.mark_blocked("serienstream", "captcha_gate", "GATE_BLOCKED")
    assert status["state"] == COOLDOWN
    assert status["next_probe_at"] == clock.value + 900
    raw = json.loads((tmp_path / "health.json").read_text())
    assert raw["providers"]["serienstream"]["blocked_reason"] == "captcha_gate"


def test_cooldown_grows_after_repeated_probe_blocks(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    first = health.mark_blocked("serienstream", "captcha_gate")
    clock.value = first["next_probe_at"]
    assert health.begin_probe("serienstream")
    second = health.mark_blocked("serienstream", "captcha_gate")
    assert second["next_probe_at"] - clock.value == 1800
    clock.value = second["next_probe_at"]
    assert health.begin_probe("serienstream")
    third = health.mark_blocked("serienstream", "rate_limit")
    assert third["next_probe_at"] - clock.value == 3600


def test_cooldown_never_exceeds_maximum(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock, initial=10, maximum=40)
    for _ in range(8):
        status = health.mark_blocked("serienstream", "captcha_gate")
        assert status["next_probe_at"] - clock.value <= 40
        clock.value = status["next_probe_at"]
        assert health.begin_probe("serienstream")


def test_parallel_workers_receive_only_one_probe(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    blocked = health.mark_blocked("serienstream", "captcha_gate")
    clock.value = blocked["next_probe_at"]
    barrier = threading.Barrier(8)
    results = []

    def attempt():
        barrier.wait()
        results.append(health.begin_probe("serienstream"))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert health.status("serienstream")["state"] == PROBING


def test_successful_probe_restores_healthy(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    blocked = health.mark_blocked("serienstream", "captcha_gate")
    clock.value = blocked["next_probe_at"]
    assert health.begin_probe("serienstream")
    status = health.mark_success("serienstream")
    assert status["state"] == HEALTHY
    assert status["failure_count"] == 0
    assert health.request_allowed("serienstream")


def test_page_only_probe_keeps_backoff_history_until_redirect_success(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    blocked = health.mark_blocked("serienstream", "captcha_gate")
    clock.value = blocked["next_probe_at"]
    assert health.begin_probe("serienstream")
    health.mark_success("serienstream", reset_failures=False)
    second = health.mark_blocked("serienstream", "captcha_gate")
    assert second["next_probe_at"] - clock.value == 1800


def test_restart_keeps_cooldown_and_recovers_interrupted_probe(tmp_path):
    clock = Clock()
    health = manager(tmp_path, clock)
    blocked = health.mark_blocked("serienstream", "captcha_gate")
    restarted = manager(tmp_path, clock)
    assert restarted.status("serienstream")["next_probe_at"] == blocked["next_probe_at"]
    clock.value = blocked["next_probe_at"]
    assert restarted.begin_probe("serienstream")
    restarted_again = manager(tmp_path, clock)
    assert restarted_again.status("serienstream")["state"] == COOLDOWN
