from pathlib import Path

import pytest
from fastapi import HTTPException

import config
import runtime_paths
import server


def test_container_path_requires_a_non_ephemeral_mount(monkeypatch):
    mountinfo = (
        "1 0 0:1 / / rw - overlay overlay rw\n"
        "2 1 0:2 /nas/series /serien rw - ext4 /dev/sda rw\n"
        "3 1 0:3 / /tmp rw - tmpfs tmpfs rw\n"
    )
    monkeypatch.setattr(runtime_paths, "in_container", lambda: True)
    original_read_text = runtime_paths.Path.read_text

    def fake_read_text(path, *args, **kwargs):
        if str(path) == "/proc/self/mountinfo":
            return mountinfo
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(runtime_paths.Path, "read_text", fake_read_text)

    assert runtime_paths.persistent_container_path(Path("/serien/Show"))
    assert not runtime_paths.persistent_container_path(Path("/volume1/Show"))
    assert not runtime_paths.persistent_container_path(Path("/tmp/Show"))


def test_config_replaces_unsafe_saved_path_with_docker_mount(monkeypatch):
    monkeypatch.setattr(config, "_read_all", lambda: {
        "save_path": "/volume1/Filme",
        "series_path": "/volume1/Serien",
    })
    monkeypatch.setattr(config, "in_container", lambda: True)
    monkeypatch.setenv("DOWNLOAD_DIR", "/movies")
    monkeypatch.setenv("SERIES_DIR", "/serien")
    monkeypatch.setattr(
        config, "persistent_container_path",
        lambda path: str(path) in {"/movies", "/serien"},
    )

    assert config.load() == "/movies"
    assert config.load_series_path() == "/serien"
    assert config.media_path_corrections() == [
        ("Filme", "/volume1/Filme", "/movies"),
        ("Serien", "/volume1/Serien", "/serien"),
    ]


def test_misplaced_episode_is_copied_to_series_mount_without_deleting_source(
    monkeypatch, tmp_path,
):
    source = tmp_path / "container-layer"
    target = tmp_path / "series-mount"
    episode = source / "Kap der Angst" / "Staffel 01" / "Kap.der.Angst.S01E03.mp4"
    movie = source / "A Movie.mp4"
    episode.parent.mkdir(parents=True)
    episode.write_bytes(b"episode")
    movie.write_bytes(b"movie")
    target.mkdir()
    monkeypatch.setattr(
        server, "persistent_container_path",
        lambda path: Path(path).resolve(strict=False) == target.resolve(strict=False),
    )

    result = server._recover_misplaced_media("Serien", str(source), str(target))

    recovered = target / episode.relative_to(source)
    assert recovered.read_bytes() == b"episode"
    assert episode.read_bytes() == b"episode"
    assert not (target / movie.name).exists()
    assert result["copied"] == 1
    assert result["errors"] == []


def test_settings_reject_ephemeral_container_media_path(monkeypatch):
    monkeypatch.setattr(server, "in_container", lambda: True)
    monkeypatch.setattr(server, "persistent_container_path", lambda _path: False)
    monkeypatch.setenv("SERIES_DIR", "/serien")

    with pytest.raises(HTTPException, match="persistenten Docker-Mount"):
        server._prepare_media_directory("/volume1/Serien", "Serienordner")
