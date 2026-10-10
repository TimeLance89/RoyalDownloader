"""Crash-durable state for the existing versioned runtime updater.

Only public release names and brief error codes are persisted, never credentials
or user data. This module is shipped by the immutable Docker bundle, so a bad
application release cannot remove the recovery metadata implementation.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from updates.runtime_release import read_release_link

JOURNAL_NAME = ".update-recovery.json"
RELEASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
STATES = {"idle", "pending", "failed"}


def _release_name(release: Path | None) -> str:
    if release is None:
        return ""
    name = Path(release).name
    if not RELEASE_NAME.fullmatch(name):
        raise ValueError("Invalid runtime release name")
    return name


def _blank() -> dict:
    return {"schema": 1, "state": "idle", "good": "", "pending": "",
            "blocked": "", "reason": ""}


def read_journal(root: Path) -> dict:
    path = Path(root) / JOURNAL_NAME
    if not path.exists():
        return _blank()
    try:
        if path.stat().st_size > 8192 or path.is_symlink():
            raise ValueError("Untrusted recovery journal")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            raise ValueError("Invalid journal schema")
        result = _blank()
        if payload.get("state") not in STATES:
            raise ValueError("Invalid journal state")
        result["state"] = payload["state"]
        for key in ("good", "pending", "blocked"):
            value = payload.get(key, "")
            if not isinstance(value, str) or (value and not RELEASE_NAME.fullmatch(value)):
                raise ValueError("Invalid journal release")
            result[key] = value
        reason = payload.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("Invalid failure reason")
        result["reason"] = reason[:160]
        if result["state"] == "pending" and not (result["good"] and result["pending"]):
            raise ValueError("Incomplete pending transition")
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # Never overwrite a damaged recovery record. The operator must
        # inspect it, rather than letting an uncertain transition continue.
        raise RuntimeError("Recovery journal could not be trusted") from exc


def _save(root: Path, record: dict) -> None:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = root / JOURNAL_NAME
    fd, name = tempfile.mkstemp(prefix=".recovery-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600) if hasattr(os, "fchmod") else None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name == "posix":
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def stage_release(root: Path, new: Path, old: Path | None) -> None:
    """Write recovery intent *before* changing the current symlink."""
    new_name = _release_name(new)
    old_name = _release_name(old)
    if not old_name or old_name == new_name:
        return
    state = read_journal(root)
    if state["state"] == "pending":
        # An earlier unconfirmed activation must be resolved first.
        raise RuntimeError("Previous update has not passed its startup check")
    if state["blocked"] == new_name:
        raise RuntimeError("Release is blocked after failed startup")
    state.update(state="pending", good=old_name, pending=new_name, reason="")
    _save(root, state)


def abort_staging(root: Path, new: Path) -> None:
    state = read_journal(root)
    if state["state"] == "pending" and state["pending"] == _release_name(new):
        state.update(state="idle", pending="", reason="")
        _save(root, state)


def confirm_healthy(root: Path, release: Path) -> None:
    current = read_release_link(root, "current")
    if current != Path(release).resolve():
        return
    name = _release_name(release)
    state = read_journal(root)
    if state["state"] == "pending" and state["pending"] != name:
        # Never clear intent here: an installer may be between journal fsync
        # and symlink activation while the old server is still healthy.
        return
    if state["state"] != "pending" and state["good"] == name:
        return
    state.update(state="idle", good=name, pending="", reason="")
    _save(root, state)


def clear_interrupted_before_activation(root: Path) -> None:
    """Boot-only recovery when power failed before the current link changed."""
    state = read_journal(root)
    current = read_release_link(root, "current")
    if (state["state"] == "pending" and current is not None
            and current.name == state["good"]):
        state.update(state="idle", pending="", reason="")
        _save(root, state)


def mark_failed(root: Path, release: Path, reason: str) -> None:
    state = read_journal(root)
    if state["state"] != "pending" or state["pending"] != _release_name(release):
        raise RuntimeError("Not a pending runtime activation")
    state.update(state="failed", blocked=state["pending"], pending="",
                 reason=reason[:160])
    _save(root, state)


def recovery_target(root: Path) -> Path | None:
    state = read_journal(root)
    current = read_release_link(root, "current")
    previous = read_release_link(root, "previous")
    if (state["state"] not in {"pending", "failed"} or current is None or previous is None
            or current.name != (state["pending"] if state["state"] == "pending" else state["blocked"])
            or previous.name != state["good"]):
        return None
    return previous
