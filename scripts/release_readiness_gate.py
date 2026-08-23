#!/usr/bin/env python3
"""Deterministic Stable-1.0 release E2E and upgrade/rollback gates.

The runner is intentionally usable from both the current image and an older RC
image. External provider/TMDB calls are replaced only at explicit adapter seams;
HTTP middleware, setup transaction, auth/session persistence, queue claims and
on-disk state use production code.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any


_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = next(
    (
        candidate
        for candidate in (_SCRIPT_PROJECT_ROOT, Path.cwd().resolve())
        if (candidate / "app_version.py").is_file()
    ),
    _SCRIPT_PROJECT_ROOT,
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = Path(os.environ.get("SERIENDL_DATA_DIR", "/app/data"))
BOOTSTRAP_TOKEN = os.environ.get("ROYAL_SETUP_TOKEN", "release-readiness-bootstrap")
ADMIN_USER = "release-admin"
ADMIN_PASSWORD = "Royal-Release-1.0-Verification!"
QUEUE_SLUG = "filmpalast:release-readiness-queue"
MEDIA_SLUG = "filmpalast:release-readiness-media-flow"
UPGRADE_SLUG = "filmpalast:rc3-upgrade-soak"
QUEUE_MARKER = DATA_DIR / "release-readiness-queue-marker.json"
UPGRADE_MARKER = DATA_DIR / "release-readiness-upgrade-marker.json"


def _fail(message: str) -> None:
    raise AssertionError(message)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _json_contains(value: Any, needle: str) -> bool:
    return needle in json.dumps(value, ensure_ascii=False, sort_keys=True)


def _expect_persisted_mapping(actual: Any, expected: Any, label: str) -> None:
    _expect(isinstance(actual, dict), f"{label}: current value is not a mapping")
    _expect(isinstance(expected, dict), f"{label}: persisted value is not a mapping")
    changed = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if key not in actual or actual.get(key) != value
    }
    _expect(not changed, f"{label}: persisted values changed: {changed}")


def _response_json(response, expected_status: int, label: str) -> Any:
    if response.status_code != expected_status:
        raise AssertionError(
            f"{label}: expected HTTP {expected_status}, got {response.status_code}: "
            f"{response.text[:1000]}"
        )
    return response.json()


def _patch_deterministic_http_runtime():
    import api_administration_router
    import server

    async def _accept_fixture_tmdb(_api_key: str, _ui_language: str) -> None:
        return None

    api_administration_router._validate_setup_tmdb_key = _accept_fixture_tmdb
    server.start_background_services = lambda: None
    return server


def _login(client, username: str = ADMIN_USER, password: str = ADMIN_PASSWORD) -> dict:
    payload = _response_json(
        client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"user-agent": "Royal-Release-Readiness"},
        ),
        200,
        "login",
    )
    _expect(payload.get("authenticated") is True, "login did not authenticate")
    return payload


def first_run_auth_flow() -> None:
    """E2E 1: unclaimed instance -> bootstrap setup -> login -> protected API."""
    from fastapi.testclient import TestClient

    server = _patch_deterministic_http_runtime()
    client = TestClient(server.app)

    status = _response_json(client.get("/api/setup/status"), 200, "setup status")
    _expect(status.get("required") is True, "fresh instance did not require setup")
    _expect(status.get("bootstrap_required") is True, "bootstrap protection is not active")
    _expect(
        BOOTSTRAP_TOKEN not in json.dumps(status, ensure_ascii=False),
        "setup status exposed the bootstrap secret",
    )

    setup = _response_json(
        client.post(
            "/api/setup/complete",
            json={
                "deployment_mode": "desktop",
                "save_path": str(DATA_DIR / "Filme"),
                "series_path": str(DATA_DIR / "Serien"),
                "ui_language": "de",
                "tmdb_api_key": "release-readiness-fixture",
                "auth_username": ADMIN_USER,
                "auth_password": ADMIN_PASSWORD,
                "bootstrap_token": BOOTSTRAP_TOKEN,
            },
            headers={"user-agent": "Royal-Release-Readiness"},
        ),
        200,
        "first-run setup",
    )
    _expect(setup.get("required") is False, "setup transaction remained required")
    _expect(setup.get("auth_configured") is True, "setup did not persist authentication")
    _expect(setup.get("deployment_mode") == "desktop", "setup did not persist deployment mode")

    client.cookies.clear()
    _response_json(
        client.get("/api/updater/config"),
        401,
        "unauthorized protected web API",
    )
    _response_json(
        client.get("/api/v1/updater/config"),
        401,
        "unauthorized protected bearer API",
    )
    _login(client)
    protected = _response_json(
        client.get("/api/updater/config"),
        200,
        "authorized protected web API",
    )
    _expect("update_channel" in protected, "protected updater API returned incomplete payload")
    _response_json(
        client.get("/api/v1/updater/config"),
        401,
        "web session must not cross into bearer-only v1 API",
    )

    post_setup = _response_json(client.get("/api/setup/status"), 200, "post-setup status")
    _expect(post_setup.get("required") is False, "completed setup regressed to first-run state")
    _expect(post_setup.get("bootstrap_required") is False, "bootstrap remained active after setup")
    print("E2E first-run/auth: PASS")


def _install_queue_fakes(server, slug: str, title: str) -> None:
    from providers.models import FilmpalastMovie, HosterInfo

    class _FixtureTmdbClient:
        def movie_summary(self, *_args, **_kwargs) -> dict:
            return {}

        def __getattr__(self, name: str):
            raise AssertionError(f"unexpected TMDB call in release gate: {name}")

    server.state.fp_movies[slug] = FilmpalastMovie(
        title=title,
        url=f"https://provider.invalid/{slug.split(':', 1)[-1]}",
        hosters=[HosterInfo("Fixture", "https://cdn.invalid/release-readiness.mp4")],
        year="2026",
        genres=["Test"],
    )
    server.state.tmdb_client = _FixtureTmdbClient()
    server._content_already_available = lambda *_args, **_kwargs: (False, "")

    # Exercise the real logical queue/scheduler admission path while preventing
    # a physical provider/download worker from starting in deterministic CI.
    server.state.dl_queue.start = lambda: None


def queue_seed_flow() -> None:
    """E2E 2a: create a durable queue claim through the authenticated web API."""
    from fastapi.testclient import TestClient
    import config as appconfig
    import server

    client = TestClient(server.app)
    _login(client)
    _install_queue_fakes(server, QUEUE_SLUG, "Release Readiness Queue Fixture")

    added = _response_json(
        client.post(
            "/api/queue/add",
            json={"slugs": [QUEUE_SLUG], "source": "release-readiness"},
        ),
        200,
        "queue add",
    )
    _expect(added.get("added") == 1, f"queue fixture was not accepted: {added}")

    duplicate = _response_json(
        client.post(
            "/api/queue/add",
            json={"slugs": [QUEUE_SLUG], "source": "release-readiness"},
        ),
        200,
        "duplicate queue add",
    )
    _expect(duplicate.get("added") == 0, "duplicate queue submission created a second job")
    _expect(duplicate.get("skipped", 0) >= 1, "duplicate queue submission was not reported skipped")

    job_id = str(server.state.queue_job_by_slug.get(QUEUE_SLUG) or "")
    _expect(bool(job_id), "logical queue job has no stable job id")
    document, _migrated = appconfig.load_queue_state()
    matching = [job for job in document.get("jobs", []) if job.get("slug") == QUEUE_SLUG]
    _expect(len(matching) == 1, f"persistent queue contains {len(matching)} fixture jobs")
    _expect(str(matching[0].get("job_id") or "") == job_id, "persisted job id differs from runtime")

    QUEUE_MARKER.write_text(
        json.dumps({"slug": QUEUE_SLUG, "job_id": job_id}, sort_keys=True),
        encoding="utf-8",
    )
    print("E2E queue seed/deduplication: PASS")


def queue_restart_verify_flow() -> None:
    """E2E 2b: a new process restores the same durable job and claim exactly once."""
    import config as appconfig
    import server

    marker = json.loads(QUEUE_MARKER.read_text(encoding="utf-8"))
    slug = marker["slug"]
    job_id = marker["job_id"]

    _expect(slug in server.state.picked, "restart lost the durable queue claim")
    _expect(server.state.queue_job_by_slug.get(slug) == job_id, "restart changed queue job identity")
    _expect(job_id in server.state.queue_jobs, "restart did not restore logical queue job")

    document, _migrated = appconfig.load_queue_state()
    matching = [job for job in document.get("jobs", []) if job.get("slug") == slug]
    _expect(len(matching) == 1, f"restart restored {len(matching)} copies of one queue job")
    _expect(str(matching[0].get("job_id") or "") == job_id, "disk job identity changed after restart")
    _expect(
        len([value for value in server.state.queue_job_by_slug if value == slug]) == 1,
        "runtime slug index contains duplicate claim keys",
    )
    print("E2E queue persistence/restart: PASS")


def media_integration_flow() -> None:
    """E2E 3: authenticated web API -> controlled provider media -> queue -> status."""
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    _login(client)
    _install_queue_fakes(server, MEDIA_SLUG, "Release Readiness Media Flow")

    added = _response_json(
        client.post(
            "/api/queue/add",
            json={"slugs": [MEDIA_SLUG], "source": "release-media-flow"},
        ),
        200,
        "media queue add",
    )
    _expect(added.get("added") == 1, f"media flow did not reach queue: {added}")

    queue_status = _response_json(client.get("/api/queue"), 200, "media queue status")
    jobs_status = _response_json(client.get("/api/queue/jobs"), 200, "media jobs status")
    _expect(_json_contains(queue_status, MEDIA_SLUG), "queue status lost media fixture")
    _expect(_json_contains(jobs_status, MEDIA_SLUG), "job status lost media fixture")
    _expect(
        bool(server.state.queue_job_by_slug.get(MEDIA_SLUG)),
        "media flow has no logical queue identity",
    )
    print("E2E media/provider->queue->status: PASS")


def _call_supported(function, values: dict[str, Any]) -> Any:
    signature = inspect.signature(function)
    supported = {name: value for name, value in values.items() if name in signature.parameters}
    return function(**supported)


def _load_queue_compat(appconfig) -> tuple[list[dict], list[str]]:
    if hasattr(appconfig, "load_queue_state"):
        document, _migrated = appconfig.load_queue_state()
        jobs = list(document.get("jobs", []))
        return jobs, [str(job.get("slug") or "") for job in jobs]
    slugs = list(appconfig.load_queue())
    return [], [str(slug) for slug in slugs]


def _auth_matches(appauth, account: dict, password: str) -> bool:
    if not account.get("configured"):
        return False
    if account.get("source") == "env":
        return account.get("env_password") == password
    return appauth.verify_password(password, str(account.get("password_hash") or ""))


def seed_upgrade_rc() -> None:
    """Create realistic RC settings/auth/queue state using the old image's code."""
    import auth as appauth
    import config as appconfig
    from app_version import APP_VERSION

    movie_dir = DATA_DIR / "upgrade-movies"
    series_dir = DATA_DIR / "upgrade-series"
    movie_dir.mkdir(parents=True, exist_ok=True)
    series_dir.mkdir(parents=True, exist_ok=True)
    password_hash = appauth.hash_password(ADMIN_PASSWORD)

    setup_values = {
        "save_path": str(movie_dir),
        "series_path": str(series_dir),
        "tmdb_api_key": "rc3-upgrade-fixture",
        "ui_language": "de",
        "auth_username": ADMIN_USER,
        "auth_password_hash": password_hash,
        "deployment_mode": "desktop",
        "auto_download": True,
        "check_interval_min": 17,
        "dl_window_start": 1,
        "dl_window_end": 6,
    }
    _expect(bool(_call_supported(appconfig.save_initial_setup, setup_values)), "RC setup state did not persist")
    if not appconfig.load_auth().get("configured"):
        _expect(appconfig.save_auth(ADMIN_USER, password_hash), "RC auth state did not persist")

    _expect(appconfig.save_automation(True, 17, 1, 6), "RC automation state did not persist")
    updater_values = {
        "update_mode": getattr(appconfig, "UPDATE_MODE_MANUAL", "manual"),
        "auto_update_interval_hours": 9,
        "update_channel": "stable",
    }
    _expect(bool(_call_supported(appconfig.save_updater, updater_values)), "RC updater state did not persist")
    _expect(appconfig.save_queue([UPGRADE_SLUG]), "RC queue state did not persist")

    account = appconfig.load_auth()
    jobs, slugs = _load_queue_compat(appconfig)
    automation = appconfig.load_automation()
    updater = appconfig.load_updater()
    _expect(_auth_matches(appauth, account, ADMIN_PASSWORD), "RC auth cannot verify its stored password")
    _expect(slugs.count(UPGRADE_SLUG) == 1, "RC seed did not create exactly one queue entry")

    UPGRADE_MARKER.write_text(
        json.dumps(
            {
                "source_version": APP_VERSION,
                "username": account.get("username"),
                "queue_slug": UPGRADE_SLUG,
                "queue_job_id": (
                    str(next((j.get("job_id") for j in jobs if j.get("slug") == UPGRADE_SLUG), "") or "")
                ),
                "automation": automation,
                "updater": updater,
                "save_path": appconfig.load(),
                "series_path": appconfig.load_series_path(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"Upgrade soak seed {APP_VERSION}: PASS")


def verify_upgrade_current() -> None:
    """Verify old RC data on candidate code and through AppState restart loading."""
    import auth as appauth
    import config as appconfig
    import server
    from app_version import APP_VERSION

    marker = json.loads(UPGRADE_MARKER.read_text(encoding="utf-8"))
    account = appconfig.load_auth()
    jobs, slugs = _load_queue_compat(appconfig)

    _expect(marker.get("source_version") == "1.0.0-rc.3", "upgrade source was not RC3")
    _expect(appconfig.is_initialized(), "candidate no longer recognizes RC installation")
    _expect(account.get("username") == marker.get("username"), "upgrade changed account identity")
    _expect(_auth_matches(appauth, account, ADMIN_PASSWORD), "candidate cannot verify RC password")
    _expect_persisted_mapping(
        appconfig.load_automation(), marker.get("automation"), "upgrade automation",
    )
    _expect_persisted_mapping(
        appconfig.load_updater(), marker.get("updater"), "upgrade updater",
    )
    _expect(appconfig.load() == marker.get("save_path"), "upgrade changed movie path")
    _expect(appconfig.load_series_path() == marker.get("series_path"), "upgrade changed series path")
    _expect(slugs.count(UPGRADE_SLUG) == 1, "upgrade lost or duplicated durable queue entry")
    _expect(UPGRADE_SLUG in server.state.picked, "candidate AppState lost RC queue claim")
    _expect(
        list(server.state.queue_job_by_slug).count(UPGRADE_SLUG) == 1,
        "candidate AppState duplicated RC queue claim",
    )

    marker_job_id = str(marker.get("queue_job_id") or "")
    if marker_job_id:
        current = next((job for job in jobs if job.get("slug") == UPGRADE_SLUG), None)
        _expect(current is not None, "upgrade lost RC queue job")
        _expect(str(current.get("job_id") or "") == marker_job_id, "upgrade changed RC queue job id")

    print(f"Upgrade soak candidate {APP_VERSION}: PASS")


def verify_rollback_or_recovery_rc() -> None:
    """Verify the old RC can still read candidate-touched or restored persistent data."""
    import auth as appauth
    import config as appconfig
    from app_version import APP_VERSION

    marker = json.loads(UPGRADE_MARKER.read_text(encoding="utf-8"))
    account = appconfig.load_auth()
    _jobs, slugs = _load_queue_compat(appconfig)

    _expect(APP_VERSION == "1.0.0-rc.3", f"rollback verifier is not RC3: {APP_VERSION}")
    _expect(appconfig.is_initialized(), "RC rollback no longer recognizes installation")
    _expect(account.get("username") == marker.get("username"), "rollback changed account identity")
    _expect(_auth_matches(appauth, account, ADMIN_PASSWORD), "rollback cannot verify password")
    _expect_persisted_mapping(
        appconfig.load_automation(), marker.get("automation"), "rollback automation",
    )
    _expect_persisted_mapping(
        appconfig.load_updater(), marker.get("updater"), "rollback updater",
    )
    _expect(slugs.count(UPGRADE_SLUG) == 1, "rollback lost or duplicated queue data")
    _expect(appconfig.load() == marker.get("save_path"), "rollback changed movie path")
    _expect(appconfig.load_series_path() == marker.get("series_path"), "rollback changed series path")
    print(f"Rollback/recovery verifier {APP_VERSION}: PASS")


def main() -> None:
    modes = {
        "first-run-auth": first_run_auth_flow,
        "queue-seed": queue_seed_flow,
        "queue-restart-verify": queue_restart_verify_flow,
        "media-flow": media_integration_flow,
        "seed-upgrade-rc": seed_upgrade_rc,
        "verify-upgrade-current": verify_upgrade_current,
        "verify-rollback-rc": verify_rollback_or_recovery_rc,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in modes:
        print("usage: release_readiness_gate.py " + "|".join(sorted(modes)), file=sys.stderr)
        raise SystemExit(2)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    modes[sys.argv[1]]()


if __name__ == "__main__":
    main()
