import pytest
import time

import core.auth as auth
from core.users import UserStore
from features.taste_profile import TasteProfileStore, UserTasteProfileStore
from integrations.royal_intelligence import RoyalIntelligenceService, profile_summary


def test_user_first_login_and_last_admin_guard(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    member = users.create("Jacqueline", "jacqueline", "member")
    assert member["setup_required"] is True
    assert member["taste_onboarding_required"] is True
    assert users.find("JACQUELINE")["password_hash"] == ""
    users.set_password(member["id"], auth.hash_password("ein-sicheres-passwort"))
    assert users.find("jacqueline")["setup_required"] is False
    admin = users.create("Steffen", "steffen", "admin")
    with pytest.raises(ValueError):
        users.set_enabled(admin["id"], False)


def test_user_taste_profiles_are_isolated_and_legacy_stays_with_admin(tmp_path):
    legacy_path = tmp_path / "taste_profile.json"
    legacy = TasteProfileStore(legacy_path, clock=time.time)
    legacy.record_event("like", item_key="movie:space", metadata={"genres": ["Sci-Fi"]})

    profiles = UserTasteProfileStore(legacy_path)
    admin = profiles.for_user("admin-legacy").public_profile()
    jacqueline_store = profiles.for_user("jacqueline-id")
    jacqueline = jacqueline_store.public_profile()

    assert admin["genres"]["Science-Fiction"] > 0
    assert jacqueline["genres"] == {}
    jacqueline_store.record_event(
        "onboarding_like", item_key="movie:romance", metadata={"genres": ["Romance"]},
    )
    assert profiles.for_user("jacqueline-id").public_profile()["genres"]["Romanze"] > 0
    assert "Romanze" not in profiles.for_user("admin-legacy").public_profile()["genres"]


def test_intelligence_cache_fingerprint_includes_user_owner():
    service = RoyalIntelligenceService({"enabled": True, "model": "test", "url": "http://localhost"})
    candidates = [{"key": "movie:1", "title": "One", "kind": "movie", "genres": ["Drama"]}]
    summary = profile_summary({"dimensions": {}, "interactions": 0, "confidence": 0})
    compact = candidates

    assert service._fingerprint(compact, summary, service.config(), "user-a") != service._fingerprint(
        compact, summary, service.config(), "user-b",
    )


def test_completing_taste_onboarding_is_user_specific(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    first = users.create("A", "user-a", "member")
    second = users.create("B", "user-b", "member")

    users.complete_taste_onboarding(first["id"])

    assert users.get(first["id"])["taste_onboarding_required"] is False
    assert users.get(second["id"])["taste_onboarding_required"] is True
