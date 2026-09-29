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


def test_profile_ui_exposes_personal_jellyfin_mapping():
    markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    controller = (ROOT / "web/js/features/profile/index.js").read_text(encoding="utf-8")
    view = (ROOT / "web/js/features/profile/view.js").read_text(encoding="utf-8")

    assert 'id="profile-jellyfin-user"' in markup
    assert 'id="profile-jellyfin-save"' in markup
    assert '"/api/me/jellyfin-profile"' in controller
    assert "jellyfin.user_id" in view


def test_household_jellyfin_sync_is_per_royal_user():
    runtime = (ROOT / "application_services" / "taste_recommender_runtime.py").read_text(encoding="utf-8")

    assert 'user.get("jellyfin_user_id")' in runtime
    assert "state.taste_profiles.for_user(royal_user_id).replace_jellyfin_items(watched)" in runtime
