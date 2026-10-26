"""Admin-only configuration downloads; anonymous short-lived instance proof."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr

from api.profile_owner_guard import require_profile_owner
from core.remote_access import PROOF_PATH, RemoteAccessError, RemoteAccessVerifier, bundle, plan


class DomainBody(BaseModel):
    domain: str = Field(max_length=512)
    service: str = Field(default="seriendownloader", max_length=64)


class BundleBody(DomainBody):
    token: SecretStr


class PrivateValidationRoute(APIRoute):
    """Do not echo a token-bearing request body in validation error details."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "Domain, Dienstname und Tunnel-Token prüfen.") from None

        return private_handler


def create_remote_access_router(current_user, verifier=None):
    verifier = verifier or RemoteAccessVerifier()
    router = APIRouter(tags=["remote-access"], route_class=PrivateValidationRoute)

    def administrator(request: Request):
        user = current_user(request.headers, request.cookies)
        if not user or user.get("role") != "admin" or user.get("setup_required"):
            raise HTTPException(403, "Eingerichtetes Administratorkonto erforderlich.")
        require_profile_owner(request.headers, str(user["id"]))
        return user

    @router.get(PROOF_PATH)
    def proof(request: Request, challenge: str = ""):
        value = verifier.proof(challenge, request.url.hostname or "") if len(challenge) <= 64 else None
        if not value:
            raise HTTPException(404, "Keine aktive Prüfung.")
        return JSONResponse({"proof": value}, headers={"Cache-Control": "no-store"})

    @router.post("/api/remote-access/plan", dependencies=[Depends(administrator)])
    def configuration(body: DomainBody, request: Request):
        try:
            return plan(body.domain, body.service, request.url.hostname or "")
        except RemoteAccessError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/remote-access/bundle", dependencies=[Depends(administrator)])
    def download(body: BundleBody, request: Request):
        try:
            content = bundle(plan(body.domain, body.service, request.url.hostname or ""), body.token.get_secret_value())
        except RemoteAccessError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(content, media_type="application/zip", headers={
            "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="royal-remote-access.zip"',
        })

    @router.post("/api/remote-access/verify", dependencies=[Depends(administrator)])
    async def verify(body: DomainBody):
        try:
            return await verifier.verify(body.domain)
        except RemoteAccessError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
