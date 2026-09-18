from pathlib import Path

from integrations.jellyfin_auth import jellyfin_auth_headers


def test_jellyfin_12_auth_header_uses_mediabrowser_scheme():
    headers = jellyfin_auth_headers("  secret  ", accept_json=True)

    assert headers == {
        "Authorization": 'MediaBrowser Token="secret"',
        "Accept": "application/json",
    }
    assert "X-Emby-Token" not in headers


def test_active_jellyfin_callers_do_not_use_legacy_emby_token_header():
    root = Path(__file__).resolve().parents[1]
    active_callers = (
        "integrations/jellyfin_client.py",
        "application_services/jellyfin_live.py",
        "application_services/seerr.py",
        "features/smart_automation.py",
    )

    for relative_path in active_callers:
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "X-Emby-Token" not in source, relative_path
        assert "jellyfin_auth_headers" in source, relative_path
