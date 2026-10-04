import requests
import pytest

import updates.update_checker as module
from updates.update_checker import UpdateChecker
from core.security_runtime import _install_update_checker_hardening


@pytest.fixture
def checker(monkeypatch, tmp_path):
    _install_update_checker_hardening(module)
    monkeypatch.setattr(module, "detect_local_commit", lambda _root: "a" * 40)
    return UpdateChecker(branch="main", app_dir=tmp_path, github_token="")


def test_missing_revision_stops_additional_network_requests_at_budget(checker, monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "detect_local_commit", lambda _root: "")

    def get(url, **options):
        calls.append(options["timeout"])
        clock[0] += 7
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","commit":{"message":"build","tree":{"sha":"cccccccccccccccccccccccccccccccccccccccc"}}}'
        return response

    monkeypatch.setattr(module.requests, "get", get)
    result = checker.check(force=True)
    assert len(calls) == 3
    assert sum(calls[-1]) <= 4
    assert result["current_sha"] == ""
    assert result["update_available"] is False
    assert result["error_code"] == "github_unavailable"
    assert result["detail"]
    assert checker._deadline is None


@pytest.mark.parametrize("failure,code", [
    (requests.Timeout("raw timeout"), "check_timeout"),
    (requests.ConnectionError("raw connection"), "github_unavailable"),
])
def test_network_failure_is_retryable_and_not_an_update(checker, monkeypatch, failure, code):
    def fail(_path):
        raise failure

    monkeypatch.setattr(checker, "_get_json", fail)
    result = checker.check(force=True)
    assert result["error_code"] == code
    assert "raw" not in result["error"]
    assert result["update_available"] is None
    assert checker._deadline is None


def test_temporary_failure_cache_expires_quickly_and_recovers(checker, monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def get(path):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout()
        if "check-runs" in path:
            return {"check_runs": [{"name": "verify", "status": "completed", "conclusion": "success"}]}
        return {"sha": "a" * 40, "commit": {"message": "build", "verification": {"verified": True}}}

    monkeypatch.setattr(checker, "_get_json", get)
    assert checker.check()["error_code"] == "check_timeout"
    clock[0] = 14
    assert checker.check()["error_code"] == "check_timeout"
    assert len(calls) == 1
    clock[0] = 16
    assert checker.check()["comparison"] == "identical"
    assert len(calls) == 4
    assert checker.check()["security_approved"] is True
    assert len(calls) == 4


def test_concurrent_check_returns_busy_without_changing_channel_or_cache(checker):
    checker._cache = {"branch": "main", "update_available": True}
    checker._lock.acquire()
    try:
        result = checker.check_branch("overnight", force=True)
        assert result["error_code"] == "check_busy"
        assert result["branch"] == "overnight"
        assert result["update_available"] is None
        assert checker.branch == "main"
        assert checker._cache["update_available"] is True
    finally:
        checker._lock.release()


@pytest.mark.parametrize("status", [429, 502, 503])
def test_github_overload_is_retryable(checker, monkeypatch, status):
    def fail(_path):
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError("raw upstream response", response=response)

    monkeypatch.setattr(checker, "_get_json", fail)
    result = checker.check(force=True)
    assert result["error_code"] == "github_unavailable"
    assert result["update_available"] is None


def test_rate_limit_has_retryable_status_and_no_followup_requests(checker, monkeypatch):
    calls = []

    def get(_url, **_options):
        calls.append(1)
        response = requests.Response()
        response.status_code = 403
        response.headers["X-RateLimit-Remaining"] = "0"
        return response

    monkeypatch.setattr(module.requests, "get", get)
    result = checker.check(force=True)
    assert result["error_code"] == "github_unavailable"
    assert "Limit" in result["error"]
    assert len(calls) == 1


def test_signature_timeout_never_approves_update_and_can_recover(checker, monkeypatch):
    fail = [True]

    def get(path):
        if path == "commits/main":
            return {"sha": "b" * 40, "commit": {"message": "build"}}
        if "check-runs" in path:
            return {"check_runs": [{"name": "verify", "status": "completed", "conclusion": "success"}]}
        if path.startswith("compare/"):
            return {"status": "ahead", "ahead_by": 1}
        if fail[0]:
            raise requests.Timeout()
        return {"commit": {"verification": {"verified": True}}}

    monkeypatch.setattr(checker, "_get_json", get)
    result = checker.check(force=True)
    assert result["error_code"] == "github_unavailable"
    assert result["update_available"] is False
    assert result["security_approved"] is False
    fail[0] = False
    result = checker.check(force=True)
    assert result["error"] == ""
    assert result["security_approved"] is True
    assert result["update_available"] is True
