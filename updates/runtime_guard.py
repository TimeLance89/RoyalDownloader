"""Independent Docker bootstrap watchdog for versioned Royal runtimes.

Executed from the immutable image bundle, outside the updated application
release. The application remains a child process, including when it re-execs
the bootstrap after an in-app update. No Docker socket or root privileges.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from updates.recovery_journal import (
    clear_interrupted_before_activation, confirm_healthy, mark_failed,
    read_journal, recovery_target,
)
from updates.runtime_release import read_release_link, rollback_release

CHILD_MARKER = "ROYAL_GUARD_CHILD"
START_TIMEOUT_SECONDS = 120
POLL_SECONDS = 1
_stop = False
_child: subprocess.Popen | None = None


def _timeout() -> int:
    try:
        return max(30, min(600, int(os.getenv("ROYAL_STARTUP_TIMEOUT_SECONDS", "120"))))
    except ValueError:
        return START_TIMEOUT_SECONDS


def _terminate_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def _on_signal(_signal, _frame) -> None:
    global _stop
    _stop = True
    if _child is not None:
        _child.terminate()


def _request_json(endpoint: str) -> dict | None:
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8765" + endpoint,
            headers={"Host": "127.0.0.1:8765"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            if response.status != 200:
                return None
            return json.loads(response.read(2048))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _healthy(release: Path) -> bool:
    health = _request_json("/api/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        return False
    capabilities = _request_json("/api/v1/capabilities")
    if not isinstance(capabilities, dict):
        return False
    try:
        expected = (release / ".app_commit_sha").read_text(encoding="utf-8").strip()
    except OSError:
        expected = ""
    actual = str(capabilities.get("build") or "")
    # Versioned GitHub releases must match the executing process, not merely
    # an old instance that is still serving the generic health endpoint.
    if expected and (not actual or not expected.lower().startswith(actual.lower())):
        return False
    return True


def _launch(release: Path, bundle: Path) -> subprocess.Popen:
    python = release / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = os.environ.copy()
    env[CHILD_MARKER] = "1"
    env["APP_SOURCE_DIR"] = str(bundle)
    env["APP_ACTIVE_RELEASE"] = str(release)
    env["APP_BASE_PYTHON"] = sys.executable
    env["APP_BOOTSTRAP_PATH"] = str(bundle / "container_entrypoint.py")
    return subprocess.Popen(
        [str(python), str(release / "server.py")],
        cwd=release,
        env=env,
    )


def supervise(runtime_root: Path, bundle: Path) -> int:
    """Start, monitor and if necessary restore exactly one failed candidate."""
    global _child, _stop
    runtime_root = Path(runtime_root).resolve()
    bundle = Path(bundle).resolve()
    restored = False
    active = read_release_link(runtime_root, "current")
    if active is None:
        raise RuntimeError("No validated current runtime")
    clear_interrupted_before_activation(runtime_root)
    # Power loss after recording a failed start but before changing the
    # symlink: complete the same one-time rollback before launching anything.
    record = read_journal(runtime_root)
    if record["state"] == "failed":
        target = recovery_target(runtime_root)
        if target is not None:
            restored = rollback_release(runtime_root)
            if restored != target:
                raise RuntimeError("Interrupted rollback target mismatch")
            print(f"[guard] Completed interrupted rollback to {target.name}", flush=True)
            active = target
    _stop = False
    timeout = _timeout()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _on_signal)

    while not _stop:
        current = read_release_link(runtime_root, "current")
        if current is None:
            raise RuntimeError("Current runtime symlink disappeared")
        active = current
        print(f"[guard] Starting runtime {active.name}", flush=True)
        try:
            child = _launch(active, bundle)
        except OSError:
            child = None
        _child = child
        deadline = time.monotonic() + timeout
        ready = False
        reason = "server_launch_failed" if child is None else ""

        while not _stop:
            if child is None:
                break
            current = read_release_link(runtime_root, "current")
            if current is None:
                reason = "active_runtime_missing"
                break
            if current != active:
                active = current
                ready = False
                deadline = time.monotonic() + timeout
                print(f"[guard] Awaiting activated runtime {active.name}", flush=True)

            exit_code = child.poll()
            if exit_code is not None:
                reason = f"server_exit_{exit_code}"
                break

            if not ready and _healthy(active):
                if read_release_link(runtime_root, "current") == active:
                    confirm_healthy(runtime_root, active)
                    ready = True
                    print(f"[guard] Runtime healthy: {active.name}", flush=True)
            if not ready and time.monotonic() >= deadline:
                reason = "startup_timeout"
                break
            time.sleep(POLL_SECONDS)

        if _stop:
            if child is not None:
                _terminate_child(child)
            return 0
        target = recovery_target(runtime_root)
        if restored or target is None or read_release_link(runtime_root, "current") != active:
            if child is not None:
                _terminate_child(child)
            print(f"[guard] Runtime stopped without recoverable update: {reason}", flush=True)
            return 1

        print(f"[guard] Update failed ({reason}); restoring {target.name}", flush=True)
        # Persist the blocked candidate *before* swapping links, so a power
        # loss between these operations can resume recovery at next boot.
        record = read_journal(runtime_root)
        if record["state"] == "pending":
            mark_failed(runtime_root, active, reason)
        if child is not None:
            _terminate_child(child)
        if read_release_link(runtime_root, "current") != active:
            return 1
        restored_release = rollback_release(runtime_root)
        if restored_release != target:
            raise RuntimeError("Rollback target no longer matches journal")
        restored = True
        # Loop launches only the old, known-good release; no oscillation.
    return 0


def main() -> None:
    runtime_root = Path(os.environ["APP_RUNTIME_DIR"])
    bundle = Path(os.environ.get("APP_SOURCE_DIR") or Path(__file__).resolve().parents[1])
    sys.exit(supervise(runtime_root, bundle))


if __name__ == "__main__":
    main()
