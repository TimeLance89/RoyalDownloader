"""Authenticated personal wishes; callers cannot specify an owner/Jellyfin ID."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool


class SavedMediaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=240)
    saved: bool


def create_saved_media_router(store, current_user, sync):
    router = APIRouter(tags=["personal-watchlist"])

    def owner(request):
        user = current_user(request.headers, request.cookies)
        if not user or not user.get("enabled", True):
            raise HTTPException(401, "Anmeldung erforderlich.")
        return user

    def payload(user):
        items = store.items(str(user["id"]))
        keys = {f"{item['media_type']}:{item['tmdb_id']}" for item in items}
        status = sync.status(user)
        return {"items": items, "sync": {**status, "ready": [key for key in status["ready"] if key in keys]}}

    @router.get("/api/me/saved-media")
    @router.get("/api/v1/me/saved-media")
    async def list_saved(request: Request):
        return await run_in_threadpool(payload, owner(request))

    @router.post("/api/me/saved-media")
    @router.post("/api/v1/me/saved-media")
    async def set_saved(body: SavedMediaBody, request: Request):
        user = owner(request)
        try:
            await run_in_threadpool(store.set, str(user["id"]), body.media_type, body.tmdb_id, body.title, body.saved)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Vormerkung konnte nicht gespeichert werden.") from exc
        sync.request()
        sync.tick()
        return await run_in_threadpool(payload, user)

    return router
