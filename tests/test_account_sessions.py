"""Owned session visibility, revocation and durable failure handling."""
import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.api_account_sessions_router import create_account_sessions_router
from core.auth import SESSION_KIND_MOBILE, SESSION_KIND_WEB, SessionPersistenceError, SessionStore


@pytest.fixture
def context(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    tokens = {"current": store.create(label="Chrome", user_id="a"),
              "other": store.create(label="TV", kind=SESSION_KIND_MOBILE, user_id="a"),
              "foreign": store.create(label="Private device", user_id="b")}
    def web(cookies):
        token = cookies.get("session", "")
        return token if store.validate(token, SESSION_KIND_WEB) else ""
    def mobile(headers):
        token = headers.get("authorization", "").removeprefix("Bearer ")
        return token if store.validate(token, SESSION_KIND_MOBILE) else ""
    def current(headers, cookies):
        token = mobile(headers) or web(cookies)
        owner = store.user_id(token)
        return {"id": owner, "role": "member"} if owner else None
    dependencies = SimpleNamespace(current_user=current, authenticated_web_token=web,
                                   authenticated_mobile_token=mobile, session_store=lambda: store)
    app = FastAPI()
    app.include_router(create_account_sessions_router(dependencies))
    with TestClient(app) as client:
        client.cookies.set("session", tokens["current"])
        yield store, tokens, client


def test_only_owned_sessions_are_visible_and_tokens_are_never_returned(context):
    store, tokens, client = context
    response = client.get("/api/me/sessions")
    assert response.status_code == 200
    rows = response.json()["sessions"]
    assert len(rows) == 2 and rows[0]["current"]
    assert {row["kind"] for row in rows} == {"web", "mobile"}
    for token in tokens.values():
        assert token not in response.text
        assert hashlib.sha256(token.encode()).hexdigest() not in response.text
    assert "Private device" not in response.text
    assert client.get("/api/me/sessions", headers={"X-Royal-Profile": "b"}).status_code == 409
    client.cookies.clear()
    assert client.get("/api/me/sessions").status_code == 401


def test_individual_revocation_keeps_current_and_other_users(context):
    store, tokens, client = context
    rows = client.get("/api/me/sessions").json()["sessions"]
    current = next(row for row in rows if row["current"])
    other = next(row for row in rows if not row["current"])
    assert client.delete("/api/me/sessions/" + current["id"]).status_code == 400
    foreign = store.list_for_user("b")[0]
    assert client.delete("/api/me/sessions/" + foreign["id"]).status_code == 404
    assert client.delete("/api/me/sessions/" + other["id"]).status_code == 200
    assert store.validate(tokens["current"]) and store.validate(tokens["foreign"])
    assert not store.validate(tokens["other"])
    assert client.delete("/api/me/sessions/" + other["id"]).status_code == 404


def test_bulk_revocation_covers_web_and_mobile_but_not_other_accounts(context):
    store, tokens, client = context
    extra = store.create(label="Other browser", user_id="a")
    result = client.post("/api/me/sessions/revoke-others").json()
    assert result["revoked"] == 2 and len(result["sessions"]) == 1
    assert result["sessions"][0]["current"]
    assert store.validate(tokens["foreign"]) and store.validate(tokens["current"])
    assert not store.validate(extra) and not store.validate(tokens["other"])


def test_mobile_can_preserve_itself_and_revoke_only_its_own_web_session(context):
    store, tokens, client = context
    client.cookies.clear()
    headers = {"Authorization": "Bearer " + tokens["other"], "X-Royal-Profile": "a"}
    response = client.post("/api/v1/me/sessions/revoke-others", headers=headers)
    assert response.status_code == 200
    assert response.json()["revoked"] == 1
    assert store.validate(tokens["other"]) and store.validate(tokens["foreign"])
    assert not store.validate(tokens["current"])


@pytest.mark.parametrize("bulk", [True, False])
def test_failed_persistence_is_reported_without_losing_session_state(context, monkeypatch, bulk):
    store, tokens, client = context
    target = next(row for row in store.list_for_user("a", tokens["current"]) if not row["current"])
    def failure():
        raise SessionPersistenceError("disk unavailable")
    monkeypatch.setattr(store, "_save_locked", failure)
    response = (client.post("/api/me/sessions/revoke-others") if bulk
                else client.delete("/api/me/sessions/" + target["id"]))
    assert response.status_code == 503
    assert store.validate(tokens["other"]) and store.validate(tokens["current"])


def test_session_references_remain_stable_after_restart_and_reject_invalid_input(tmp_path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    token = store.create(label="Browser", user_id="a")
    before = store.list_for_user("a", token)
    assert SessionStore(path).list_for_user("a", token) == before
    assert not store.revoke_for_user("é" * 64, "a")
    assert not store.revoke_for_user("0" * 64, "a")
