"""Security and persistence regressions for the optional announcement channel."""
import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from application_services import announcements as service


@pytest.fixture
def announcement_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_db_path", lambda: tmp_path / "announcements.sqlite3")
    monkeypatch.setattr(service, "_last_poll", 0.0)
    key = Ed25519PrivateKey.generate()
    filename = tmp_path / "signing.pem"
    filename.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setattr(
        service, "PUBLIC_KEY_B64",
        base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    )
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PRIVATE_KEY_FILE", str(filename))
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_OWNER_USER_ID", "official-admin")
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PUBLISHER", "1")
    return key


def test_global_admin_requires_matching_signer_and_owner(announcement_runtime, monkeypatch):
    valid = {"id": "official-admin", "role": "admin", "enabled": True}
    other_admin = {"id": "another-admin", "role": "admin", "enabled": True}
    assert service.is_publisher_owner(valid)
    assert not service.is_publisher_owner(other_admin)
    assert not service.is_publisher_owner({"id": "official-admin", "role": "member", "enabled": True})
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PUBLISHER", "0")
    assert not service.publisher_ready()
    assert not service.is_publisher_owner(valid)
    with pytest.raises(PermissionError):
        service.publish("Title", "Content", "news")


def test_pinned_key_refuses_modified_and_forged_messages(announcement_runtime):
    payload = service.publish("Wichtig", "Offizielle Meldung", "important")
    item = service.feed()["items"][0]
    assert service.verify(item["payload"], item["signature"])
    forged = {**item["payload"], "body": "Gefälschter Inhalt"}
    assert not service.verify(forged, item["signature"])
    assert not service.verify(item["payload"], base64.b64encode(bytes(64)).decode())
    assert payload["revision"] == 1


def test_read_state_is_profile_scoped_and_revocation_signed(announcement_runtime):
    published = service.publish("Royal Event", "Neue Überraschung", "event")
    user_a = service.inbox("user-a")["items"]
    user_b = service.inbox("user-b")["items"]
    assert len(user_a) == len(user_b) == 1
    assert user_a[0]["read"] is False
    service.mark_read("user-a", published["id"])
    assert service.inbox("user-a")["items"][0]["read"] is True
    assert service.inbox("user-b")["items"][0]["read"] is False
    service.revoke(published["id"])
    signed = service.feed()["items"][0]
    assert signed["payload"]["revoked"]
    assert signed["payload"]["revision"] == 2
    assert service.verify(signed["payload"], signed["signature"])
    assert service.inbox("user-b")["items"] == []


def test_receiver_fail_closed_and_persistent_opt_out(announcement_runtime, monkeypatch):
    published = service.publish("Announcement", "Hello RD", "news")
    feed = service.feed()
    monkeypatch.setenv("ROYAL_ANNOUNCEMENTS_PUBLISHER", "0")
    service.set_enabled(False)
    assert service.inbox("user") == {"enabled": False, "items": []}
    service.set_enabled(True)
    assert service.enabled()
    monkeypatch.setattr(service, "_get_json", lambda path: feed)
    monkeypatch.setattr(service, "_post_receipt", lambda items: None)
    # Flush the publisher's temporary records; receiver has to authenticate
    # an external feed against the pinned key.
    with service._lock, service._connect() as db:
        db.execute("DELETE FROM messages")
        db.commit()
    assert service.inbox("user")["items"][0]["id"] == published["id"]
    # A forged higher revision must not erase the last verified copy.
    tampered = json.loads(json.dumps(feed))
    tampered["items"][0]["payload"]["body"] = "Injected"
    monkeypatch.setattr(service, "_get_json", lambda path: tampered)
    monkeypatch.setattr(service, "_last_poll", 0.0)
    assert service.inbox("user")["items"][0]["body"] == "Hello RD"


def test_receipt_counters_are_per_installation_and_profile(announcement_runtime):
    published = service.publish("Neue Version", "Test", "news")
    installation = "42e3c1d2-b5fa-49d6-a219-a4c4eeaa356f"
    profile_a, profile_b = "a" * 32, "b" * 32
    service.accept_receipts(installation, [
        {"id": published["id"], "profile": profile_a, "kind": "delivered"},
        {"id": published["id"], "profile": profile_a, "kind": "delivered"},
        {"id": published["id"], "profile": profile_b, "kind": "read"},
    ])
    service.accept_receipts(installation, [
        {"id": published["id"], "profile": profile_a, "kind": "read"},
    ])
    stats = service.statistics()[0]["stats"]
    assert stats["installations"] == 1
    assert stats["delivered_profiles"] == 2
    assert stats["read_profiles"] == 2
