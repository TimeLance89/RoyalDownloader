import hashlib
from pathlib import Path

import pytest

from ytdlp_updater import YtDlpRuntimeUpdater

ROOT = Path(__file__).resolve().parents[1]


def _content(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_dependencies_and_images_are_exactly_pinned():
    direct = [
        line for line in _content("requirements.in").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    locked = [
        line for line in _content("requirements.lock").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert all("==" in line for line in direct)
    assert all("==" in line for line in locked)

    dockerfile = _content("Dockerfile")
    compose = _content("docker-compose.yml")
    assert "FROM python:3.12.13-slim-bookworm" in dockerfile
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile
    assert "SEERR_IMAGE_TAG:-v3.4.1" in compose
    assert "SEERR_IMAGE_TAG:-latest" not in compose
    assert "YTDLP_AUTO_UPDATE:-false" in compose


def test_release_gate_dependencies_are_locked_and_kept_out_of_runtime_image():
    gate_dockerfile = _content("Dockerfile.release-gate")
    workflow = _content(".github/workflows/quality.yml")

    assert "requirements-dev.lock" in gate_dockerfile
    assert "royal-downloader:quality" in gate_dockerfile
    assert "royal-downloader:release-gate" in workflow
    assert "pip-audit -r requirements-dev.lock" in workflow
    assert "requirements-dev.lock" not in _content("Dockerfile")


def test_container_browser_uses_signed_patched_source_and_fails_closed():
    dockerfile = _content("Dockerfile")
    assert 'ARG CHROME_SECURITY_FLOOR="151.0.7922.169-1"' in dockerfile
    assert 'ARG DEBIAN_CHROMIUM_SECURITY_FLOOR="151.0.7922.169-1~deb12u1"' in dockerfile
    assert "https://dl.google.com/linux/linux_signing_key.pub" in dockerfile
    assert "signed-by=/usr/share/keyrings/google-chrome.asc" in dockerfile
    assert "https://dl.google.com/linux/chrome/deb/ stable main" in dockerfile
    assert 'dpkg --compare-versions "${chrome_version}" ge "${CHROME_SECURITY_FLOOR}"' in dockerfile
    assert 'dpkg --compare-versions "${chromium_version}" ge "${DEBIAN_CHROMIUM_SECURITY_FLOOR}"' in dockerfile
    assert 'dpkg --compare-versions "${chromium_common_version}" ge "${DEBIAN_CHROMIUM_SECURITY_FLOOR}"' in dockerfile
    assert "CHROME_PATH=/usr/local/bin/royal-chrome" in dockerfile
    assert "ln -sfn /usr/local/bin/royal-chrome /usr/local/bin/chromium" in dockerfile


def test_legacy_updater_dependency_sentinel_stays_compatible():
    # Version 6457b78d compares this file byte-for-byte before accepting an
    # update. Runtime dependency changes belong in requirements.in/.lock.
    assert _content("requirements.txt") == (
        "curl_cffi\n"
        "nodriver==0.50.3\n"
        "beautifulsoup4\n"
        "lxml\n"
        "yt-dlp\n"
        "fastapi\n"
        "uvicorn[standard]\n"
        "requests>=2.32,<3\n"
        "cryptography>=45,<49\n"
    )


def test_update_and_native_start_install_from_lock():
    assert "requirements.lock" in _content("self_updater.py")
    assert '"app_version.py"' in _content("self_updater.py")
    assert '"update_channels.py"' in _content("self_updater.py")
    assert '"application_services/runtime.py"' in _content("self_updater.py")
    assert "self_updater, server" in _content("self_updater.py")
    assert "-r requirements.lock" in _content("start.sh")
    assert 'APP_RUNTIME_DIR="${APP_RUNTIME_DIR:-$(pwd)/runtime}"' in _content("start.sh")
    assert "exec python docker_bootstrap.py" in _content("start.sh")


def test_runtime_revision_comes_from_active_release_not_stale_image_environment():
    dockerfile = _content("Dockerfile")
    runtime_section = dockerfile.split("FROM runtime-base AS runtime", 1)[1]
    assert "APP_COMMIT_SHA=${APP_COMMIT_SHA}" not in runtime_section


def test_docker_context_excludes_local_media_and_workspace_artifacts():
    dockerignore = _content(".dockerignore")
    for excluded in (
        "Filme/", "Serien/", ".downloading/", ".agents/", "[#]recycle/",
        ".nas-update-staging.*",
    ):
        assert excluded in dockerignore


def test_ytdlp_wheel_requires_an_approved_hash(tmp_path, monkeypatch):
    updater = YtDlpRuntimeUpdater()
    payload = b"verified wheel"

    def fake_pip(_arguments, timeout):
        assert timeout == 300
        (tmp_path / "yt_dlp-2026.7.4-py3-none-any.whl").write_bytes(payload)

    monkeypatch.setattr(updater, "_run_pip", fake_pip)
    digest = hashlib.sha256(payload).hexdigest()
    wheel = updater.download_wheel("2026.7.4", tmp_path, [digest])
    assert wheel.is_file()

    wheel.unlink()
    with pytest.raises(RuntimeError, match="PyPI-Hash"):
        updater.download_wheel("2026.7.4", tmp_path, ["0" * 64])
