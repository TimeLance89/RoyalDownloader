from pathlib import Path

import pytest

import runtime_release
from self_updater import SelfUpdater


def _release(root: Path, name: str, dependency: str) -> Path:
    release = runtime_release.releases_dir(root) / name
    release.mkdir()
    (release / "server.py").write_text("# server\n", encoding="utf-8")
    (release / "dependency-version").write_text(dependency, encoding="utf-8")
    return release


def test_atomic_activation_and_complete_rollback(tmp_path):
    old = _release(tmp_path, "old", "v1")
    new = _release(tmp_path, "new", "v2")
    runtime_release.activate_release(tmp_path, old)
    runtime_release.activate_release(tmp_path, new)
    assert runtime_release.read_release_link(tmp_path, "current") == new
    assert runtime_release.read_release_link(tmp_path, "previous") == old

    restored = runtime_release.rollback_release(tmp_path)
    assert restored == old
    assert (runtime_release.read_release_link(tmp_path, "current") / "dependency-version").read_text() == "v1"
    assert runtime_release.read_release_link(tmp_path, "previous") == new


def test_interrupted_link_replace_keeps_old_runtime(monkeypatch, tmp_path):
    old = _release(tmp_path, "old", "v1")
    new = _release(tmp_path, "new", "v2")
    runtime_release.activate_release(tmp_path, old)
    real_replace = runtime_release.os.replace

    def fail_current(source, destination):
        if Path(destination).name == "current":
            raise OSError("simulated power loss")
        return real_replace(source, destination)

    monkeypatch.setattr(runtime_release.os, "replace", fail_current)
    with pytest.raises(OSError, match="power loss"):
        runtime_release.activate_release(tmp_path, new)
    assert runtime_release.read_release_link(tmp_path, "current") == old


def test_failed_staged_smoke_never_changes_current(monkeypatch, tmp_path):
    old = _release(tmp_path, "old", "v1")
    runtime_release.activate_release(tmp_path, old)
    source = tmp_path / "source"
    source.mkdir()
    (source / "server.py").write_text("# new\n", encoding="utf-8")
    (source / "requirements.txt").write_text("example==2\n", encoding="utf-8")
    updater = SelfUpdater("owner/repo", old, persistent_override=True)

    def fake_dependencies(staging):
        python = staging / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
        return python

    monkeypatch.setattr(updater, "_install_release_dependencies", fake_dependencies)
    monkeypatch.setattr(updater, "_repair_nodriver", lambda *_args: None)
    monkeypatch.setattr(
        updater, "_smoke_release",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("bad import")),
    )
    with pytest.raises(RuntimeError, match="bad import"):
        updater._install_versioned(source, "a" * 40, tmp_path)
    assert runtime_release.read_release_link(tmp_path, "current") == old
    assert not list(runtime_release.releases_dir(tmp_path).glob(".staging-*"))
    assert not (runtime_release.releases_dir(tmp_path) / ("a" * 12)).exists()


def test_verified_staged_release_is_activated_once(monkeypatch, tmp_path):
    old = _release(tmp_path, "old", "v1")
    runtime_release.activate_release(tmp_path, old)
    source = tmp_path / "source"
    source.mkdir()
    (source / "server.py").write_text("# new\n", encoding="utf-8")
    (source / "requirements.txt").write_text("example==2\n", encoding="utf-8")
    updater = SelfUpdater("owner/repo", old, persistent_override=True)

    def fake_dependencies(staging):
        python = staging / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
        (staging / "dependency-version").write_text("v2", encoding="utf-8")
        return python

    monkeypatch.setattr(updater, "_install_release_dependencies", fake_dependencies)
    monkeypatch.setattr(updater, "_repair_nodriver", lambda *_args: None)
    monkeypatch.setattr(updater, "_smoke_release", lambda *_args: None)
    updater._install_versioned(source, "b" * 40, tmp_path)

    current = runtime_release.read_release_link(tmp_path, "current")
    assert current and current.name == "b" * 12
    assert (current / "dependency-version").read_text() == "v2"
    assert runtime_release.read_release_link(tmp_path, "previous") == old
