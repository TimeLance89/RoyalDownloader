"""Independent runtime recovery, crash journal and no-loop regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from updates import recovery_journal as journal
from updates import runtime_guard as guard
from updates.runtime_release import (
    activate_release, read_release_link, releases_dir, rollback_release,
)


pytestmark = pytest.mark.skipif(os.name == "nt", reason="Docker runtime requires POSIX symlinks")


def release(root: Path, name: str, sha: str = "") -> Path:
    path = releases_dir(root) / name
    path.mkdir()
    (path / "server.py").write_text("pass\n", encoding="utf-8")
    if sha:
        (path / ".app_commit_sha").write_text(sha + "\n", encoding="utf-8")
    return path


def test_journal_records_intent_before_activation_and_confirms_exact_revision(tmp_path):
    old = release(tmp_path, "good", "a" * 40)
    new = release(tmp_path, "new", "b" * 40)
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)

    journal.stage_release(tmp_path, new, old)
    record = journal.read_journal(tmp_path)
    assert record["state"] == "pending"
    assert record["good"] == "good"
    assert record["pending"] == "new"
    assert (tmp_path / journal.JOURNAL_NAME).stat().st_mode & 0o777 == 0o600

    # An outdated health probe must not approve the candidate.
    journal.confirm_healthy(tmp_path, old)
    assert journal.read_journal(tmp_path)["state"] == "pending"
    journal.clear_interrupted_before_activation(tmp_path)
    assert journal.read_journal(tmp_path)["state"] == "idle"
    journal.stage_release(tmp_path, new, old)
    activate_release(tmp_path, new)
    journal.confirm_healthy(tmp_path, old)
    assert journal.read_journal(tmp_path)["state"] == "pending"
    assert journal.recovery_target(tmp_path) == old
    journal.confirm_healthy(tmp_path, new)
    assert journal.read_journal(tmp_path)["good"] == "new"
    assert journal.read_journal(tmp_path)["state"] == "idle"
    assert journal.recovery_target(tmp_path) is None


def test_failed_candidate_is_blocked_and_rollback_survives_restart(tmp_path):
    old = release(tmp_path, "good")
    new = release(tmp_path, "bad")
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)
    journal.stage_release(tmp_path, new, old)
    activate_release(tmp_path, new)
    journal.mark_failed(tmp_path, new, "startup_timeout")
    # Simulate a power loss after recording failure but before switching links.
    assert journal.recovery_target(tmp_path) == old
    assert rollback_release(tmp_path) == old
    assert journal.recovery_target(tmp_path) is None
    assert journal.read_journal(tmp_path)["blocked"] == "bad"
    with pytest.raises(RuntimeError, match="blocked"):
        journal.stage_release(tmp_path, new, old)
    assert read_release_link(tmp_path, "current") == old


def test_corrupt_journal_is_not_silently_discarded(tmp_path):
    (tmp_path / journal.JOURNAL_NAME).write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="trusted"):
        journal.read_journal(tmp_path)


def test_atomic_activation_interrupted_before_swap_preserves_good(tmp_path):
    old = release(tmp_path, "good")
    new = release(tmp_path, "candidate")
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)
    journal.stage_release(tmp_path, new, old)
    # Crash before current symlink replacement; old runtime still serves.
    assert read_release_link(tmp_path, "current") == old
    journal.confirm_healthy(tmp_path, old)
    assert journal.read_journal(tmp_path)["state"] == "pending"
    journal.clear_interrupted_before_activation(tmp_path)
    assert journal.read_journal(tmp_path)["state"] == "idle"
    journal.stage_release(tmp_path, new, old)


class FakeChild:
    def __init__(self, *, return_code=None):
        self.return_code = return_code
        self.terminated = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = -15

    def wait(self, timeout=None):
        return self.return_code

    def kill(self):
        self.terminated = True
        self.return_code = -9


def test_watchdog_recovers_bad_update_then_launches_good_once(monkeypatch, tmp_path):
    old = release(tmp_path, "good", "a" * 40)
    bad = release(tmp_path, "bad", "b" * 40)
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)
    journal.stage_release(tmp_path, bad, old)
    activate_release(tmp_path, bad)
    launched = []

    def launch(active, _bundle):
        launched.append(active)
        if active == bad:
            return FakeChild(return_code=2)
        return FakeChild()

    def sleep(_seconds):
        if launched[-1] == old:
            guard._stop = True

    monkeypatch.setattr(guard, "_launch", launch)
    monkeypatch.setattr(guard, "_healthy", lambda active: active == old)
    monkeypatch.setattr(guard.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(guard.time, "sleep", sleep)
    assert guard.supervise(tmp_path, tmp_path) == 0
    assert launched == [bad, old]
    assert read_release_link(tmp_path, "current") == old
    assert journal.read_journal(tmp_path)["blocked"] == "bad"


def test_watchdog_never_rolls_back_normal_shutdown_or_non_candidate(monkeypatch, tmp_path):
    old = release(tmp_path, "normal")
    activate_release(tmp_path, old)
    launched = []
    monkeypatch.setattr(guard, "_launch", lambda active, _bundle: launched.append(active) or FakeChild(return_code=8))
    monkeypatch.setattr(guard.signal, "signal", lambda *_args: None)
    assert guard.supervise(tmp_path, tmp_path) == 1
    assert launched == [old]
    assert read_release_link(tmp_path, "current") == old


def test_watchdog_uses_build_identity_not_generic_health(monkeypatch, tmp_path):
    candidate = release(tmp_path, "candidate", "e" * 40)
    monkeypatch.setattr(guard, "_request_json", lambda path: (
        {"status": "ok"} if path == "/api/health" else {"build": "f" * 12}
    ))
    assert guard._healthy(candidate) is False
    monkeypatch.setattr(guard, "_request_json", lambda path: (
        {"status": "ok"} if path == "/api/health" else {"build": "e" * 12}
    ))
    assert guard._healthy(candidate) is True


def test_watchdog_has_no_privileged_docker_socket_requirement():
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "docker.sock" not in source
    assert "subprocess.Popen" in source
    assert "rollback_release" in source


def test_failed_launch_recovers_previous_release_without_docker_socket(monkeypatch, tmp_path):
    old = release(tmp_path, "old")
    new = release(tmp_path, "new")
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)
    journal.stage_release(tmp_path, new, old)
    activate_release(tmp_path, new)
    launched = []

    def launch(active, _bundle):
        launched.append(active)
        if active == new:
            raise FileNotFoundError("simulated missing Python")
        return FakeChild()

    monkeypatch.setattr(guard, "_launch", launch)
    monkeypatch.setattr(guard, "_healthy", lambda active: active == old)
    monkeypatch.setattr(guard.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(guard.time, "sleep", lambda _s: setattr(guard, "_stop", True))
    assert guard.supervise(tmp_path, tmp_path) == 0
    assert launched == [new, old]
    assert journal.read_journal(tmp_path)["blocked"] == "new"


def test_guard_finishes_failed_power_loss_rollback_before_start(monkeypatch, tmp_path):
    old = release(tmp_path, "old")
    new = release(tmp_path, "new")
    activate_release(tmp_path, old)
    journal.confirm_healthy(tmp_path, old)
    journal.stage_release(tmp_path, new, old)
    activate_release(tmp_path, new)
    journal.mark_failed(tmp_path, new, "power_lost")
    launched = []

    monkeypatch.setattr(guard, "_launch", lambda active, _bundle: launched.append(active) or FakeChild())
    monkeypatch.setattr(guard, "_healthy", lambda active: active == old)
    monkeypatch.setattr(guard.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(guard.time, "sleep", lambda _s: setattr(guard, "_stop", True))
    assert guard.supervise(tmp_path, tmp_path) == 0
    assert launched == [old]
    assert read_release_link(tmp_path, "current") == old


def test_readiness_transport_is_loopback_only_and_never_uses_proxy(monkeypatch):
    connections = []

    class LocalResponse:
        status = 200

        def read(self, limit):
            assert limit == 2048
            return b'{"status":"ok"}'

    class LocalConnection:
        def __init__(self, host, port, timeout):
            connections.append((host, port, timeout))
            assert (host, port, timeout) == ("127.0.0.1", 8765, 2)

        def request(self, method, endpoint, headers):
            assert (method, endpoint) == ("GET", "/api/health")
            assert headers["Host"] == "127.0.0.1:8765"

        def getresponse(self):
            return LocalResponse()

        def close(self):
            pass

    monkeypatch.setattr(guard.http.client, "HTTPConnection", LocalConnection)
    assert guard._request_json("https://example.com/steal") is None
    assert not connections
    assert guard._request_json("/api/health") == {"status": "ok"}
    assert connections == [("127.0.0.1", 8765, 2)]
