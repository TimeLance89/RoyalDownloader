from pathlib import Path
import os

import pytest

import docker_bootstrap
import runtime_release
from self_updater import SelfUpdater


requires_directory_symlinks = pytest.mark.skipif(
    os.name == "nt",
    reason="versioned Docker runtime uses POSIX directory symlinks",
)


def _release(root: Path, name: str, dependency: str) -> Path:
    release = runtime_release.releases_dir(root) / name
    release.mkdir()
    (release / "server.py").write_text("# server\n", encoding="utf-8")
    (release / "dependency-version").write_text(dependency, encoding="utf-8")
    return release


@requires_directory_symlinks
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


def test_prune_releases_keeps_active_and_previous(monkeypatch, tmp_path):
    old = _release(tmp_path, "old", "v1")
    current = _release(tmp_path, "current-build", "v2")
    stale = _release(tmp_path, "stale", "v0")
    monkeypatch.setattr(
        runtime_release,
        "read_release_link",
        lambda _root, name: current if name == "current" else old if name == "previous" else None,
    )

    assert runtime_release.prune_releases(tmp_path) == [stale]
    assert old.is_dir() and current.is_dir()
    assert not stale.exists()


def test_prune_releases_dry_run_does_not_delete(tmp_path):
    for name in ("one", "two", "three"):
        _release(tmp_path, name, name)

    removed = runtime_release.prune_releases(tmp_path, dry_run=True)

    assert len(removed) == 1
    assert all((runtime_release.releases_dir(tmp_path) / name).exists() for name in ("one", "two", "three"))


@requires_directory_symlinks
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


@requires_directory_symlinks
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


@requires_directory_symlinks
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


def test_unmarked_bundle_identity_changes_with_source(tmp_path):
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "server.py").write_text("# first\n", encoding="utf-8")
    first = docker_bootstrap._source_identity(source)
    (source / "server.py").write_text("# second\n", encoding="utf-8")
    second = docker_bootstrap._source_identity(source)
    assert second != first

    # Persistent and generated content must not create phantom releases.
    (source / "data").mkdir()
    (source / "data/state.json").write_text("changed", encoding="utf-8")
    assert docker_bootstrap._source_identity(source) == second


def test_legacy_runtime_copy_skips_transient_content(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "release"
    source.mkdir()
    (source / "server.py").write_text("# server\n", encoding="utf-8")
    for name in (".downloading", "#recycle", "__pycache__"):
        folder = source / name
        folder.mkdir()
        (folder / "generated-file").write_text("not source", encoding="utf-8")

    docker_bootstrap._copy_source(source, destination)

    assert (destination / "server.py").is_file()
    assert all(not (destination / name).exists() for name in (".downloading", "#recycle", "__pycache__"))
