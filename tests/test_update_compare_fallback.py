import requests

import update_checker
from update_checker import UpdateChecker


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = "https://api.github.com/repos/example/project/compare/base...head"
    request = requests.Request("GET", response.url).prepare()
    response.request = request
    return requests.HTTPError(f"{status} response", response=response, request=request)


def test_compare_404_uses_latest_parent_without_reporting_github_failure(
    monkeypatch,
    tmp_path,
):
    current_sha = "a" * 40
    latest_sha = "b" * 40
    checker = UpdateChecker(branch="overnight", app_dir=tmp_path)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _path: current_sha)

    def fake_get_json(path):
        if path == "commits/overnight":
            return {
                "sha": latest_sha,
                "html_url": f"https://github.com/example/project/commit/{latest_sha}",
                "commit": {"message": "new overnight build"},
                "parents": [{"sha": current_sha}],
            }
        if path == f"commits/{latest_sha}/check-runs?per_page=100":
            return {"check_runs": [{
                "name": "verify",
                "status": "completed",
                "conclusion": "success",
            }]}
        if path == f"compare/{current_sha}...{latest_sha}":
            raise _http_error(404)
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(checker, "_get_json", fake_get_json)

    result = checker.check(force=True)

    assert result["comparison"] == "ahead"
    assert result["ahead_by"] == 1
    assert result["behind_by"] == 0
    assert result["update_available"] is True
    assert result["error"] == ""


def test_compare_404_without_provable_ancestry_fails_safe(monkeypatch, tmp_path):
    current_sha = "a" * 40
    latest_sha = "b" * 40
    checker = UpdateChecker(branch="main", app_dir=tmp_path)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _path: current_sha)

    def fake_get_json(path):
        if path == "commits/main":
            return {
                "sha": latest_sha,
                "commit": {"message": "latest"},
                "parents": [],
            }
        if path == f"compare/{current_sha}...{latest_sha}":
            raise _http_error(404)
        if path == f"commits/{current_sha}":
            return {"sha": current_sha, "parents": []}
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(checker, "_get_json", fake_get_json)

    result = checker.check(force=True)

    assert result["comparison"] == "unknown"
    assert result["update_available"] is False
    assert result["ahead_by"] == 0
    assert result["behind_by"] == 0
    assert result["error"] == ""


def test_non_404_compare_error_is_still_reported(monkeypatch, tmp_path):
    current_sha = "a" * 40
    latest_sha = "b" * 40
    checker = UpdateChecker(branch="main", app_dir=tmp_path)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _path: current_sha)

    def fake_get_json(path):
        if path == "commits/main":
            return {"sha": latest_sha, "commit": {"message": "latest"}}
        if path == f"compare/{current_sha}...{latest_sha}":
            raise _http_error(503)
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(checker, "_get_json", fake_get_json)

    result = checker.check(force=True)

    assert result["comparison"] == "unknown"
    assert result["update_available"] is None
    assert "503 response" in result["error"]
