"""Historical account snapshots accept additive defaults, never security changes."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def normalize(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.setenv("ROYAL_GATE_RUNTIME", str(tmp_path / "runtime"))
    spec = importlib.util.spec_from_file_location("stable_defaults_gate", scripts / "stable_upgrade_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalized_users_for_upgrade


def test_non_enrolled_old_account_matches_additive_false_flag_without_mutation(normalize):
    old = {"id": "member", "role": "member", "enabled": True, "created_at": 123, "taste_onboarding_required": False}
    current = {**old, "avatar_id": "", "mfa_enabled": False}
    assert normalize([old]) == normalize([current])
    assert "mfa_enabled" not in old and "avatar_id" not in old


@pytest.mark.parametrize(("field", "changed"), [("mfa_enabled", True), ("role", "admin"),
    ("enabled", False), ("created_at", 124), ("taste_onboarding_required", True)])
def test_security_and_account_changes_still_fail_the_upgrade_comparison(normalize, field, changed):
    old = {"id": "member", "role": "member", "enabled": True, "created_at": 123, "taste_onboarding_required": False}
    assert normalize([old]) != normalize([{**old, field: changed}])
