import asyncio
from pathlib import Path

import api_administration_router as administration
import config as appconfig
from downloader import DownloadJob


def test_demo_configuration_is_initialized_without_media_paths(monkeypatch, tmp_path: Path):
    config_file = tmp_path / "settings.ini"
    config_file.write_text(
        "deployment_mode = demo\nsave_path =\nseries_path =\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(appconfig, "_config_file", lambda: config_file)
    monkeypatch.setattr(appconfig, "_config_dir", lambda: tmp_path)

    assert appconfig.is_initialized() is True
    assert appconfig.demo_mode_enabled() is True
    assert appconfig.load() == str(tmp_path / "demo-output" / "Filme")
    assert appconfig.load_series_path() == str(tmp_path / "demo-output" / "Serien")
    assert not (tmp_path / "demo-output").exists()


def test_demo_download_runs_without_network_or_files(tmp_path: Path):
    events = []
    target = tmp_path / "media" / "Film.2026.mp4"
    job = DownloadJob(
        "https://invalid.example/video.mp4",
        "mp4",
        target,
        demo_mode=True,
        demo_step_delay=0,
        on_start=lambda: events.append(("start", None)),
        on_progress=lambda pct, msg: events.append((pct, msg)),
        on_done=lambda ok, msg: events.append((ok, msg)),
    )

    job._run()

    assert events[0] == ("start", None)
    assert any(event[0] == 100.0 for event in events)
    assert events[-1] == (True, "Demo abgeschlossen · keine Datei gespeichert")
    assert not target.exists()
    assert not target.parent.exists()
    assert not job.staging_dir.exists()


def test_demo_commit_is_fail_closed(tmp_path: Path):
    job = DownloadJob(
        "https://invalid.example/video.mp4",
        "mp4",
        tmp_path / "target.mp4",
        demo_mode=True,
    )

    prepared, detail = job._prepare_staging()

    assert prepared is False
    assert "Demo-Modus" in detail
    assert not job.staging_dir.exists()


def test_settings_accept_demo_without_preparing_media_directories(monkeypatch):
    prepared = []
    monkeypatch.setattr(administration.appconfig, "load_deployment_mode", lambda: "desktop")
    monkeypatch.setattr(administration.appconfig, "save", lambda value: value == "")
    monkeypatch.setattr(administration.appconfig, "save_series_path", lambda value: value == "")
    monkeypatch.setattr(administration.appconfig, "save_deployment_mode", lambda value: value == "demo")
    monkeypatch.setattr(administration.appconfig, "load", lambda: "virtual-movies")
    monkeypatch.setattr(administration.appconfig, "load_series_path", lambda: "virtual-series")
    monkeypatch.setattr(
        administration,
        "_prepare_media_directory",
        lambda *args: prepared.append(args),
    )
    monkeypatch.setattr(
        administration,
        "write_project_env",
        lambda *args: {"path": ".env", "created": False},
    )
    previous = (administration.state.save_path, administration.state.series_path)
    try:
        result = asyncio.run(administration.api_config_set(
            administration.ConfigBody(
                deployment_mode="demo", save_path="", series_path="",
            )
        ))
    finally:
        administration.state.save_path, administration.state.series_path = previous

    assert prepared == []
    assert result["deployment_mode"] == "demo"
    assert result["save_path"] == ""
    assert result["series_path"] == ""
    assert result["restart_required"] is True
