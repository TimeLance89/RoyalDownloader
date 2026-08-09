import os
from pathlib import Path

from environment_file import load_project_env, read_env, write_project_env


def test_setup_creates_env_from_example_and_applies_desktop_mode(tmp_path: Path):
    example = tmp_path / ".env.example"
    target = tmp_path / ".env"
    example.write_text("KEEP_ME=yes\nHOST=0.0.0.0\nOPEN_BROWSER=0\n", encoding="utf-8")

    result = write_project_env(
        "desktop", r"C:\Media\Filme", r"C:\Media\Serien",
        path=target, example_path=example,
    )

    values = read_env(target)
    assert result["created"] is True
    assert values["KEEP_ME"] == "yes"
    assert values["ROYAL_DEPLOYMENT_MODE"] == "desktop"
    assert values["HOST"] == "127.0.0.1"
    assert values["OPEN_BROWSER"] == "1"
    assert values["DOWNLOAD_DIR"] == r"C:\Media\Filme"


def test_existing_env_keeps_unknown_values_when_switching_to_nas(tmp_path: Path):
    example = tmp_path / ".env.example"
    target = tmp_path / ".env"
    example.write_text("UNUSED=template\n", encoding="utf-8")
    target.write_text("PRIVATE_TOKEN=secret\nROYAL_DEPLOYMENT_MODE=desktop\n", encoding="utf-8")

    result = write_project_env(
        "nas", "/volume/media/Filme", "/volume/media/Serien",
        path=target, example_path=example,
    )

    values = read_env(target)
    assert result["created"] is False
    assert values["PRIVATE_TOKEN"] == "secret"
    assert values["ROYAL_DEPLOYMENT_MODE"] == "nas"
    assert values["HOST"] == "0.0.0.0"
    assert values["OPEN_BROWSER"] == "0"


def test_project_env_replaces_empty_container_placeholder(monkeypatch, tmp_path: Path):
    target = tmp_path / ".env"
    target.write_text("UPDATE_GITHUB_TOKEN=configured-token\n", encoding="utf-8")
    monkeypatch.setenv("UPDATE_GITHUB_TOKEN", "")

    load_project_env(target)

    assert os.environ["UPDATE_GITHUB_TOKEN"] == "configured-token"
