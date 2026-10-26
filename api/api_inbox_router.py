"""Profile-bound removal of inbox messages; never removes underlying work."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.profile_owner_guard import require_profile_owner


class DismissBody(BaseModel):
    keys: list[Annotated[str, Field(pattern=r"^(subscription|source|announcement|global):[a-f0-9]{32}$")]] = Field(min_length=1, max_length=500)


def create_inbox_router(store, current_user):
    def owner(request: Request):
        user = current_user(request.headers, request.cookies)
        if not user:
            raise HTTPException(401, "Anmeldung erforderlich.")
        require_profile_owner(request.headers, str(user["id"]))
        return str(user["id"])

    router = APIRouter(tags=["inbox"])

    @router.get("/api/inbox/dismissals")
    def keys(user_id=Depends(owner)):
        return {"keys": store.keys(user_id)}

    @router.post("/api/inbox/dismissals")
    def dismiss(body: DismissBody, user_id=Depends(owner)):
        try:
            store.dismiss(user_id, body.keys)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"dismissed": True}

    return router
