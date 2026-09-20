import pytest

import core.auth as auth
from core.users import UserStore


def test_user_first_login_and_last_admin_guard(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    member = users.create("Jacqueline", "jacqueline", "member")
    assert member["setup_required"] is True
    assert users.find("JACQUELINE")["password_hash"] == ""
    users.set_password(member["id"], auth.hash_password("ein-sicheres-passwort"))
    assert users.find("jacqueline")["setup_required"] is False
    admin = users.create("Steffen", "steffen", "admin")
    with pytest.raises(ValueError):
        users.set_enabled(admin["id"], False)
