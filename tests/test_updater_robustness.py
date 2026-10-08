"""Regression cases for update approval, channel changes and restart failures."""

import asyncio
import io
import tarfile

import pytest
from fastapi import HTTPException

import server
from application_services import updater as updater_service
from core import config
from updates import self_updater, update_checker
from updates.self_updater import SelfUpdater


@pytest.mark.parametrize("blocked", [
    {"security_blocked": True},
    {"security_approved": False},
    {"quality_approved": False},
    {"error": "verification timeout"},
])
def test_confirmed_downgrade_cannot_bypass_update_approval(monkeypatch, blocked):
    class Checker:
        def check_branch(self, *_args):
            return {
                "latest_sha": "b" * 40, "current_sha": "a" * 40,
                "comparison": "behind", "update_available": False,
                "security_approved": True, "quality_approved": True, **blocked,
            }

    monkeypatch.setattr(server, "UPDATE_CHECKER", Checker())
    monkeypatch.setattr(server, "_updater_config_payload", lambda: {"update_channel": "stable"})
    started = []
    monkeypatch.setattr(server, "_start_update_when_idle", lambda *args, **kwargs: started.append(args))
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_updater_install(server.UpdateInstallBody(
            target_sha="b" * 40, confirm_channel_switch=True,
        )))
    assert error.value.status_code == 409
    assert not started


@pytest.mark.parametrize("new_status,conclusion,expected", [
    ("completed", "failure", "failed"),
    ("in_progress", None, "pending"),
    ("completed", "cancelled", "failed"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_newest_verify_run_supersedes_previous_success(
    monkeypatch, tmp_path, new_status, conclusion, expected, reverse,
):
    checker = update_checker.UpdateChecker(branch="overnight", app_dir=tmp_path)
    runs = [
        {"name": "verify", "id": 100, "status": "completed", "conclusion": "success"},
        {"name": "verify", "id": 200, "status": new_status, "conclusion": conclusion},
    ]
    monkeypatch.setattr(checker, "_get_json", lambda _path: {"check_runs": runs[::-1] if reverse else runs})
    assert checker._quality_gate_state("b" * 40) == expected


@pytest.mark.parametrize("change", [{"update_channel": "overnight"}, {"update_mode": "manual"}])
def test_automatic_update_rechecks_configuration_after_network_check(monkeypatch, change):
    cfg = {"update_channel": "stable", "update_mode": "automatic"}
    monkeypatch.setattr(server.state, "updater_cfg", cfg)
    monkeypatch.setattr(config, "load_updater", lambda: dict(cfg))
    monkeypatch.setattr(server, "_set_updater_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "log", lambda *_args: None)
    started = []

    class Checker:
        def check_branch(self, *_args):
            cfg.update(change)
            return {
                "latest_sha": "b" * 40, "current_sha": "a" * 40,
                "comparison": "ahead", "update_available": True,
                "quality_approved": True, "security_approved": True,
            }

    class Installer:
        def start(self, sha):
            started.append(sha)
            return {}

    monkeypatch.setattr(updater_service, "UPDATE_CHECKER", Checker())
    monkeypatch.setattr(updater_service, "UPDATE_INSTALLER", Installer())
    assert server._attempt_automatic_update() != "installing"
    assert not started


@pytest.mark.parametrize("blocked", [
    {"quality_approved": False}, {"security_approved": False},
    {"security_blocked": True}, {"security_approved": None},
])
def test_automatic_update_requires_explicit_approval(monkeypatch, blocked):
    monkeypatch.setattr(server.state, "updater_cfg", {"update_mode": "automatic", "update_channel": "stable"})
    monkeypatch.setattr(server, "_set_updater_runtime", lambda *_args, **_kwargs: None)
    started = []
    monkeypatch.setattr(server, "_start_update_when_idle", lambda *args, **kwargs: started.append(args))

    class Checker:
        def check_branch(self, *_args):
            return {
                "comparison": "ahead", "update_available": True, "latest_sha": "b" * 40,
                "quality_approved": True, "security_approved": True, **blocked,
            }

    monkeypatch.setattr(updater_service, "UPDATE_CHECKER", Checker())
    assert server._attempt_automatic_update() == "unavailable"
    assert not started


def test_restart_callback_failure_becomes_terminal_error(monkeypatch, tmp_path):
    def restart():
        raise OSError("exec failed")

    updater = SelfUpdater("owner/repo", tmp_path, restart_callback=restart, persistent_override=True)
    monkeypatch.setattr(updater, "_install", lambda _sha: None)
    updater._worker("b" * 40)
    status = updater.status()
    assert status["state"] == "error"
    assert status["active"] is False
    assert "exec failed" in status["error"]


def test_rollback_reports_restored_commit(monkeypatch, tmp_path):
    release = tmp_path / "previous"
    release.mkdir()
    (release / ".app_commit_sha").write_text("a" * 40, encoding="utf-8")
    updater = SelfUpdater("owner/repo", tmp_path, persistent_override=True)
    updater._target_sha = "b" * 40
    monkeypatch.setattr(updater, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(self_updater, "rollback_release", lambda _root: release)
    assert updater.rollback()["target_sha"] == "a" * 40


def test_archive_response_closed_on_size_rejection(monkeypatch, tmp_path):
    class Response:
        headers = {"Content-Length": str(self_updater._MAX_ARCHIVE_BYTES + 1)}
        closed = False

        def raise_for_status(self):
            pass

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(self_updater.requests, "get", lambda *_args, **_kwargs: response)
    updater = SelfUpdater("owner/repo", tmp_path, persistent_override=True)
    with pytest.raises(RuntimeError, match="groß"):
        updater._download_archive("b" * 40, tmp_path / "archive")
    assert response.closed


def test_archive_member_limit_stops_before_reading_all_headers(monkeypatch, tmp_path):
    archive = tmp_path / "archive.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for i in range(4):
            info = tarfile.TarInfo(f"release/file{i}")
            info.size = 1
            bundle.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(self_updater, "_MAX_ARCHIVE_MEMBERS", 3, raising=False)
    monkeypatch.setattr(tarfile.TarFile, "getmembers", lambda _self: pytest.fail("eager member collection"))
    updater = SelfUpdater("owner/repo", tmp_path, persistent_override=True)
    with pytest.raises(RuntimeError, match="zu viele Dateien"):
        updater._extract_archive(archive, tmp_path / "extract")


def test_pending_quality_cache_recovers_without_waiting_ten_minutes(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(update_checker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _root: "a" * 40)
    checker = update_checker.UpdateChecker(branch="overnight", app_dir=tmp_path)

    def get_json(path):
        if "check-runs" in path:
            return {"check_runs": [{"id": 100, "name": "verify",
                                    "status": "in_progress" if clock[0] < 15 else "completed",
                                    "conclusion": "success"}]}
        if "compare/" in path:
            return {"status": "ahead", "ahead_by": 1}
        return {"sha": "b" * 40, "commit": {"message": "build", "verification": {"verified": True}}}

    monkeypatch.setattr(checker, "_get_json", get_json)
    assert checker.check()["update_available"] is False
    clock[0] = 14
    assert checker.check()["quality_gate"] == "pending"
    clock[0] = 16
    assert checker.check()["update_available"] is True


def test_manual_install_rejects_a_channel_changed_since_approval(monkeypatch):
    started = []

    class Installer:
        def start(self, sha):
            started.append(sha)

    monkeypatch.setattr(updater_service, "UPDATE_INSTALLER", Installer())
    monkeypatch.setattr(config, "load_updater", lambda: {"update_channel": "overnight"})
    monkeypatch.setattr(server.state, "updater_cfg", {})
    with pytest.raises(RuntimeError, match="Kanal wurde geändert"):
        server._start_update_when_idle("b" * 40, expected_channel="stable")
    assert not started


def test_asynchronous_restart_failure_is_reported(monkeypatch, tmp_path):
    updater = SelfUpdater("owner/repo", tmp_path, persistent_override=True)
    updater._set_state("restarting", "restarting")
    monkeypatch.setattr(updater_service, "UPDATE_INSTALLER", updater)
    monkeypatch.setattr(server, "log", lambda *_args: None)

    def pause():
        raise OSError("queue persistence failed")

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server, "_pause_downloads_for_update_restart", pause)
    monkeypatch.setattr(updater_service.threading, "Thread", ImmediateThread)
    server._restart_after_update()
    assert updater.status()["active"] is False
    assert "queue persistence failed" in updater.status()["error"]


@pytest.mark.parametrize("transfer", ["success", "truncated", "too_slow"])
def test_archive_transfer_checks_completion_budget_and_closes_response(monkeypatch, tmp_path, transfer):
    clock = [0.0]
    monkeypatch.setattr(self_updater.time, "monotonic", lambda: clock[0])

    class Response:
        headers = {"Content-Length": "2" if transfer == "truncated" else "1"}
        closed = False

        def raise_for_status(self):
            pass

        def iter_content(self, **_kwargs):
            if transfer == "too_slow":
                clock[0] = self_updater._ARCHIVE_DOWNLOAD_SECONDS + 1
            yield b"x"

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(self_updater.requests, "get", lambda *_args, **_kwargs: response)
    updater = SelfUpdater("owner/repo", tmp_path, persistent_override=True)
    if transfer == "success":
        updater._download_archive("b" * 40, tmp_path / "archive")
    else:
        with pytest.raises(RuntimeError, match="unvollständig|Zeitlimit"):
            updater._download_archive("b" * 40, tmp_path / "archive")
    assert response.closed


def test_restart_identity_is_bound_to_process_not_replaced_files(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SERVER_COMMIT", "a" * 40)
    monkeypatch.setattr(server, "APP_DIR", tmp_path)
    (tmp_path / ".app_commit_sha").write_text("f" * 40, encoding="utf-8")
    assert server._capabilities_payload()["current_sha"] == server.SERVER_COMMIT
