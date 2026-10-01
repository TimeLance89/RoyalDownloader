#!/usr/bin/env python3
"""Exercise published v1.1.0 data with old, candidate and rollback code.

Run only with disposable SERIENDL_DATA_DIR and ROYAL_GATE_RUNTIME volumes.
The v1.1.0 tag incorrectly reported APP_VERSION=1.0.0; its SHA identifies it.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import release_readiness_gate as legacy
# The shared harness also supports direct source-tree execution; this gate must
# always exercise the checkout/image selected by the caller, including rollback.
sys.path.insert(0, str(Path.cwd()))
from core import auth, config
from core.app_version import APP_VERSION
from core.personal_requests import PersonalRequestStore
from core.users import UserStore
from features.taste_profile import UserTasteProfileStore

STABLE_SHA = "31d91417c4d45bb054140de60b7125ac6b7dbd78"
MARKER = legacy.DATA_DIR / "stable-upgrade.json"
RUNTIME = Path(os.environ["ROYAL_GATE_RUNTIME"])


def running_source_sha():
    """Read the immutable source marker written into the built image.

    APP_COMMIT_SHA is intentionally build-only: the final runtime stage must not
    retain a stale image environment value after an in-app runtime switch.
    """
    for name in (".app_commit_sha", "BUILD_COMMIT"):
        marker = Path.cwd() / name
        if marker.is_file():
            value = marker.read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def settings():
    return {name: getattr(config, name)() for name in (
        "load", "load_series_path", "load_automation", "load_updater",
        "load_jellyfin", "load_provider_priorities", "load_provider_enabled",
        "load_content_languages", "load_tmdb", "load_watchlist",
        "load_movie_subscriptions", "load_deployment_mode", "load_ui_language",
    )}


def normalized_users_for_upgrade(items):
    """Normalize only additive, empty profile defaults across old releases.

    The gate must still fail when any pre-existing account, role, onboarding,
    timestamp or security value changes. New optional presentation fields are
    allowed only at their migration default.
    """
    normalized = []
    for item in items:
        value = dict(item)
        value.setdefault("avatar_id", "")
        normalized.append(value)
    return normalized


def seed():
    assert running_source_sha() == STABLE_SHA
    assert APP_VERSION == "1.0.0", "Published v1.1.0's historical metadata changed"
    legacy.seed_upgrade_rc()
    import server  # Register the same application config extensions as on restart.
    assert server.state is not None
    assert config.save_jellyfin("http://jellyfin.invalid:8096", "fixture-only", "user-fixture")
    assert config.save_provider_priorities(["filmpalast"], ["serienstream"], content_languages=["de"])
    users = UserStore(config.users_file(), config.load_auth())
    member = users.create("Release member", "release-member", "member")
    users.set_password(member["id"], auth.hash_password(legacy.ADMIN_PASSWORD))
    users.complete_taste_onboarding(member["id"])
    session = auth.SessionStore(config.sessions_file()).create("upgrade", user_id=member["id"])
    profiles = UserTasteProfileStore(config.taste_profile_file())
    profiles.for_user(member["id"]).set_feedback("movie:fixture", "like", metadata={"genres": ["Drama"]})
    assert config.save_watchlist([{
        "base_slug": "release-series", "title": "Release series",
        "sample_url": "https://example.invalid/series", "requested_by_user_id": member["id"],
    }])
    assert config.save_movie_subscriptions([{
        "key": "tmdb:999", "title": "Release movie", "requested_by_user_id": member["id"],
    }])
    job = {"job_id": "stable-request", "slug": "fixture-movie", "status": "completed", "created_at": 10.0}
    request = PersonalRequestStore(config.personal_requests_file()).record(member["id"], job)
    assert request
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "previous-release-marker").write_text(STABLE_SHA, encoding="utf-8")
    MARKER.write_text(json.dumps({
        "source_sha": STABLE_SHA, "settings": settings(), "users": users.list(),
        "user_id": member["id"], "session": session, "request": request, "job": job,
    }), encoding="utf-8")
    print("Published v1.1.0 seed: PASS")


def verify(mode):
    if mode == "rollback":
        assert running_source_sha() == STABLE_SHA
        assert APP_VERSION == "1.0.0"
    else:
        assert APP_VERSION == "1.5.0"
    import server
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    assert marker["source_sha"] == STABLE_SHA
    assert settings() == marker["settings"], "Settings/subscriptions changed"
    assert config.is_initialized()
    assert auth.verify_password(legacy.ADMIN_PASSWORD, config.load_auth()["password_hash"])
    users = UserStore(config.users_file(), config.load_auth())
    assert normalized_users_for_upgrade(users.list()) == normalized_users_for_upgrade(
        marker["users"],
    ), "Accounts/onboarding changed"
    assert auth.verify_password(legacy.ADMIN_PASSWORD, users.get(marker["user_id"])["password_hash"])
    assert server.SESSION_STORE.validate(marker["session"])
    assert server.SESSION_STORE.user_id(marker["session"]) == marker["user_id"]
    jobs, slugs = legacy._load_queue_compat(config)
    assert slugs.count(legacy.UPGRADE_SLUG) == 1
    assert legacy.UPGRADE_SLUG in server.state.picked
    original = json.loads(legacy.UPGRADE_MARKER.read_text(encoding="utf-8"))
    assert next(job["job_id"] for job in jobs if job["slug"] == legacy.UPGRADE_SLUG) == original["queue_job_id"]
    profiles = UserTasteProfileStore(config.taste_profile_file())
    assert profiles.for_user(marker["user_id"]).public_profile()["genres"]["Drama"] > 0
    assert profiles.for_user("admin-legacy").public_profile()["genres"] == {}
    requests = PersonalRequestStore(config.personal_requests_file())
    assert requests.recent_for_user(marker["user_id"]) == [marker["request"]]
    assert requests.recent_for_user("admin-legacy") == []
    assert requests.record(marker["user_id"], marker["job"])["id"] == marker["request"]["id"]
    assert requests.count_for_user(marker["user_id"]) == 1
    # Exercise candidate writes, not just passive reads, before rollback.
    assert config.save_watchlist(config.load_watchlist())
    assert config.save_movie_subscriptions(config.load_movie_subscriptions())
    assert (RUNTIME / "previous-release-marker").read_text(encoding="utf-8") == STABLE_SHA
    print(f"Published Stable {mode} / restart / isolation / retry persistence: PASS")


if __name__ == "__main__":
    if sys.argv[1] == "seed":
        seed()
    else:
        verify(sys.argv[1])
