import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

import config
import server
import update_checker
from update_channels import (
    DEFAULT_UPDATE_CHANNEL,
    UPDATE_CHANNEL_BRANCHES,
    normalize_update_channel,
    update_branch_for_channel,
)
from update_checker import UpdateChecker


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_PROJECT_DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_legacy_migration_checked", True)
    monkeypatch.delenv("UPDATE_MODE", raising=False)
    monkeypatch.delenv("AUTO_UPDATE", raising=False)
    monkeypatch.delenv("AUTO_UPDATE_INTERVAL_HOURS", raising=False)
    monkeypatch.delenv("UPDATE_CHANNEL", raising=False)
    monkeypatch.delenv("UPDATE_GITHUB_BRANCH", raising=False)
    return tmp_path / config.APP_NAME / "settings.ini"


def test_existing_configuration_without_channel_defaults_to_stable(isolated_config):
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("save_path = /movies\nupdate_mode = manual\n", encoding="utf-8")

    loaded = config.load_updater()

    assert loaded["update_channel"] == DEFAULT_UPDATE_CHANNEL == "stable"
    assert loaded["update_branch"] == "main"


def test_channel_mapping_is_central_and_rejects_unknown_values_safely():
    assert dict(UPDATE_CHANNEL_BRANCHES) == {
        "stable": "main",
        "overnight": "overnight",
    }
    assert update_branch_for_channel("stable") == "main"
    assert update_branch_for_channel("overnight") == "overnight"
    assert normalize_update_channel("invalid") == "stable"


def test_switching_checker_branch_invalidates_cached_branch_result(tmp_path):
    checker = UpdateChecker(branch="main", app_dir=tmp_path)
    checker._cache = {"branch": "main"}
    checker._cache_time = 123.0

    assert checker.set_branch("overnight") == "overnight"
    assert checker.branch == "overnight"
    assert checker._cache is None
    assert checker._cache_time == 0.0


def test_in_app_update_marker_overrides_stale_checkout_and_container_environment(
    monkeypatch,
    tmp_path,
):
    checkout_sha = "a" * 40
    current_sha = "b" * 40
    monkeypatch.setenv("APP_COMMIT_SHA", "c" * 40)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(checkout_sha + "\n", encoding="utf-8")
    (tmp_path / ".app_commit_sha").write_text(current_sha + "\n", encoding="utf-8")

    assert update_checker.detect_local_commit(tmp_path) == current_sha


def test_container_commit_environment_remains_fallback_without_release_marker(
    monkeypatch,
    tmp_path,
):
    image_sha = "c" * 40
    monkeypatch.setenv("APP_COMMIT_SHA", image_sha)

    assert update_checker.detect_local_commit(tmp_path) == image_sha


def test_updater_reads_changed_project_token_without_restart(monkeypatch, tmp_path):
    token_file = tmp_path / ".env"
    token_file.write_text("UPDATE_GITHUB_TOKEN=first-token\n", encoding="utf-8")
    monkeypatch.setenv("APP_SOURCE_DIR", str(tmp_path))
    checker = UpdateChecker(app_dir=tmp_path)

    assert checker._github_token() == "first-token"

    token_file.write_text("UPDATE_GITHUB_TOKEN=second-token\n", encoding="utf-8")

    assert checker._github_token() == "second-token"


@pytest.mark.parametrize(
    ("check_run", "expected_gate", "expected_approved", "expected_update"),
    (
        (
            {"name": "verify", "status": "completed", "conclusion": "success"},
            "passed",
            True,
            True,
        ),
        (
            {"name": "verify", "status": "in_progress", "conclusion": None},
            "pending",
            False,
            False,
        ),
        (
            {"name": "verify", "status": "completed", "conclusion": "failure"},
            "failed",
            False,
            False,
        ),
    ),
)
def test_overnight_update_requires_successful_quality_for_exact_commit(
    monkeypatch,
    tmp_path,
    check_run,
    expected_gate,
    expected_approved,
    expected_update,
):
    current_sha = "a" * 40
    latest_sha = "b" * 40
    checker = UpdateChecker(branch="overnight", app_dir=tmp_path)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _path: current_sha)

    def fake_get_json(path):
        if path == "commits/overnight":
            return {
                "sha": latest_sha,
                "html_url": f"https://github.com/example/commit/{latest_sha}",
                "commit": {"message": "tested Overnight build"},
            }
        if path == f"commits/{latest_sha}/check-runs?per_page=100":
            return {"check_runs": [check_run]}
        if path == f"commits/{latest_sha}":
            return {
                "sha": latest_sha,
                "commit": {"verification": {"verified": True, "reason": "valid"}},
            }
        if path == f"compare/{current_sha}...{latest_sha}":
            return {"status": "ahead", "ahead_by": 1, "behind_by": 0}
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(checker, "_get_json", fake_get_json)

    result = checker.check(force=True)

    assert result["latest_sha"] == latest_sha
    assert result["quality_gate"] == expected_gate
    assert result["quality_approved"] is expected_approved
    assert result["commit_signature_verified"] is True
    assert result["security_approved"] is expected_approved
    assert result["update_available"] is expected_update


def test_missing_overnight_quality_result_fails_closed(monkeypatch, tmp_path):
    checker = UpdateChecker(branch="overnight", app_dir=tmp_path)
    monkeypatch.setattr(
        checker,
        "_get_json",
        lambda _path: {"check_runs": [{"name": "unrelated", "status": "completed"}]},
    )

    assert checker._quality_gate_state("b" * 40) == "missing"


def test_fresh_stable_archive_is_detected_after_switch_to_overnight(
    monkeypatch, tmp_path,
):
    stable_sha = "a" * 40
    overnight_sha = "b" * 40
    checker = UpdateChecker(branch="overnight", app_dir=tmp_path)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _path: "")

    def fake_get_json(path):
        if path == "commits/overnight":
            return {
                "sha": overnight_sha,
                "commit": {"message": "overnight", "tree": {"sha": "d" * 40}},
            }
        if path == f"commits/{overnight_sha}/check-runs?per_page=100":
            return {"check_runs": [{
                "name": "verify", "status": "completed", "conclusion": "success",
            }]}
        if path == f"commits/{overnight_sha}":
            return {
                "sha": overnight_sha,
                "commit": {"verification": {"verified": True, "reason": "valid"}},
            }
        if path == "commits/main":
            return {
                "sha": stable_sha,
                "commit": {"message": "stable", "tree": {"sha": "c" * 40}},
            }
        if path == f"compare/{stable_sha}...{overnight_sha}":
            return {"status": "ahead", "ahead_by": 1, "behind_by": 0}
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(checker, "_get_json", fake_get_json)
    monkeypatch.setattr(
        checker,
        "_source_matches_commit",
        lambda payload: payload.get("sha") == stable_sha,
    )

    result = checker.check(force=True)

    assert result["current_sha"] == stable_sha
    assert result["comparison"] == "ahead"
    assert result["security_approved"] is True
    assert result["update_available"] is True


def test_stable_requires_the_same_green_quality_gate(monkeypatch, tmp_path):
    checker = UpdateChecker(branch="main", app_dir=tmp_path)
    latest_sha = "b" * 40

    def fake_get_json(path):
        assert path == f"commits/{latest_sha}/check-runs?per_page=100"
        return {"check_runs": [{
            "name": "verify", "status": "completed", "conclusion": "success",
        }]}

    monkeypatch.setattr(checker, "_get_json", fake_get_json)

    assert checker._quality_gate_state(latest_sha) == "passed"


def test_channel_selection_is_persisted_and_survives_reload(isolated_config):
    assert config.save_updater("automatic", 12, "overnight") is True
    assert "update_channel = overnight" in isolated_config.read_text(encoding="utf-8")

    loaded_after_restart = config.load_updater()

    assert loaded_after_restart["update_channel"] == "overnight"
    assert loaded_after_restart["update_branch"] == "overnight"
    assert loaded_after_restart["update_mode"] == "automatic"

    # Older clients do not send the additive channel field.
    assert config.save_updater("manual", 6) is True
    assert config.load_updater()["update_channel"] == "overnight"


def test_persisted_channel_overrides_stale_runtime_snapshot(
    monkeypatch, isolated_config,
):
    assert config.save_updater("automatic", 6, "overnight") is True
    monkeypatch.setattr(server.state, "updater_cfg", {
        "update_mode": "automatic",
        "auto_update": True,
        "auto_update_interval_hours": 6,
        "update_channel": "stable",
        "update_branch": "main",
    })

    payload = server._updater_config_payload()

    assert payload["update_channel"] == "overnight"
    assert payload["update_branch"] == "overnight"
    assert server.state.updater_cfg["update_channel"] == "overnight"


class _Checker:
    def __init__(self, comparison="ahead"):
        self.branch = "main"
        self.comparison = comparison

    def set_branch(self, branch):
        self.branch = branch
        return branch

    def check(self, _force=False):
        return {
            "repository": "TimeLance89/RoyalDownloader",
            "repository_url": "https://github.com/TimeLance89/RoyalDownloader",
            "branch": self.branch,
            "current_sha": "a" * 40,
            "latest_sha": "b" * 40,
            "comparison": self.comparison,
            "update_available": self.comparison in {"ahead", "diverged"},
            "ahead_by": 1,
            "behind_by": 1 if self.comparison in {"behind", "diverged"} else 0,
            "error": "",
        }

    def check_branch(self, branch, force=False):
        self.set_branch(branch)
        return self.check(force)


class _Installer:
    def status(self):
        return {"state": "idle", "active": False, "rollback_available": True}

    def rollback(self):
        return {"state": "restarting", "rollback_available": True}


def _bind_updater(monkeypatch, channel, comparison="ahead"):
    checker = _Checker(comparison)
    monkeypatch.setattr(server, "UPDATE_CHECKER", checker)
    monkeypatch.setattr(server, "UPDATE_INSTALLER", _Installer())
    monkeypatch.setattr(server, "_updater_config_payload", lambda: {
        "update_mode": "manual",
        "auto_update": False,
        "auto_update_interval_hours": 6,
        "update_channel": channel,
        "update_branch": update_branch_for_channel(channel),
    })
    return checker


@pytest.mark.parametrize(
    ("channel", "branch"),
    (("stable", "main"), ("overnight", "overnight")),
)
def test_update_status_channel_and_checker_branch_stay_consistent(
    monkeypatch, channel, branch,
):
    checker = _bind_updater(monkeypatch, channel)

    payload = asyncio.run(server.api_updater_status(True))

    assert payload["update_channel"] == channel
    assert payload["update_branch"] == branch
    assert payload["branch"] == branch
    assert checker.branch == branch
    assert payload["application_version"] == server.APP_VERSION


def test_api_channel_change_is_saved_and_reconfigures_checker(
    monkeypatch, isolated_config,
):
    checker = _Checker()
    monkeypatch.setattr(server, "UPDATE_CHECKER", checker)
    monkeypatch.setattr(server.state, "updater_cfg", config.load_updater())

    payload = asyncio.run(server.api_updater_config_set(server.UpdaterConfigBody(
        update_mode="manual",
        auto_update_interval_hours=6,
        update_channel="overnight",
    )))

    assert payload["saved"] is True
    assert payload["update_channel"] == "overnight"
    assert payload["update_branch"] == "overnight"
    assert checker.branch == "overnight"
    assert config.load_updater()["update_channel"] == "overnight"


def test_overnight_to_stable_divergence_requires_confirmation(monkeypatch):
    _bind_updater(monkeypatch, "stable", comparison="diverged")
    started = []
    monkeypatch.setattr(server, "_start_update_when_idle", started.append)

    status = asyncio.run(server.api_updater_status(True))
    assert status["possible_downgrade"] is True
    assert status["channel_switch_requires_confirmation"] is True

    with pytest.raises(HTTPException, match="Branchwechsel ausdrücklich bestätigen"):
        asyncio.run(server.api_updater_install(server.UpdateInstallBody(target_sha="b" * 40)))
    assert started == []

    asyncio.run(server.api_updater_install(server.UpdateInstallBody(
        target_sha="b" * 40,
        confirm_channel_switch=True,
    )))
    assert started == ["b" * 40]


def test_rollback_contract_is_independent_of_selected_channel(monkeypatch):
    for channel in ("stable", "overnight"):
        _bind_updater(monkeypatch, channel)
        payload = asyncio.run(server.api_updater_rollback())
        assert payload["installer"]["state"] == "restarting"


def test_invalid_api_channel_is_rejected_without_changing_contract(monkeypatch):
    monkeypatch.setattr(config, "save_updater", lambda *_args: True)
    monkeypatch.setattr(config, "load_updater", lambda: {
        "update_mode": "manual",
        "auto_update": False,
        "auto_update_interval_hours": 6,
        "update_channel": "stable",
        "update_branch": "main",
    })
    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_updater_config_set(server.UpdaterConfigBody(
            update_mode="manual",
            update_channel="preview",
        )))
    assert raised.value.status_code == 400


def test_frontend_exposes_both_channels_and_warnings():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    account = (ROOT / "web" / "screens" / "account.js").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="updater-channel"' in html
    assert '<option value="stable">Stable (empfohlen)</option>' in html
    assert '<option value="overnight">Overnight (Entwicklung)</option>' in html
    assert "kann instabil sein" in account
    assert "Rückwechsel zu Stable erkannt" in account
    assert "confirm_channel_switch" in (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "Zum Overnight-Kanal wechseln?" in app


def test_ci_protects_both_branches_and_release_requires_main_ancestry():
    quality = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "branches:\n      - main\n      - overnight" in quality
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/main' in release
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in release
    assert ":latest" not in release.casefold()
