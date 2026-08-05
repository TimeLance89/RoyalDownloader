from pathlib import Path
import os

import pytest

import container_entrypoint


ROOT = Path(__file__).resolve().parents[1]
requires_posix = pytest.mark.skipif(os.name != "posix", reason="requires POSIX user IDs")


def test_image_and_compose_run_unprivileged_with_reduced_privileges():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "USER royal" in dockerfile
    assert "--no-sandbox" not in dockerfile
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "APP_UID: ${PUID:-1000}" in compose
    assert "APP_GID: ${PGID:-1000}" in compose


@requires_posix
def test_smoke_check_writes_only_required_mounts(monkeypatch, tmp_path):
    for name in ("runtime", "data", "movies", "series"):
        monkeypatch.setenv(
            {
                "runtime": "APP_RUNTIME_DIR",
                "data": "SERIENDL_DATA_DIR",
                "movies": "DOWNLOAD_DIR",
                "series": "SERIES_DIR",
            }[name],
            str(tmp_path / name),
        )
    monkeypatch.setattr(container_entrypoint.os, "getuid", lambda: 1000)
    container_entrypoint.smoke_check()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data", "movies", "runtime", "series"]


@requires_posix
def test_smoke_check_rejects_root(monkeypatch):
    monkeypatch.setattr(container_entrypoint.os, "getuid", lambda: 0)
    try:
        container_entrypoint.smoke_check()
    except RuntimeError as exc:
        assert "nicht als root" in str(exc)
    else:
        raise AssertionError("root runtime was accepted")
