"""The composed updater must approve only the exact signed target and green CI.

No real GitHub requests are made. This regression coverage models the REST
metadata returned for both protected update channels.
"""

from __future__ import annotations

import pytest

import updates.update_checker as update_checker
from core.security_runtime import _install_update_checker_hardening


CURRENT = "a" * 40
TARGET = "b" * 40


@pytest.fixture
def checker_factory(monkeypatch, tmp_path):
    # The live composition root installs this after all runtime services.
    _install_update_checker_hardening(update_checker)
    monkeypatch.setattr(update_checker, "detect_local_commit", lambda _root: CURRENT)

    def factory(branch, *, verification=None, returned_sha=TARGET, checks=None):
        checker = update_checker.UpdateChecker(branch=branch, app_dir=tmp_path)
        observed = []
        if checks is None:
            checks = [{"id": 10, "name": "verify",
                       "status": "completed", "conclusion": "success"}]

        def get_json(path):
            observed.append(path)
            if path == f"commits/{branch}":
                return {"sha": TARGET, "commit": {"message": "candidate update"},
                        "parents": [{"sha": CURRENT}]}
            if path == f"commits/{TARGET}/check-runs?per_page=100":
                return {"check_runs": checks}
            if path == f"commits/{TARGET}":
                return {"sha": returned_sha, "commit": {"verification": verification}}
            if path == f"compare/{CURRENT}...{TARGET}":
                return {"status": "ahead", "ahead_by": 1, "behind_by": 0}
            raise AssertionError(f"Unexpected GitHub request: {path}")

        monkeypatch.setattr(checker, "_get_json", get_json)
        return checker, observed

    return factory


@pytest.mark.parametrize("branch", ["main", "overnight"])
@pytest.mark.parametrize(
    ("verification", "returned_sha", "approved", "reason"),
    [
        ({"verified": True, "reason": "valid"}, TARGET, True, "valid"),
        ({"verified": False, "reason": "unsigned"}, TARGET, False, "unsigned"),
        ({"verified": False, "reason": "bad_email"}, TARGET, False, "bad_email"),
        ({"verified": True, "reason": "unknown_key"}, TARGET, False, "unknown_key"),
        ({"verified": True, "reason": "gpgverify_unavailable"}, TARGET, False,
         "gpgverify_unavailable"),
        ({"verified": True}, TARGET, False, "unverified"),
        (None, TARGET, False, "unverified"),
        ({"verified": True, "reason": "valid"}, "c" * 40, False,
         "revision_mismatch"),
        ({"verified": True, "reason": "valid"}, "", False, "revision_mismatch"),
    ],
)
def test_exact_commit_signature_required_for_both_channels(
    checker_factory, branch, verification, returned_sha, approved, reason,
):
    checker, calls = checker_factory(
        branch, verification=verification, returned_sha=returned_sha,
    )

    result = checker.check(force=True)

    assert f"commits/{TARGET}/check-runs?per_page=100" in calls
    assert calls[-1] == f"commits/{TARGET}"
    assert result["latest_sha"] == TARGET
    assert result["quality_gate"] == "passed"
    assert result["quality_approved"] is True
    assert result["commit_signature_verified"] is approved
    assert result["commit_signature_reason"] == reason
    assert result["security_approved"] is approved
    assert result.get("security_blocked", False) is not approved
    assert result["update_available"] is approved
    assert result["error"] == ""


@pytest.mark.parametrize("branch", ["main", "overnight"])
@pytest.mark.parametrize(
    ("checks", "expected_gate"),
    [
        ([], "missing"),
        ([{"id": 10, "name": "verify", "status": "in_progress",
           "conclusion": None}], "pending"),
        ([{"id": 10, "name": "verify", "status": "completed",
           "conclusion": "failure"}], "failed"),
        ([{"id": 10, "name": "verify", "status": "completed",
           "conclusion": "success"},
          {"id": 20, "name": "verify", "status": "in_progress",
           "conclusion": None}], "pending"),
    ],
)
def test_signature_cannot_substitute_for_missing_or_failed_quality(
    checker_factory, branch, checks, expected_gate,
):
    checker, calls = checker_factory(
        branch, verification={"verified": True, "reason": "valid"},
        checks=checks,
    )

    result = checker.check(force=True)

    assert f"commits/{TARGET}" in calls
    assert result["quality_gate"] == expected_gate
    assert result["quality_approved"] is False
    assert result["commit_signature_verified"] is True
    assert result["security_approved"] is False
    assert result["security_blocked"] is True
    assert result["update_available"] is False
