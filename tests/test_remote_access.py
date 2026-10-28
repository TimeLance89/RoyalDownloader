"""Generated NAS artifacts and hostile-domain verification boundaries."""
import asyncio
import base64
import io
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import zipfile

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_remote_access_router import create_remote_access_router
from api.api_security import SecurityDependencies, install_authentication_middleware, is_public_path
from core.remote_access import (
    PROOF_PATH, RemoteAccessError, RemoteAccessVerifier, bundle, fetch_public, plan,
    public_hostname, public_ips,
)


@pytest.mark.parametrize("domain", ["http://own.example.com", "https://user:pass@own.example.com", "localhost", "192.168.1.4", "127.0.0.1", "https://[::1]", "own.example.com:443", "own.example.com/path", "own.example.com?q=x", "*.example.com", "foo.local", "foo.internal", "https://own.example.com/#fragment", "foo..com", "-foo.example.com", "foo.example.com\nX-Evil: yes"])
def test_reject_non_public_or_ambiguous_names(domain):
    with pytest.raises(RemoteAccessError):
        public_hostname(domain)


def test_normalizes_own_domain_and_idna():
    assert public_hostname(" https://Royal.Example.com/ ") == "royal.example.com"
    assert public_hostname("royal.bücher.de") == "royal.xn--bcher-kva.de"


def test_bundle_preserves_mounts_and_lan_without_broad_proxy_trust(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "*,old.example.com;nas.local,192.168.1.8")
    monkeypatch.setenv("PORT", "9876")
    config = plan("royal.example.com", "royal", "192.168.1.9")
    token = "test-tunnel-token-" * 5
    raw = bundle(config, token)
    assert token not in str(config)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("cloudflare-tunnel.token").decode().strip() == token
        assert archive.getinfo("cloudflare-tunnel.token").external_attr >> 16 & 0o777 == 0o600
        compose_text = archive.read("docker-compose.remote.yml").decode()
        assert token not in compose_text
        compose = yaml.safe_load(compose_text)
        royal = compose["services"]["royal"]
        assert set(royal) == {"environment"}  # no replacement mounts, ports or image
        env = royal["environment"]
        assert env["ROYAL_TRUSTED_PROXIES"] == "127.0.0.1/32,::1/128"
        assert env["TRUST_CLOUDFLARE_HEADERS"] == "true"
        assert "*" not in env["ROYAL_ALLOWED_HOSTS"]
        assert all(host in env["ROYAL_ALLOWED_HOSTS"] for host in ["royal.example.com", "192.168.1.9", "nas.local", "old.example.com"])
        tunnel = compose["services"]["cloudflare-tunnel"]
        assert tunnel["network_mode"] == "service:royal"
        assert tunnel["read_only"] and tunnel["cap_drop"] == ["ALL"]
        assert tunnel["command"][-2:] == ["--token-file", "/run/secrets/cloudflare_tunnel_token"]
        assert "volumes" not in tunnel and "ports" not in tunnel
        assert "http://127.0.0.1:9876" in archive.read("README.txt").decode()


@pytest.mark.parametrize("service", ["cloudflare-tunnel", "x;whoami", "../royal", "royal\nservices:", ""])
def test_no_compose_or_shell_service_injection(service):
    with pytest.raises(RemoteAccessError):
        plan("royal.example.com", service)


@pytest.mark.parametrize("token", ["", "x" * 8193, "docker run --token " + "x" * 40, "x" * 50 + "\nwhoami", "x'$(whoami)" * 10])
def test_opaque_tokens_not_commands(token):
    with pytest.raises(RemoteAccessError):
        bundle(plan("royal.example.com", "seriendownloader"), token)


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["fd00::1"], ["1.1.1.1", "192.168.1.1"], []])
def test_dns_must_contain_only_public_ips(monkeypatch, addresses):
    monkeypatch.setattr("core.remote_access.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, (ip, 443)) for ip in addresses])
    with pytest.raises(RemoteAccessError):
        public_ips("royal.example.com")


def verifier_fixture(*, bad_proof=False, auth=None, api_status=401, status=200):
    calls = []
    def fetch(host, ip, path):
        calls.append((host, ip, path))
        if path.startswith(PROOF_PATH):
            challenge = parse_qs(urlsplit(path).query)["challenge"][0]
            return status, {"proof": challenge if bad_proof else verifier.proof(challenge, host)}
        if path == "/api/auth/status":
            return 200, auth if auth is not None else {"configured": True, "required": True, "authenticated": False}
        return api_status, {}
    verifier = RemoteAccessVerifier(fetch=fetch, resolve=lambda host: ["1.1.1.1"], clock=lambda: 100)
    return verifier, calls


def test_confirms_own_installation_and_guards_not_merely_any_royal_site():
    verifier, calls = verifier_fixture()
    try:
        result = asyncio.run(verifier.verify("royal.example.com"))
        assert result["verified"] and result["url"] == "https://royal.example.com"
        assert b"<svg" in base64.b64decode(result["qr_data_url"].split(",")[1])
        assert len(calls) == 3 and all(call[:2] == ("royal.example.com", "1.1.1.1") for call in calls)
        assert not verifier.proofs
        with pytest.raises(RemoteAccessError, match="Prüfung"):
            asyncio.run(verifier.verify("royal.example.com"))
    finally:
        verifier.close()


@pytest.mark.parametrize("kwargs", [{"bad_proof": True}, {"status": 302}, {"status": 403}, {"auth": {"configured": False, "required": False}}, {"auth": {"configured": True, "required": True, "authenticated": True}}, {"api_status": 200}, {"api_status": 302}])
def test_wrong_site_access_redirect_or_missing_login_never_pass(kwargs):
    verifier, _ = verifier_fixture(**kwargs)
    try:
        with pytest.raises(RemoteAccessError):
            asyncio.run(verifier.verify("royal.example.com"))
        assert not verifier.proofs
    finally:
        verifier.close()


def test_proof_is_short_lived_and_not_nonce_echo():
    clock = [100]
    verifier = RemoteAccessVerifier(clock=lambda: clock[0])
    try:
        verifier.proofs["challenge"] = ("different-secret-proof", 130, "royal.example.com")
        assert verifier.proof("challenge", "royal.example.com") == "different-secret-proof"
        assert verifier.proof("unknown", "royal.example.com") is None
        assert verifier.proof("challenge", "other.example.com") is None
        clock[0] = 130
        assert verifier.proof("challenge", "royal.example.com") is None
    finally:
        verifier.close()


def test_single_outstanding_dns_job_prevents_worker_exhaustion():
    release, entered = threading.Event(), threading.Event()
    def resolve(host):
        entered.set()
        release.wait(5)
        return ["127.0.0.1"]
    verifier = RemoteAccessVerifier(resolve=resolve)
    async def exercise():
        first = asyncio.create_task(verifier.verify("royal.example.com"))
        await asyncio.to_thread(entered.wait, 2)
        with pytest.raises(RemoteAccessError, match="Prüfung"):
            await verifier.verify("other.example.com")
        release.set()
        with pytest.raises(RemoteAccessError, match="öffentliche"):
            await first
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        verifier.close()


def test_fetch_pins_ip_and_certificate_hostname_without_redirects(monkeypatch):
    record = {}
    class Reply:
        status = 200
        def read(self, size):
            assert size == 16385
            return b'{"proof":"example"}'
        def close(self):
            record["closed"] = True
    class Pool:
        def __init__(self, ip, **kwargs):
            record.update(ip=ip, **kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def request(self, method, path, **kwargs):
            record.update(method=method, path=path, **kwargs)
            return Reply()
    monkeypatch.setattr("core.remote_access.urllib3.HTTPSConnectionPool", Pool)
    assert fetch_public("royal.example.com", "1.1.1.1", "/proof") == (200, {"proof": "example"})
    assert record["ip"] == "1.1.1.1"
    assert record["server_hostname"] == record["assert_hostname"] == "royal.example.com"
    assert record["cert_reqs"] == "CERT_REQUIRED"
    assert not record["redirect"] and not record["retries"]
    assert record["headers"] == {"Host": "royal.example.com", "Accept": "application/json"}
    assert record["closed"]


def test_router_admin_profile_binding_secret_cleanup_and_public_proof():
    user = {"id": "owner", "role": "member"}
    verifier, _ = verifier_fixture()
    app = FastAPI()
    app.include_router(create_remote_access_router(lambda headers, cookies: user, verifier))
    try:
        with TestClient(app) as client:
            body = {"domain": "royal.example.com"}
            assert client.post("/api/remote-access/plan", json=body).status_code == 403
            user["role"] = "admin"
            assert client.post("/api/remote-access/plan", json=body, headers={"X-Royal-Profile": "other"}).status_code == 409
            assert client.post("/api/remote-access/plan", json=body, headers={"X-Royal-Profile": "owner"}).status_code == 200
            token = "test-tunnel-token-" * 5
            response = client.post("/api/remote-access/bundle", json={**body, "token": token})
            assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
            assert response.headers["cache-control"] == "no-store"
            invalid = client.post("/api/remote-access/bundle", json={**body, "token": token + "\nbad"})
            assert invalid.status_code == 400 and token not in invalid.text
            malformed = client.post("/api/remote-access/bundle", json={"token": token})
            assert malformed.status_code == 422 and token not in malformed.text
            assert client.get(PROOF_PATH + "?challenge=guess").status_code == 404
            verifier.proofs["challenge"] = ("proof", 130, "testserver")
            assert client.get(PROOF_PATH + "?challenge=challenge").json() == {"proof": "proof"}
            assert is_public_path(PROOF_PATH, "GET", lambda: False)
            assert not is_public_path(PROOF_PATH, "POST", lambda: False)
            assert not is_public_path("/api/remote-access/bundle", "POST", lambda: True)
    finally:
        verifier.close()


def test_real_middleware_blocks_anonymous_and_cross_origin_bundle_requests(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "testserver")
    verifier, _ = verifier_fixture()
    app = FastAPI()
    user = {"id": "owner", "role": "admin"}
    app.include_router(create_remote_access_router(lambda h, c: user, verifier))
    install_authentication_middleware(app, SecurityDependencies(
        setup_required=lambda: False,
        request_is_authenticated=lambda h, c, *a, **k: h.get("authorization") == "Bearer fixture-session",
        authenticated_mobile_token=lambda *a, **k: "", bearer_token=lambda h: "",
        session_token=lambda c: "", client_key=lambda r: "peer",
        request_is_secure=lambda r: True, public_translate_limiter=SimpleNamespace(allow=lambda key: True),
    ))
    try:
        with TestClient(app, base_url="https://testserver") as client:
            body = {"domain": "royal.example.com", "token": "test-tunnel-token-" * 5}
            assert client.post("/api/remote-access/bundle", json=body).status_code == 401
            headers = {"authorization": "Bearer fixture-session", "Origin": "https://foreign.example.com"}
            assert client.post("/api/remote-access/bundle", json=body, headers=headers).status_code == 403
            headers["Origin"] = "https://testserver"
            allowed = client.post("/api/remote-access/bundle", json=body, headers=headers)
            assert allowed.status_code == 200 and allowed.headers["cache-control"] == "no-store"
            assert client.get(PROOF_PATH + "?challenge=unknown").status_code == 404
            assert client.post(PROOF_PATH).status_code == 401
    finally:
        verifier.close()
