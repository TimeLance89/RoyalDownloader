"""Owned device sessions, with no bearer tokens exposed to the UI."""
from fastapi import APIRouter, HTTPException, Request

from api.profile_owner_guard import require_profile_owner
from core.auth import SessionPersistenceError


def create_account_sessions_router(dependencies):
    router = APIRouter(tags=["account-sessions"])

    def context(request):
        user = dependencies.current_user(request.headers, request.cookies)
        if not user:
            raise HTTPException(401, "Anmeldung erforderlich.")
        require_profile_owner(request.headers, str(user["id"]))
        token = (dependencies.authenticated_mobile_token(request.headers)
                 if request.url.path.startswith("/api/v1/") else dependencies.authenticated_web_token(request.cookies))
        store = dependencies.session_store()
        if not token or store.user_id(token) not in ("", str(user["id"])):
            raise HTTPException(401, "Eine gültige Sitzung dieses Kontos ist erforderlich.")
        return str(user["id"]), token, store

    @router.get("/api/me/sessions")
    @router.get("/api/v1/me/sessions")
    def sessions(request: Request):
        owner, token, store = context(request)
        return {"sessions": store.list_for_user(owner, token)}

    @router.delete("/api/me/sessions/{reference}")
    @router.delete("/api/v1/me/sessions/{reference}")
    def revoke(reference: str, request: Request):
        owner, token, store = context(request)
        try:
            if not store.revoke_for_user(reference, owner, token):
                raise HTTPException(404, "Sitzung nicht gefunden.")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionPersistenceError as exc:
            raise HTTPException(503, "Sitzungsänderung konnte nicht gespeichert werden.") from exc
        return {"revoked": True, "sessions": store.list_for_user(owner, token)}

    @router.post("/api/me/sessions/revoke-others")
    @router.post("/api/v1/me/sessions/revoke-others")
    def revoke_others(request: Request):
        owner, token, store = context(request)
        try:
            removed = store.revoke_user(owner, keep_token=token)
        except SessionPersistenceError as exc:
            raise HTTPException(503, "Sitzungsänderung konnte nicht gespeichert werden.") from exc
        return {"revoked": removed, "sessions": store.list_for_user(owner, token)}

    return router
