import asyncio
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import auth as appauth
import server


PASSWORD = "korrektes-passwort"


class MobileApiTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sessions_path = Path(self._tmp.name) / "sessions.json"
        self._store_backup = server.SESSION_STORE
        self._guard_backup = server.LOGIN_GUARD
        self._basic_guard_backup = server.BASIC_AUTH_GUARD
        server.SESSION_STORE = appauth.SessionStore(path=self.sessions_path)
        server.LOGIN_GUARD = appauth.LoginGuard()
        server.BASIC_AUTH_GUARD = appauth.LoginGuard()
        self.addCleanup(self._restore)
        self.account = {
            "username": "admin",
            "password_hash": appauth.hash_password(PASSWORD),
            "configured": True,
            "source": "settings",
        }
        account_patcher = patch(
            "server.appconfig.load_auth", side_effect=lambda: dict(self.account),
        )
        account_patcher.start()
        self.addCleanup(account_patcher.stop)
        init_patcher = patch("server.appconfig.is_initialized", return_value=True)
        init_patcher.start()
        self.addCleanup(init_patcher.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def _restore(self):
        server.SESSION_STORE = self._store_backup
        server.LOGIN_GUARD = self._guard_backup
        server.BASIC_AUTH_GUARD = self._basic_guard_backup

    def _login(self, label="Pixel 9"):
        return self.client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": PASSWORD,
                "device_label": label,
            },
        )

    @staticmethod
    def _bearer(token):
        return {"Authorization": f"Bearer {token}"}


class MobileCapabilityTests(MobileApiTestBase):
    def test_capabilities_and_health_are_public(self):
        capabilities = self.client.get("/api/v1/capabilities")
        self.assertEqual(capabilities.status_code, 200)
        payload = capabilities.json()
        self.assertEqual(payload["api_version"], 1)
        self.assertEqual(payload["supported_api_versions"], [1])
        self.assertTrue(payload["authentication"]["required"])
        self.assertIn("bearer", payload["authentication"]["methods"])
        self.assertTrue(payload["features"]["cover_proxy"])
        self.assertEqual(payload["websocket"]["path"], "/api/v1/ws")
        self.assertTrue(payload["websocket"]["authorization_header"])
        self.assertEqual(capabilities.headers["cache-control"], "no-store")
        self.assertEqual(capabilities.headers["x-content-type-options"], "nosniff")
        self.assertEqual(capabilities.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(
            capabilities.headers["content-security-policy"], "frame-ancestors 'self'",
        )
        self.assertNotIn("strict-transport-security", capabilities.headers)

        secure_capabilities = self.client.get(
            "/api/v1/capabilities", headers={"X-Forwarded-Proto": "https"},
        )
        self.assertEqual(
            secure_capabilities.headers["strict-transport-security"],
            "max-age=31536000",
        )

        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok", "api_version": 1})

        auth_status = self.client.get("/api/v1/auth/status")
        self.assertEqual(auth_status.headers["cache-control"], "no-store")

    def test_v1_core_routes_are_protected(self):
        response = self.client.get("/api/v1/queue")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "auth_required")
        self.assertEqual(
            self.client.post("/api/v1/auth/sessions/revoke").status_code,
            401,
        )

    def test_explicit_fail_closed_mode_protects_missing_account(self):
        self.account = {
            "username": "",
            "password_hash": "",
            "configured": False,
            "source": "none",
        }
        with patch.dict(server.os.environ, {"APP_REQUIRE_AUTH": "1"}):
            response = self.client.get("/api/queue")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "auth_required")

    def test_cloudflare_client_ip_requires_explicit_trust_and_validation(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="172.18.0.2"),
            headers={"cf-connecting-ip": "2001:0db8::1"},
        )
        with patch.dict(server.os.environ, {"TRUST_CLOUDFLARE_HEADERS": ""}):
            self.assertEqual(server.client_key(request), "172.18.0.2")
        with patch.dict(server.os.environ, {"TRUST_CLOUDFLARE_HEADERS": "1"}):
            self.assertEqual(server.client_key(request), "2001:db8::1")
            request.headers["cf-connecting-ip"] = "198.51.100.1, 203.0.113.2"
            self.assertEqual(server.client_key(request), "172.18.0.2")
            request.headers["cf-connecting-ip"] = "keine-ip"
            self.assertEqual(server.client_key(request), "172.18.0.2")

    def test_same_origin_requires_the_effective_https_scheme(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        rejected = self.client.post(
            "/api/queue/clear",
            json={},
            headers={
                "Origin": "http://testserver",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(rejected.status_code, 403)
        accepted = self.client.post(
            "/api/queue/clear",
            json={},
            headers={
                "Origin": "https://testserver",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(accepted.status_code, 200)

    def test_core_aliases_share_the_legacy_handlers(self):
        endpoints = {
            route.path: route.endpoint
            for route in server.app.routes
            if hasattr(route, "endpoint")
        }
        pairs = {
            "/api/genres": "/api/v1/genres",
            "/api/movies": "/api/v1/movies",
            "/api/movie/{slug:path}": "/api/v1/movie/{slug:path}",
            "/api/movies/preload": "/api/v1/movies/preload",
            "/api/tmdb/movie": "/api/v1/tmdb/movie",
            "/api/tmdb/movies": "/api/v1/tmdb/movies",
            "/api/jellyfin/matches": "/api/v1/jellyfin/matches",
            "/api/series": "/api/v1/series",
            "/api/series/load": "/api/v1/series/load",
            "/api/anime": "/api/v1/anime",
            "/api/anime/{anime_id}": "/api/v1/anime/{anime_id}",
            "/api/queue": "/api/v1/queue",
            "/api/queue/add": "/api/v1/queue/add",
            "/api/queue/remove": "/api/v1/queue/remove",
            "/api/queue/clear": "/api/v1/queue/clear",
            "/api/download/cancel": "/api/v1/download/cancel",
            "/api/watchlist": "/api/v1/watchlist",
            "/api/watchlist/add": "/api/v1/watchlist/add",
            "/api/watchlist/mode": "/api/v1/watchlist/mode",
            "/api/watchlist/remove": "/api/v1/watchlist/remove",
            "/api/watchlist/check": "/api/v1/watchlist/check",
            "/api/watchlist/open": "/api/v1/watchlist/open",
            "/api/cover": "/api/v1/cover",
            "/ws": "/api/v1/ws",
        }
        for legacy, versioned in pairs.items():
            self.assertIn(legacy, endpoints)
            self.assertIn(versioned, endpoints)
            self.assertIs(endpoints[legacy], endpoints[versioned])


class BearerAuthenticationTests(MobileApiTestBase):
    def test_cover_proxy_keeps_web_and_mobile_authentication_separate(self):
        with patch(
            "server._fetch_cover_data",
            return_value=(b"image-bytes", "image/png"),
        ):
            self.assertEqual(
                self.client.get("/api/v1/cover", params={"url": "https://example.com/a.png"}).status_code,
                401,
            )

            token = self._login().json()["access_token"]
            mobile = self.client.get(
                "/api/v1/cover",
                params={"url": "https://example.com/a.png"},
                headers=self._bearer(token),
            )
            self.assertEqual(mobile.status_code, 200)
            self.assertEqual(mobile.headers["content-type"], "image/png")

            self.client.post(
                "/api/auth/login", json={"username": "admin", "password": PASSWORD},
            )
            self.assertEqual(
                self.client.get("/api/cover", params={"url": "https://example.com/a.png"}).status_code,
                200,
            )
            self.assertEqual(
                self.client.get("/api/v1/cover", params={"url": "https://example.com/a.png"}).status_code,
                401,
            )

            self.client.cookies.clear()
            self.assertEqual(
                self.client.get(
                    "/api/cover",
                    params={"url": "https://example.com/a.png"},
                    headers=self._bearer(token),
                ).status_code,
                403,
            )

    def test_login_returns_bearer_and_persists_device_label(self):
        response = self._login("Mein Pixel")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(payload["auth_method"], "bearer")
        self.assertEqual(payload["device_label"], "Mein Pixel")
        self.assertTrue(payload["access_token"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(appauth.SESSION_COOKIE_NAME, response.cookies)

        stored = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        labels = {entry["label"] for entry in stored["sessions"].values()}
        self.assertEqual(labels, {"Mein Pixel"})
        kinds = {entry["kind"] for entry in stored["sessions"].values()}
        self.assertEqual(kinds, {appauth.SESSION_KIND_MOBILE})
        self.assertNotIn(payload["access_token"], self.sessions_path.read_text(encoding="utf-8"))

    def test_early_device_name_alias_is_accepted(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": PASSWORD,
                "device_name": "Früher Android-Prototyp",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["device_label"], "Früher Android-Prototyp")

    def test_login_rejects_oversized_credentials_before_password_hashing(self):
        with patch("server.verify_credentials") as verify:
            response = self.client.post(
                "/api/v1/auth/login",
                json={
                    "username": "admin",
                    "password": "x" * (appauth.MAX_PASSWORD_LENGTH + 1),
                },
            )
        self.assertEqual(response.status_code, 422)
        verify.assert_not_called()

    def test_bearer_authenticates_v1_and_legacy_rest_routes(self):
        token = self._login().json()["access_token"]
        headers = self._bearer(token)
        self.assertEqual(self.client.get("/api/v1/queue", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/queue", headers=headers).status_code, 200)

        status = self.client.get("/api/v1/auth/status", headers=headers).json()
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["auth_method"], "bearer")
        self.assertEqual(status["username"], "admin")

        admin_route = self.client.get("/api/auth/config", headers=headers)
        self.assertEqual(admin_route.status_code, 403)
        self.assertEqual(admin_route.json()["code"], "access_denied")

    def test_invalid_and_expired_bearer_are_rejected(self):
        self.assertEqual(
            self.client.get(
                "/api/v1/queue", headers=self._bearer("ungueltig"),
            ).status_code,
            401,
        )

        token = self._login().json()["access_token"]
        fingerprint = appauth._token_fingerprint(token)
        server.SESSION_STORE._sessions[fingerprint]["created"] = (
            time.time() - appauth.DEFAULT_SESSION_TTL_SECONDS - 1
        )
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(token)).status_code,
            401,
        )

    def test_logout_revokes_the_bearer(self):
        token = self._login().json()["access_token"]
        headers = self._bearer(token)
        response = self.client.post("/api/v1/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked"], 1)
        self.assertEqual(self.client.get("/api/v1/queue", headers=headers).status_code, 401)

    def test_revoke_other_sessions_keeps_the_calling_bearer(self):
        web_login = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        self.assertEqual(web_login.status_code, 200)
        mine = self._login("Telefon").json()["access_token"]
        other = self._login("Tablet").json()["access_token"]

        response = self.client.post(
            "/api/v1/auth/sessions/revoke", headers=self._bearer(mine),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked"], 1)
        self.assertTrue(response.json()["current_session_preserved"])
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(mine)).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(other)).status_code,
            401,
        )
        # Mobile-Geräteverwaltung beendet keine Browser-Sitzung.
        self.assertEqual(self.client.get("/api/queue").status_code, 200)

    def test_cookie_and_basic_remain_legacy_only(self):
        legacy_login = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        self.assertIn(appauth.SESSION_COOKIE_NAME, legacy_login.cookies)
        self.assertEqual(self.client.get("/api/queue").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/queue").status_code, 401)
        status = self.client.get("/api/v1/auth/status").json()
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["auth_method"], "none")

        self.client.cookies.clear()
        encoded = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
        self.assertEqual(
            self.client.get(
                "/api/queue", headers={"Authorization": f"Basic {encoded}"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/queue", headers={"Authorization": f"Basic {encoded}"},
            ).status_code,
            401,
        )

    def test_mobile_logout_does_not_revoke_web_cookie(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/login", json={"username": "admin", "password": PASSWORD},
            ).status_code,
            200,
        )
        token = self._login().json()["access_token"]
        response = self.client.post(
            "/api/v1/auth/logout", headers=self._bearer(token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked"], 1)
        self.assertEqual(self.client.get("/api/queue").status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(token)).status_code,
            401,
        )

    def test_web_session_revoke_does_not_revoke_mobile_tokens(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        server.SESSION_STORE.create("Anderer Browser")
        mobile = self._login().json()["access_token"]
        response = self.client.post("/api/auth/sessions/revoke")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked"], 1)
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(mobile)).status_code,
            200,
        )

    def test_password_change_revokes_web_and_mobile_sessions(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        mobile = self._login().json()["access_token"]
        with patch("server.appconfig.save_auth", return_value=True):
            response = self.client.post(
                "/api/auth/config",
                json={
                    "username": "admin",
                    "password": "neues-passwort",
                    "current_password": PASSWORD,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(mobile)).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/queue").status_code, 200)

    def test_logout_persistence_failure_returns_503_and_rolls_back(self):
        token = self._login().json()["access_token"]
        with patch.object(
            server.SESSION_STORE,
            "_save_locked",
            side_effect=appauth.SessionPersistenceError("Datenträger nicht verfügbar"),
        ):
            response = self.client.post(
                "/api/v1/auth/logout", headers=self._bearer(token),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "session_store_unavailable")
        self.assertEqual(
            self.client.get("/api/v1/queue", headers=self._bearer(token)).status_code,
            200,
        )

    def test_invalid_basic_auth_is_rate_limited_before_rehashing(self):
        encoded = base64.b64encode(b"admin:falsch").decode()
        headers = {"Authorization": f"Basic {encoded}"}
        with patch("server.verify_credentials", return_value=False) as verify:
            for _ in range(appauth.DEFAULT_MAX_ATTEMPTS + 1):
                self.assertEqual(
                    self.client.get("/api/queue", headers=headers).status_code,
                    401,
                )
        self.assertEqual(verify.call_count, appauth.DEFAULT_MAX_ATTEMPTS)


class CoverProxySecurityTests(MobileApiTestBase):
    def setUp(self):
        super().setUp()
        with server.state.cover_cache_lock:
            server.state.cover_cache.clear()
            server.state.cover_fail_cache.clear()
        self.addCleanup(self._clear_cover_caches)

    @staticmethod
    def _clear_cover_caches():
        with server.state.cover_cache_lock:
            server.state.cover_cache.clear()
            server.state.cover_fail_cache.clear()

    def test_redirect_to_private_network_is_rejected_before_second_request(self):
        response = SimpleNamespace(
            status_code=302,
            headers={"Location": "http://127.0.0.1/private"},
            primary_ip="93.184.216.34",
            close=Mock(),
        )
        curl_session = SimpleNamespace(get=Mock(return_value=response), close=Mock())
        manager = SimpleNamespace(
            _make_curl_session=Mock(return_value=curl_session),
            _browser_headers=Mock(return_value={}),
        )
        with (
            patch("server.get_fp_scraper", return_value=SimpleNamespace(session=manager)),
            patch(
                "server._safe_public_http_url",
                side_effect=lambda value: "127.0.0.1" not in value,
            ),
        ):
            result = server._fetch_cover_data("https://public.example/poster.jpg")

        self.assertIsNone(result)
        self.assertEqual(curl_session.get.call_count, 1)
        response.close.assert_called_once()
        curl_session.close.assert_called_once()

    def test_cover_log_target_removes_query_fragment_and_userinfo(self):
        target = server._cover_log_target(
            "https://user:secret@example.com/poster.jpg?token=secret#fragment",
        )
        self.assertEqual(target, "example.com/poster.jpg")
        self.assertNotIn("secret", target)


class MobileWebSocketTests(MobileApiTestBase):
    def test_v1_websocket_accepts_bearer_and_sends_initial_snapshot(self):
        token = self._login().json()["access_token"]
        with self.client.websocket_connect(
            "/api/v1/ws", headers=self._bearer(token),
        ) as websocket:
            snapshot = websocket.receive_json()
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(snapshot["api_version"], 1)
        self.assertEqual(snapshot["event_schema_version"], 1)
        self.assertIn("queue", snapshot)
        self.assertIn("watchlist", snapshot)
        self.assertIn("download", snapshot)

    def test_legacy_websocket_accepts_bearer_without_changing_its_protocol(self):
        token = self._login().json()["access_token"]
        with self.client.websocket_connect(
            "/ws", headers=self._bearer(token),
        ) as websocket:
            self.assertIsNotNone(websocket)

    def test_v1_websocket_rejects_web_cookie(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/v1/ws"):
                pass

    def test_legacy_websocket_rejects_foreign_cookie_origin(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/ws", headers={"Origin": "http://boeser-host"},
            ):
                pass

    def test_legacy_websocket_rejects_wrong_origin_scheme(self):
        self.client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD},
        )
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/ws",
                headers={
                    "Origin": "http://testserver",
                    "X-Forwarded-Proto": "https",
                },
            ):
                pass
        with self.client.websocket_connect(
            "/ws",
            headers={
                "Origin": "https://testserver",
                "X-Forwarded-Proto": "https",
            },
        ) as websocket:
            self.assertIsNotNone(websocket)

    def test_revoked_bearer_closes_an_existing_websocket(self):
        token = self._login().json()["access_token"]
        with patch.object(server, "WEBSOCKET_AUTH_RECHECK_SECONDS", 0.01):
            with self.client.websocket_connect(
                "/api/v1/ws", headers=self._bearer(token),
            ) as websocket:
                self.assertEqual(websocket.receive_json()["type"], "snapshot")
                server.SESSION_STORE.revoke(token)
                with self.assertRaises(WebSocketDisconnect) as closed:
                    websocket.receive_json()
                self.assertEqual(closed.exception.code, 1008)

    def test_client_messages_cannot_bypass_websocket_revocation(self):
        token = self._login().json()["access_token"]
        with patch.object(server, "WEBSOCKET_AUTH_RECHECK_SECONDS", 0.02):
            with self.client.websocket_connect(
                "/api/v1/ws", headers=self._bearer(token),
            ) as websocket:
                self.assertEqual(websocket.receive_json()["type"], "snapshot")
                server.SESSION_STORE.revoke(
                    token, kind=appauth.SESSION_KIND_MOBILE,
                )
                stop = threading.Event()
                closed = threading.Event()
                close_code = []

                def spam_messages():
                    try:
                        while not stop.is_set():
                            websocket.send_text("keepalive")
                            time.sleep(0.002)
                    except WebSocketDisconnect:
                        pass

                def wait_for_close():
                    try:
                        websocket.receive_json()
                    except WebSocketDisconnect as exc:
                        close_code.append(exc.code)
                        closed.set()

                sender = threading.Thread(target=spam_messages, daemon=True)
                receiver = threading.Thread(target=wait_for_close, daemon=True)
                sender.start()
                receiver.start()
                closed_while_sending = closed.wait(timeout=0.5)
                stop.set()
                sender.join(timeout=1)
                receiver.join(timeout=1)
                self.assertTrue(closed_while_sending)
                self.assertEqual(close_code, [1008])


class SessionPersistenceTests(unittest.TestCase):
    def test_hourly_activity_checkpoint_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            with patch("auth.time.time", return_value=1_000.0):
                store = appauth.SessionStore(
                    path=path,
                    ttl_seconds=10_000,
                    idle_seconds=10_000,
                )
                token = store.create(label="Telefon")

            with patch("auth.time.time", return_value=4_701.0):
                self.assertTrue(store.validate(token))

            persisted = json.loads(path.read_text(encoding="utf-8"))
            entry = next(iter(persisted["sessions"].values()))
            self.assertEqual(entry["last_seen"], 4_701.0)
            self.assertNotIn("_persisted_last_seen", entry)

            with patch("auth.time.time", return_value=4_702.0):
                reloaded = appauth.SessionStore(
                    path=path,
                    ttl_seconds=10_000,
                    idle_seconds=10_000,
                )
                self.assertTrue(reloaded.validate(token))

    def test_legacy_entries_load_as_web_sessions_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            token = "altes-browser-token"
            now = time.time()
            path.write_text(json.dumps({
                "version": 1,
                "sessions": {
                    appauth._token_fingerprint(token): {
                        "created": now,
                        "last_seen": now,
                        "label": "Alter Browser",
                    },
                },
            }), encoding="utf-8")
            store = appauth.SessionStore(path=path)
            self.assertTrue(store.validate(token, appauth.SESSION_KIND_WEB))
            self.assertFalse(store.validate(token, appauth.SESSION_KIND_MOBILE))

    def test_failed_mutations_are_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = appauth.SessionStore(path=Path(tmp) / "sessions.json")
            web = store.create("Browser", kind=appauth.SESSION_KIND_WEB)
            mobile = store.create("Telefon", kind=appauth.SESSION_KIND_MOBILE)
            with patch.object(
                store,
                "_save_locked",
                side_effect=appauth.SessionPersistenceError("voll"),
            ):
                with self.assertRaises(appauth.SessionPersistenceError):
                    store.create("Neues Telefon", kind=appauth.SESSION_KIND_MOBILE)
                with self.assertRaises(appauth.SessionPersistenceError):
                    store.revoke(mobile, kind=appauth.SESSION_KIND_MOBILE)
                with self.assertRaises(appauth.SessionPersistenceError):
                    store.revoke_all(kind=appauth.SESSION_KIND_WEB)
            self.assertEqual(store.count(), 2)
            self.assertTrue(store.validate(web, appauth.SESSION_KIND_WEB))
            self.assertTrue(store.validate(mobile, appauth.SESSION_KIND_MOBILE))

    def test_login_guard_bounds_rotating_client_state(self):
        guard = appauth.LoginGuard(max_tracked_keys=16)
        for index in range(100):
            guard.register_failure(f"198.51.100.{index}")
        self.assertLessEqual(len(guard._key_order), 16)
        self.assertLessEqual(len(guard._attempts), 16)
        self.assertLessEqual(len(guard._locked_until), 16)


class _FakeWebSocket:
    def __init__(self, *, fail_send: bool = False, block_send: bool = False):
        self.accepted = False
        self.sent = []
        self.closed = None
        self.fail_send = fail_send
        self.block_send = block_send
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.send_started.set()
        if self.fail_send:
            raise RuntimeError("Verbindung beendet")
        if self.block_send:
            await self.release_send.wait()
        self.sent.append(payload)

    async def close(self, code, reason):
        self.closed = (code, reason)
        self.release_send.set()


class WebSocketManagerTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_until(self, predicate, timeout=0.5):
        async def wait_loop():
            while not predicate():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_loop(), timeout=timeout)

    async def test_snapshot_and_broadcasts_are_serialized_in_order(self):
        manager = server.WSManager(queue_size=4)
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            initial_payload_factory=lambda: {"type": "snapshot", "sequence": 0},
        )
        manager.publish({"type": "queue_update", "sequence": 1})
        manager.publish({"type": "queue_update", "sequence": 2})
        await self._wait_until(lambda: len(websocket.sent) == 3)
        self.assertEqual(
            [payload["sequence"] for payload in websocket.sent], [0, 1, 2],
        )
        manager.disconnect(websocket)
        await asyncio.sleep(0)
        self.assertNotIn(websocket, manager.clients)

    async def test_failed_sender_is_removed(self):
        manager = server.WSManager(queue_size=2)
        websocket = _FakeWebSocket(fail_send=True)
        await manager.connect(websocket)
        manager.publish({"type": "queue_update"})
        await self._wait_until(lambda: websocket not in manager.clients)

    async def test_slow_client_is_closed_instead_of_dropping_events(self):
        manager = server.WSManager(queue_size=2)
        websocket = _FakeWebSocket(block_send=True)
        await manager.connect(websocket)
        manager.publish({"sequence": 1})
        await asyncio.wait_for(websocket.send_started.wait(), timeout=0.5)
        manager.publish({"sequence": 2})
        manager.publish({"sequence": 3})
        manager.publish({"sequence": 4})
        await self._wait_until(lambda: websocket.closed is not None)
        self.assertEqual(websocket.closed[0], 1013)
        self.assertNotIn(websocket, manager.clients)


if __name__ == "__main__":
    unittest.main()
