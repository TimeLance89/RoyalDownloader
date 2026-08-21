"""Authentication API routes.

The router owns HTTP request/response translation for web and native clients.
Credential storage, session state and application configuration are injected by
the composition root so this module stays independent from ``server.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from auth import MAX_PASSWORD_LENGTH, MAX_USERNAME_LENGTH


class LoginBody(BaseModel):
    username: str = Field(max_length=MAX_USERNAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class ApiV1LoginBody(LoginBody):
    device_label: str = Field(default="", max_length=120)
    # Early native prototypes used this additive alias.
    device_name: str = Field(default="", max_length=120)


class AuthConfigBody(BaseModel):
    username: str = Field(max_length=MAX_USERNAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    current_password: str | None = Field(default="", max_length=MAX_PASSWORD_LENGTH)


@dataclass(frozen=True)
class AuthDependencies:
    """Runtime collaborators supplied by the application composition root."""

    api_version: int
    appauth: Any
    appconfig: Any
    login_guard: Callable[[], Any]
    session_store: Callable[[], Any]
    client_key: Callable[[Request], str]
    auth_account: Callable[[], dict]
    auth_required: Callable[[], bool]
    auth_configured: Callable[[], bool]
    setup_required: Callable[[], bool]
    request_is_authenticated: Callable[..., bool]
    request_auth_method: Callable[..., str]
    verify_credentials: Callable[[str, str], bool]
    authenticated_web_token: Callable[[dict], str]
    authenticated_mobile_token: Callable[..., str]
    bearer_token: Callable[[Any], str]
    session_token: Callable[[dict], str]
    request_is_secure: Callable[[Request], bool]
    log: Callable[..., None]


def create_auth_router(dependencies: AuthDependencies) -> APIRouter:
    """Build the authentication router with no dependency on server globals."""
    router = APIRouter(tags=["auth-setup"])
    appauth = dependencies.appauth
    # The existing guard limits one source IP.  A second, account-wide budget
    # prevents distributed password guessing through many addresses while a
    # deliberately higher threshold avoids making a few typos a global DoS.
    account_login_guard = appauth.LoginGuard(
        max_attempts=20,
        window_seconds=15 * 60,
        lockout_seconds=15 * 60,
        max_tracked_keys=32,
    )

    def set_session_cookie(response: Response, request: Request, token: str) -> None:
        response.set_cookie(
            appauth.SESSION_COOKIE_NAME,
            token,
            max_age=appauth.DEFAULT_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=dependencies.request_is_secure(request),
            path="/",
        )

    def auth_status_payload(
        request: Request,
        auth_method: str | None = None,
    ) -> dict:
        account = dependencies.auth_account()
        configured = bool(account.get("configured"))
        authenticated = (
            dependencies.request_is_authenticated(
                request.headers,
                request.cookies,
                dependencies.client_key(request),
            )
            if auth_method is None
            else (not dependencies.auth_required() or auth_method != "none")
        )
        return {
            "configured": configured,
            "required": dependencies.auth_required(),
            "authenticated": authenticated,
            "username": (
                account.get("username", "")
                if authenticated or not configured
                else ""
            ),
            "source": account.get("source", "none"),
            "setup_required": dependencies.setup_required(),
            "prompt_setup": (
                dependencies.appconfig.is_initialized() and not configured
            ),
            "min_password_length": appauth.MIN_PASSWORD_LENGTH,
            "min_username_length": appauth.MIN_USERNAME_LENGTH,
        }

    async def create_login_session(
        username: str,
        password: str,
        request: Request,
        label: str,
        session_kind: str,
    ) -> tuple[str, dict, str]:
        key = dependencies.client_key(request)
        login_guard = dependencies.login_guard()
        account_key = "royal-admin"
        blocked_ip = login_guard.retry_after(key)
        blocked_account = account_login_guard.retry_after(account_key)
        blocked = max(blocked_ip, blocked_account)
        if blocked:
            raise HTTPException(
                429,
                f"Zu viele Fehlversuche. Bitte {blocked} Sekunden warten.",
                headers={"Retry-After": str(blocked)},
            )
        if not dependencies.auth_configured():
            raise HTTPException(400, "Es ist kein Konto eingerichtet.")
        ok = await run_in_threadpool(
            dependencies.verify_credentials,
            username.strip(),
            password,
        )
        if not ok:
            lockout_ip = login_guard.register_failure(key)
            lockout_account = account_login_guard.register_failure(account_key)
            lockout = max(lockout_ip, lockout_account)
            dependencies.log(f"Fehlgeschlagene Anmeldung von {key}.", "warn")
            if lockout:
                raise HTTPException(
                    429,
                    f"Zu viele Fehlversuche. Bitte {lockout} Sekunden warten.",
                    headers={"Retry-After": str(lockout)},
                )
            remaining = min(
                login_guard.remaining_attempts(key),
                account_login_guard.remaining_attempts(account_key),
            )
            raise HTTPException(
                401,
                f"Benutzername oder Passwort ist falsch. Noch {remaining} Versuch(e).",
            )
        login_guard.register_success(key)
        account_login_guard.register_success(account_key)
        session_label = str(label or "").strip()[:120]
        token = dependencies.session_store().create(
            label=session_label,
            kind=session_kind,
        )
        payload = auth_status_payload(request)
        payload.update({
            "authenticated": True,
            "username": dependencies.auth_account().get("username", ""),
        })
        dependencies.log("Anmeldung erfolgreich.")
        return token, payload, session_label

    async def save_auth_config(
        body: AuthConfigBody,
        request: Request,
        session_kind: str,
    ) -> tuple[str, str]:
        account = dependencies.auth_account()
        if bool(account.get("configured")):
            confirmed = await run_in_threadpool(
                dependencies.verify_credentials,
                account.get("username", ""),
                body.current_password or "",
            )
            if not confirmed:
                raise HTTPException(403, "Das aktuelle Passwort ist falsch.")
        try:
            username = appauth.validate_username(body.username)
            password = appauth.validate_password(body.password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        password_hash = await run_in_threadpool(appauth.hash_password, password)
        session_store = dependencies.session_store()
        session_store.revoke_all()
        saved = await run_in_threadpool(
            dependencies.appconfig.save_auth,
            username,
            password_hash,
        )
        if not saved:
            raise HTTPException(500, "Das Konto konnte nicht gespeichert werden.")
        default_label = (
            "Android" if session_kind == appauth.SESSION_KIND_MOBILE else ""
        )
        session_label = (
            request.headers.get("user-agent", "") or default_label
        )[:120]
        token = session_store.create(
            label=session_label,
            kind=session_kind,
        )
        return username, token

    @router.get("/api/auth/status")
    async def api_auth_status(request: Request):
        return JSONResponse(
            auth_status_payload(request),
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.get("/api/v1/auth/status")
    async def api_v1_auth_status(request: Request):
        auth_method = dependencies.request_auth_method(
            request.headers,
            request.cookies,
            dependencies.client_key(request),
            versioned=True,
            allow_basic=False,
        )
        payload = auth_status_payload(request, auth_method=auth_method)
        payload.update({
            "api_version": dependencies.api_version,
            "auth_method": auth_method,
            "token_ttl_seconds": appauth.DEFAULT_SESSION_TTL_SECONDS,
            "token_idle_timeout_seconds": appauth.DEFAULT_SESSION_IDLE_SECONDS,
        })
        return JSONResponse(
            payload,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/api/auth/login")
    async def api_auth_login(body: LoginBody, request: Request):
        token, payload, _label = await create_login_session(
            body.username,
            body.password,
            request,
            request.headers.get("user-agent", ""),
            appauth.SESSION_KIND_WEB,
        )
        response = JSONResponse(payload)
        set_session_cookie(response, request, token)
        return response

    @router.post("/api/v1/auth/login")
    async def api_v1_auth_login(body: ApiV1LoginBody, request: Request):
        requested_label = (
            body.device_label
            or body.device_name
            or request.headers.get("user-agent", "")
            or "API client"
        )
        token, payload, session_label = await create_login_session(
            body.username,
            body.password,
            request,
            requested_label,
            appauth.SESSION_KIND_MOBILE,
        )
        payload.update({
            "api_version": dependencies.api_version,
            "auth_method": "bearer",
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": appauth.DEFAULT_SESSION_TTL_SECONDS,
            "idle_timeout_seconds": appauth.DEFAULT_SESSION_IDLE_SECONDS,
            "device_label": session_label,
        })
        return JSONResponse(
            payload,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/api/auth/logout")
    async def api_auth_logout(request: Request):
        dependencies.session_store().revoke(
            dependencies.session_token(request.cookies),
            kind=appauth.SESSION_KIND_WEB,
        )
        response = JSONResponse({"ok": True})
        response.delete_cookie(appauth.SESSION_COOKIE_NAME, path="/")
        return response

    @router.post("/api/v1/auth/logout")
    async def api_v1_auth_logout(request: Request):
        token = dependencies.bearer_token(request.headers)
        revoked = int(bool(
            token
            and dependencies.session_store().revoke(
                token,
                kind=appauth.SESSION_KIND_MOBILE,
            )
        ))
        return JSONResponse({"ok": True, "revoked": revoked})

    @router.get("/api/auth/config")
    @router.get("/api/v1/auth/config")
    async def api_auth_config_get(request: Request):
        account = dependencies.auth_account()
        session_kind = (
            appauth.SESSION_KIND_MOBILE
            if request.url.path.startswith("/api/v1/")
            else appauth.SESSION_KIND_WEB
        )
        return {
            "configured": bool(account.get("configured")),
            "username": account.get("username", ""),
            "source": account.get("source", "none"),
            "active_sessions": dependencies.session_store().count(session_kind),
            "min_password_length": appauth.MIN_PASSWORD_LENGTH,
            "min_username_length": appauth.MIN_USERNAME_LENGTH,
        }

    @router.post("/api/auth/config")
    async def api_auth_config_set(body: AuthConfigBody, request: Request):
        username, token = await save_auth_config(
            body,
            request,
            appauth.SESSION_KIND_WEB,
        )
        response = JSONResponse({
            "ok": True,
            "configured": True,
            "username": username,
            "source": "settings",
            "active_sessions": dependencies.session_store().count(
                appauth.SESSION_KIND_WEB,
            ),
        })
        set_session_cookie(response, request, token)
        dependencies.log(f"Zugangsdaten aktualisiert (Benutzer „{username}“).")
        return response

    @router.post("/api/v1/auth/config")
    async def api_v1_auth_config_set(body: AuthConfigBody, request: Request):
        username, token = await save_auth_config(
            body,
            request,
            appauth.SESSION_KIND_MOBILE,
        )
        session_label = (
            request.headers.get("user-agent", "") or "Android"
        )[:120]
        dependencies.log(
            "Zugangsdaten über die Android-App aktualisiert "
            f"(Benutzer „{username}“).",
        )
        return {
            "ok": True,
            "configured": True,
            "username": username,
            "source": "settings",
            "active_sessions": dependencies.session_store().count(
                appauth.SESSION_KIND_MOBILE,
            ),
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": appauth.DEFAULT_SESSION_TTL_SECONDS,
            "device_label": session_label,
        }

    @router.post("/api/auth/sessions/revoke")
    async def api_auth_sessions_revoke(request: Request):
        session_store = dependencies.session_store()
        removed = session_store.revoke_all(
            keep_token=dependencies.authenticated_web_token(request.cookies),
            kind=appauth.SESSION_KIND_WEB,
        )
        dependencies.log(f"{removed} andere Sitzung(en) beendet.")
        return {
            "ok": True,
            "revoked": removed,
            "active_sessions": session_store.count(
                appauth.SESSION_KIND_WEB,
            ),
        }

    @router.post("/api/v1/auth/sessions/revoke")
    async def api_v1_auth_sessions_revoke(request: Request):
        keep_token = dependencies.authenticated_mobile_token(request.headers)
        session_store = dependencies.session_store()
        removed = session_store.revoke_all(
            keep_token=keep_token,
            kind=appauth.SESSION_KIND_MOBILE,
        )
        dependencies.log(f"{removed} andere Sitzung(en) beendet.")
        return {
            "ok": True,
            "revoked": removed,
            "active_sessions": session_store.count(
                appauth.SESSION_KIND_MOBILE,
            ),
            "current_session_preserved": bool(keep_token),
        }

    return router
