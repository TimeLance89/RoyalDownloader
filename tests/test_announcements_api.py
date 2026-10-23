"""The local RD administrator is never automatically a global publisher."""
import base64
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from api.api_announcements_router import create_announcements_router
from application_services import announcements


def test_publish_routes_require_official_host_exact_owner_and_correct_signer(monkeypatch, tmp_path):
    monkeypatch.setattr(announcements, "_db_path", lambda: tmp_path / "notices.sqlite3")
    key = Ed25519PrivateKey.generate()
    filename = tmp_path / "publisher.pem"
    filename.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setattr(
        announcements, "PUBLIC_KEY_B64",
        base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
    )
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PUBLISHER", "1")
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_OWNER_USER_ID", "the-owner")
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PRIVATE_KEY_FILE", str(filename))

    def current_user(headers, cookies):
        return {"id": headers.get("x-test-user", "other-admin"), "role": "admin", "enabled": True}

    app = FastAPI()
    app.include_router(create_announcements_router(current_user))
    client = TestClient(app, base_url="https://royal-downloader.de")
    payload = {"title": "Royal Event", "body": "Ein Test", "category": "event"}
    authorized = {"x-test-user": "the-owner", "host": "royal-downloader.de"}

    assert client.post("/api/announcements/admin/messages", json=payload).status_code == 403
    assert client.post("/api/announcements/admin/messages", json=payload,
                       headers={"x-test-user": "the-owner", "host": "evil.example"}).status_code == 403
    assert client.get("/api/announcements/admin/status", headers=authorized).json() == {"can_publish": True}

    sent = client.post("/api/announcements/admin/messages", json=payload, headers=authorized)
    assert sent.status_code == 200
    message_id = sent.json()["id"]
    assert uuid.UUID(message_id)
    signed = client.get("/api/public/announcements/feed").json()["items"][0]
    assert announcements.verify(signed["payload"], signed["signature"])
    assert signed["payload"]["title"] == "Royal Event"

    # Read endpoint belongs to each local profile; publishing authorization is separate.
    assert client.post("/api/announcements/" + message_id + "/read",
                       headers={"x-test-user": "other-admin"}).status_code == 200
    assert client.get("/api/announcements", headers={"x-test-user": "other-admin"}).json()["items"][0]["read"]

    assert client.post("/api/announcements/admin/messages/" + message_id + "/revoke",
                       headers={"x-test-user": "other-admin"}).status_code == 403
    assert client.post("/api/announcements/admin/messages/" + message_id + "/revoke",
                       headers=authorized).status_code == 200
    assert client.get("/api/public/announcements/feed").json()["items"][0]["payload"]["revoked"] is True

    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PRIVATE_KEY_FILE", str(tmp_path / "missing.pem"))
    assert client.get("/api/announcements/admin/status", headers=authorized).json() == {"can_publish": False}
    assert client.post("/api/announcements/admin/messages", json=payload, headers=authorized).status_code == 403
