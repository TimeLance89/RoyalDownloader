"""RFC vectors, restart/replay safety, recovery and durable failure handling."""
import base64
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.totp import TotpService, TotpError, totp
from core.users import UserStore


@pytest.mark.parametrize(("timestamp", "expected"), [(59, "94287082"), (1111111109, "07081804"),
    (1111111111, "14050471"), (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")])
def test_rfc6238_sha1_vectors(timestamp, expected):
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp(secret, timestamp // 30, 8) == expected


@pytest.fixture
def state(tmp_path):
    clock = [1_800_000_001]
    users = UserStore(tmp_path / "users.json", {"configured": True, "username": "royal", "password_hash": "hash"})
    service = TotpService(users, clock=lambda: clock[0])
    return users, service, clock, "admin-legacy"


def enroll(state):
    users, service, clock, uid = state
    setup = service.begin(uid, "royal")
    codes = service.confirm(uid, totp(setup["secret"], clock[0] // 30))
    return setup["secret"], codes


def test_setup_is_pending_encrypted_and_never_exposed_in_public_user(state):
    users, service, clock, uid = state
    setup = service.begin(uid, "royal")
    assert not service.enabled(uid)
    assert service.status(uid)["pending"]
    assert "otpauth://totp/" in setup["otpauth_uri"] and "issuer=RoyalDownloader" in setup["otpauth_uri"]
    assert setup["secret"] not in users._path.read_text()
    assert "mfa" not in users.public(users.get(uid))
    clock[0] += 601
    with pytest.raises(TotpError, match="abgelaufen"):
        service.confirm(uid, "123456")
    assert not service.enabled(uid)


def test_replay_and_recovery_codes_stay_consumed_after_restart(state):
    users, service, clock, uid = state
    secret, codes = enroll(state)
    with pytest.raises(TotpError):
        service.verify(uid, totp(secret, clock[0] // 30))  # Enrollment consumed it.
    clock[0] += 30
    epoch = service.verify(uid, totp(secret, clock[0] // 30))
    service.verify(uid, codes[0])
    serialized = users._path.read_text()
    assert secret not in serialized and codes[0] not in serialized
    restored = TotpService(UserStore(users._path, {}), clock=lambda: clock[0])
    assert restored.users.mfa_state(uid)["epoch"] == epoch
    assert restored.status(uid)["recovery_codes_remaining"] == 9
    for code in [totp(secret, clock[0] // 30), codes[0]]:
        with pytest.raises(TotpError): restored.verify(uid, code)
    restored.verify(uid, codes[1])


def test_parallel_requests_cannot_reuse_same_code(state):
    _, service, clock, uid = state
    secret, _ = enroll(state)
    clock[0] += 30
    def attempt(_):
        try:
            service.verify(uid, totp(secret, clock[0] // 30)); return True
        except TotpError: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1


def test_account_wide_budget_applies_across_code_entry_routes(state):
    _, service, clock, uid = state
    secret, _ = enroll(state)
    clock[0] += 30
    good = totp(secret, clock[0] // 30)
    for _ in range(5):
        with pytest.raises(TotpError): service.verify(uid, "not-a-code")
    with pytest.raises(TotpError) as blocked: service.verify(uid, good)
    assert blocked.value.status == 429 and blocked.value.retry_after > 0


def test_persistence_failure_does_not_consume_factor_or_enable_in_memory(state, monkeypatch):
    users, service, clock, uid = state
    setup = service.begin(uid, "royal")
    save = users._save
    def fail(): raise OSError("disk unavailable")
    monkeypatch.setattr(users, "_save", fail)
    with pytest.raises(TotpError) as failure: service.confirm(uid, totp(setup["secret"], clock[0] // 30))
    assert failure.value.status == 503
    assert not service.enabled(uid)
    monkeypatch.setattr(users, "_save", save)
    codes = service.confirm(uid, totp(setup["secret"], clock[0] // 30))
    monkeypatch.setattr(users, "_save", fail)
    with pytest.raises(TotpError): service.verify(uid, codes[0])
    assert service.status(uid)["recovery_codes_remaining"] == 10
    monkeypatch.setattr(users, "_save", save)
    service.verify(uid, codes[0])


def test_missing_key_does_not_reset_existing_mfa_and_recovery_still_works(state):
    users, service, clock, uid = state
    secret, codes = enroll(state)
    service.key_path.unlink()
    clock[0] += 30
    with pytest.raises(TotpError) as unavailable: service.verify(uid, totp(secret, clock[0] // 30))
    assert unavailable.value.status == 503 and service.enabled(uid)
    other = users.create("Other", "other", "member")
    with pytest.raises(TotpError): service.begin(other["id"], "other")
    assert not service.key_path.exists()
    service.disable(uid, codes[0])
    assert not service.enabled(uid)


def test_regeneration_replaces_all_old_codes_and_rotation_changes_epoch(state):
    users, service, clock, uid = state
    _, old = enroll(state)
    epoch = users.mfa_state(uid)["epoch"]
    new = service.regenerate(uid, old[0])
    assert len(new) == 10 and set(new).isdisjoint(old)
    with pytest.raises(TotpError): service.verify(uid, old[1])
    service.disable(uid, new[0])
    enroll(state)
    assert users.mfa_state(uid)["epoch"] != epoch
    assert json.loads(users._path.read_text())["users"][0]["mfa"]["enabled"]
