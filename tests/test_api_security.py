from api_security import is_mobile_legacy_path, is_public_path


def test_public_api_policy_is_method_aware():
    assert is_public_path("/api/ui/config", "GET", lambda: False)
    assert not is_public_path("/api/ui/config", "POST", lambda: False)
    assert is_public_path("/api/ui/config", "POST", lambda: True)
    assert not is_public_path("/api/config", "GET", lambda: False)


def test_mobile_legacy_policy_excludes_administration():
    assert is_mobile_legacy_path("/api/movie/example")
    assert is_mobile_legacy_path("/api/queue/add")
    assert not is_mobile_legacy_path("/api/updater/install")
    assert not is_mobile_legacy_path("/api/setup/complete")
