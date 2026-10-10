"""Crash recovery and loss-prevention tests for durable download queue state."""

from __future__ import annotations

import json
import os

import pytest

from core import config, queue_jobs


def _document(slug: str, revision: int) -> dict:
    return {
        "schema_version": queue_jobs.SCHEMA_VERSION,
        "revision": revision,
        "jobs": [queue_jobs.new_job(slug, job_id="fixed-" + slug)],
        "history": [],
    }


def test_previous_verified_snapshot_is_preserved_before_each_replace(tmp_path):
    path = tmp_path / "download_queue.json"
    first = _document("provider:first", 1)
    second = _document("provider:second", 2)
    queue_jobs.atomic_save(path, first)
    original = path.read_bytes()
    assert queue_jobs._backup_path(path).read_bytes() == original

    queue_jobs.atomic_save(path, second)

    backup = queue_jobs._backup_path(path)
    assert backup.read_bytes() == original
    assert json.loads(path.read_text())["revision"] == 2
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert backup.stat().st_mode & 0o777 == 0o600


def test_corrupted_primary_recovers_job_identity_from_verified_backup(tmp_path):
    path = tmp_path / "download_queue.json"
    old = _document("provider:episode-s01e03", 3)
    recent = _document("provider:episode-s01e04", 4)
    queue_jobs.atomic_save(path, old)
    queue_jobs.atomic_save(path, recent)
    backup_before = queue_jobs._backup_path(path).read_bytes()
    path.write_text("{partial:bad", encoding="utf-8")

    restored, migrated = queue_jobs.load_document(path)

    assert migrated is True
    assert restored["revision"] == 3
    assert restored["jobs"][0]["job_id"] == "fixed-provider:episode-s01e03"
    assert restored["jobs"][0]["slug"] == "provider:episode-s01e03"
    assert path.read_bytes() == backup_before


def test_missing_primary_recovers_from_backup_without_changing_id(tmp_path):
    path = tmp_path / "download_queue.json"
    queue_jobs.atomic_save(path, _document("provider:stable", 7))
    path.unlink()
    document, migrated = queue_jobs.load_document(path)
    assert migrated is True
    assert document["revision"] == 7
    assert document["jobs"][0]["job_id"] == "fixed-provider:stable"
    assert path.is_file()


@pytest.mark.parametrize("broken", [
    b"{invalid JSON",
    b'{"jobs":"not a list","history":[]}',
    b'{"jobs":[{"status":"downloading"}],"history":[]}',
    b"null",
    b'["valid", 7]',
])
def test_unrecoverable_snapshot_never_returns_an_empty_queue(tmp_path, broken):
    path = tmp_path / "download_queue.json"
    path.write_bytes(broken)
    original = path.read_bytes()
    with pytest.raises((RuntimeError, ValueError)):
        queue_jobs.load_document(path)
    assert path.read_bytes() == original
    assert not queue_jobs._backup_path(path).exists()


def test_corrupted_primary_and_backup_fail_closed_without_overwriting_either(tmp_path):
    path = tmp_path / "download_queue.json"
    queue_jobs.atomic_save(path, _document("provider:keep", 1))
    backup = queue_jobs._backup_path(path)
    path.write_text("garbled-primary", encoding="utf-8")
    backup.write_text("garbled-backup", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Sicherung"):
        queue_jobs.load_document(path)
    assert path.read_text() == "garbled-primary"
    assert backup.read_text() == "garbled-backup"


def test_broken_snapshot_is_not_overwritten_by_new_queue(tmp_path):
    path = tmp_path / "download_queue.json"
    queue_jobs.atomic_save(path, _document("provider:keep", 1))
    path.write_bytes(b"garbled-primary")
    backup_before = queue_jobs._backup_path(path).read_bytes()
    with pytest.raises(ValueError):
        queue_jobs.atomic_save(path, _document("provider:other", 2))
    assert path.read_bytes() == b"garbled-primary"
    assert queue_jobs._backup_path(path).read_bytes() == backup_before


def test_power_loss_during_primary_swap_keeps_old_queue_and_valid_backup(tmp_path, monkeypatch):
    path = tmp_path / "download_queue.json"
    queue_jobs.atomic_save(path, _document("provider:stable", 10))
    original = path.read_bytes()
    replace = queue_jobs.os.replace

    def fail_primary(source, destination):
        if destination == path:
            raise OSError("simulated power loss")
        return replace(source, destination)

    monkeypatch.setattr(queue_jobs.os, "replace", fail_primary)
    with pytest.raises(OSError, match="power loss"):
        queue_jobs.atomic_save(path, _document("provider:next", 11))
    assert path.read_bytes() == original
    assert queue_jobs._backup_path(path).read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_core_config_queue_load_propagates_unrecoverable_corruption(monkeypatch, tmp_path):
    path = tmp_path / "download_queue.json"
    path.write_bytes(b"invalid-primary")
    monkeypatch.setattr(config, "_queue_file", lambda: path)
    with pytest.raises(RuntimeError, match="nicht wiederherstellbar"):
        config.load_queue_state()
    assert path.read_bytes() == b"invalid-primary"


def test_legacy_slug_list_still_migrates_and_survives_backup(tmp_path):
    path = tmp_path / "download_queue.json"
    path.write_text(json.dumps(["provider:one", "provider:show-s01e02"]), encoding="utf-8")
    document, migrated = queue_jobs.load_document(path)
    assert migrated is True
    queue_jobs.atomic_save(path, document)
    assert len(queue_jobs.load_document(path)[0]["jobs"]) == 2
    path.write_text("bad", encoding="utf-8")
    recovered, _ = queue_jobs.load_document(path)
    assert {j["slug"] for j in recovered["jobs"]} == {
        "provider:one", "provider:show-s01e02",
    }


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink privileges vary")
def test_queue_refuses_symlink_backup_instead_of_following_untrusted_path(tmp_path):
    path = tmp_path / "download_queue.json"
    target = tmp_path / "outside.json"
    target.write_text('{"jobs":[],"history":[]}', encoding="utf-8")
    queue_jobs._backup_path(path).symlink_to(target)
    with pytest.raises(RuntimeError, match="Symlink"):
        queue_jobs.atomic_save(path, _document("provider:one", 1))
    assert target.read_text() == '{"jobs":[],"history":[]}'
