from pathlib import Path

import pytest

from core.profile_avatars import MAX_PROFILE_AVATAR_BYTES, ProfileAvatarStore
from core.users import UserStore


def png_bytes(extra: int = 0) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (b"x" * extra)


def test_profile_avatar_store_round_trip(tmp_path: Path):
    store = ProfileAvatarStore(tmp_path / "profile_avatars")

    saved = store.save("Mein Bild.png", "image/png", png_bytes(32))

    assert saved["id"].startswith("custom-")
    assert saved["content_type"] == "image/png"
    assert store.exists(saved["id"]) is True
    assert store.list()[0]["name"] == "Mein Bild.png"
    payload = store.read(saved["id"])
    assert payload == (png_bytes(32), "image/png")

    deleted = store.delete(saved["id"])
    assert deleted["id"] == saved["id"]
    assert store.read(saved["id"]) is None
    assert store.list() == []


def test_profile_avatar_store_rejects_unsafe_or_oversized_payloads(tmp_path: Path):
    store = ProfileAvatarStore(tmp_path / "profile_avatars")

    with pytest.raises(ValueError, match="PNG"):
        store.save("payload.svg", "image/svg+xml", b"<svg></svg>")

    with pytest.raises(ValueError, match="4 MB"):
        store.save("huge.png", "image/png", png_bytes(MAX_PROFILE_AVATAR_BYTES))


def test_custom_avatar_can_be_assigned_and_cleared_from_users(tmp_path: Path):
    users = UserStore(tmp_path / "users.json", {})
    alice = users.create("Alice", "alice", "member")
    bob = users.create("Bob", "bob", "member")
    avatar_id = "custom-0123456789abcdef"

    users.set_profile_identity(alice["id"], "Alice", avatar_id)
    users.set_profile_identity(bob["id"], "Bob", avatar_id)

    assert users.get(alice["id"])["avatar_id"] == avatar_id
    assert users.clear_avatar_id(avatar_id) == 2
    assert users.get(alice["id"])["avatar_id"] == ""
    assert users.get(bob["id"])["avatar_id"] == ""


def test_custom_avatar_management_is_exposed_in_admin_ui():
    root = Path(__file__).resolve().parents[1]
    markup = (root / "web" / "index.html").read_text(encoding="utf-8")
    account = (root / "web/js/features/settings/account.js").read_text(encoding="utf-8")
    household = (root / "web/js/features/profile/household.js").read_text(encoding="utf-8")
    identity = (root / "web/js/features/profile/identity.js").read_text(encoding="utf-8")
    components = (root / "web/styles/components.css").read_text(encoding="utf-8")

    assert 'id="account-avatar-card"' in markup
    assert 'id="account-avatar-file"' in markup
    assert 'id="account-avatar-library"' in markup
    assert '"/api/auth/profile-avatars"' in account
    assert '"Profilbild löschen"' in account
    assert 'onSaved({ user: currentUser' in account
    assert '"/api/profile-avatars"' in household
    assert 'avatar.startsWith("custom-")' in identity
    assert ".has-profile-avatar" in components
    assert "background-size:cover" in components
