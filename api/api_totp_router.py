"""Authenticated TOTP enrollment and recovery-code management."""
import base64
import io

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.profile_owner_guard import require_profile_owner
from api.totp_support import totp_error
from core.auth import MAX_PASSWORD_LENGTH
from core.totp import TotpError


class TotpBody(BaseModel):
    current_password: str = Field(default="", max_length=MAX_PASSWORD_LENGTH)
    otp_code: str = Field(default="", max_length=128)


def create_totp_router(dependencies, set_cookie):
    router = APIRouter(tags=["auth-setup"])
    guard = dependencies.appauth.LoginGuard(max_attempts=5, window_seconds=300, lockout_seconds=300)

    def user_context(request, body=None):
        user = dependencies.current_user(request.headers, request.cookies)
        if not user:
            raise HTTPException(401, "Anmeldung erforderlich.")
        require_profile_owner(request.headers, str(user["id"]))
        if dependencies.mfa is None:
            raise HTTPException(503, "2FA-Verwaltung nicht verfügbar.")
        if body is not None:
            key = str(user["id"])
            retry = guard.retry_after(key)
            if retry:
                raise HTTPException(429, "Zu viele Fehlversuche.", headers={"Retry-After": str(retry)})
            if not dependencies.verify_credentials(user["username"], body.current_password):
                guard.register_failure(key)
                raise HTTPException(403, "Das aktuelle Passwort ist falsch.")
            guard.register_success(key)
        return user

    def replacement(request, user, payload):
        user_id = str(user["id"])
        store = dependencies.session_store()
        store.revoke_user(user_id)
        mobile = request.url.path.startswith("/api/v1/")
        kind = dependencies.appauth.SESSION_KIND_MOBILE if mobile else dependencies.appauth.SESSION_KIND_WEB
        state = dependencies.user_store().mfa_state(user_id)
        token = store.create(label=request.headers.get("user-agent", "")[:120], kind=kind, user_id=user_id,
                             auth_epoch=state.get("epoch", "") if state.get("enabled") else "")
        payload["user"] = dependencies.user_store().public(dependencies.user_store().get(user_id))
        if mobile:
            payload.update(access_token=token, token_type="Bearer", expires_in=dependencies.appauth.DEFAULT_SESSION_TTL_SECONDS)
        response = JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        if not mobile:
            set_cookie(response, request, token)
        return response

    @router.get("/api/me/totp")
    @router.get("/api/v1/me/totp")
    def status(request: Request):
        user = user_context(request)
        return dependencies.mfa.status(str(user["id"]))

    @router.post("/api/me/totp/setup")
    @router.post("/api/v1/me/totp/setup")
    def setup(body: TotpBody, request: Request):
        user = user_context(request, body)
        try:
            payload = dependencies.mfa.begin(str(user["id"]), user["username"])
        except TotpError as exc:
            raise totp_error(exc) from exc
        # Generate locally: the seed is never sent to an external QR service.
        import qrcode
        import qrcode.image.svg
        image = qrcode.make(payload["otpauth_uri"], image_factory=qrcode.image.svg.SvgPathFillImage)
        output = io.BytesIO()
        image.save(output)
        payload["qr_data_url"] = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()
        return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @router.post("/api/me/totp/confirm")
    @router.post("/api/v1/me/totp/confirm")
    def confirm(body: TotpBody, request: Request):
        user = user_context(request, body)
        try:
            with dependencies.mfa.lock:
                codes = dependencies.mfa.confirm(str(user["id"]), body.otp_code)
                return replacement(request, user, {"enabled": True, "recovery_codes": codes})
        except TotpError as exc:
            raise totp_error(exc) from exc

    @router.post("/api/me/totp/disable")
    @router.post("/api/v1/me/totp/disable")
    def disable(body: TotpBody, request: Request):
        user = user_context(request, body)
        try:
            with dependencies.mfa.lock:
                dependencies.mfa.disable(str(user["id"]), body.otp_code)
                return replacement(request, user, {"enabled": False})
        except TotpError as exc:
            raise totp_error(exc) from exc

    @router.post("/api/me/totp/recovery-codes")
    @router.post("/api/v1/me/totp/recovery-codes")
    def recovery(body: TotpBody, request: Request):
        user = user_context(request, body)
        try:
            codes = dependencies.mfa.regenerate(str(user["id"]), body.otp_code)
        except TotpError as exc:
            raise totp_error(exc) from exc
        return JSONResponse({"recovery_codes": codes}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    return router
