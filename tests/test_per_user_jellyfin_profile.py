from pathlib import Path

from core.users import UserStore


ROOT = Path(__file__).resolve().parents[1]


def test_user_store_persists_jellyfin_identity_per_profile(tmp_path):
    store = UserStore(tmp_path / "users.json", {})
    first = store.create("Alice", "alice", "member")
    second = store.create("Bob", "bob", "member")

    store.set_jellyfin_user(first["id"], "jf-alice", "Alice JF")

    assert store.get(first["id"])["jellyfin_user_id"] == "jf-alice"
    assert store.get(first["id"])["jellyfin_user_name"] == "Alice JF"
    assert store.get(second["id"])["jellyfin_user_id"] == ""
    assert store.get(second["id"])["jellyfin_user_name"] == ""
    assert "jellyfin_user_id" not in store.list()[0]
    mappings = {item["id"]: item for item in store.list_jellyfin_profiles()}
    assert mappings[first["id"]]["jellyfin_user_id"] == "jf-alice"
    assert mappings[second["id"]]["jellyfin_user_id"] == ""


def test_user_store_persists_profile_name_and_avatar(tmp_path):
    store = UserStore(tmp_path / "users.json", {})
    user = store.create("Alice", "alice", "member")

    saved = store.set_profile_identity(user["id"], "Alice Kino", "avatar-purple")

    assert saved["display_name"] == "Alice Kino"
    assert saved["avatar_id"] == "avatar-purple"
    assert store.get(user["id"])["avatar_id"] == "avatar-purple"

    try:
        store.set_profile_identity(user["id"], "Alice", "../unsafe")
    except ValueError as exc:
        assert "Profilbild" in str(exc)
    else:
        raise AssertionError("unknown avatar id must be rejected")


def test_household_chooser_owns_personal_jellyfin_mapping_ui():
    markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    household = (ROOT / "web/js/features/profile/household.js").read_text(encoding="utf-8")
    profile = (ROOT / "web/js/features/profile/index.js").read_text(encoding="utf-8")

    assert 'id="household-jellyfin-user"' in markup
    assert 'id="household-manage-save"' in markup
    assert 'id="household-profile-name"' in markup
    assert 'id="household-avatar-grid"' in markup
    assert "household-user-settings" in household
    assert "/profile" in household
    assert "PROFILE_AVATARS" in household
    assert '"/api/me/household/unlock"' in household
    assert "/jellyfin-profile" in household
    assert 'id="profile-jellyfin-user"' not in markup
    assert '"/api/me/jellyfin-profile"' not in profile


def test_household_jellyfin_sync_is_per_royal_user():
    runtime = (ROOT / "application_services" / "taste_recommender_runtime.py").read_text(encoding="utf-8")

    assert 'list_jellyfin_profiles()' in runtime
    assert 'user.get("jellyfin_user_id")' in runtime
    assert "state.taste_profiles.for_user(royal_user_id).replace_jellyfin_items(watched)" in runtime
