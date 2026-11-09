"""Authenticated, profile-scoped segment metadata for current and future clients."""

from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import JSONResponse

from api.playback_access import PlaybackAccess
from application_services.media_segments import MediaSegments, SegmentError
from integrations.jellyfin_saved import jellyfin_id
from integrations.media_center import profile_identity, validate_server_url


@dataclass(frozen=True)
class _Context:
    owner: str
    role: str
    base_url: str
    api_key: str = field(repr=False)
    generation: int
    profile_id: str


def create_media_segments_router(backend, *, service=None):
    service = service if service is not None else MediaSegments()
    access = PlaybackAccess(backend, None)
    router = APIRouter(tags=["media-segments"])

    def owner(request: Request):
        request.state.playback_context = access.snapshot(request)
        user = backend.current_user(request.headers, request.cookies)
        if not user or not user.get("enabled", True):
            raise HTTPException(401, "Anmeldung erforderlich.")
        if user.get("role") not in ("admin", "member"):
            raise HTTPException(403, "Kein Zugriff auf Medienmetadaten.")
        return user

    def context(user):
        with backend.state.jellyfin_cache_lock:
            config = dict(backend.state.jellyfin_cfg)
            generation = backend.state.jellyfin_config_generation
        if config.get("provider", "jellyfin") != "jellyfin":
            raise SegmentError(503, "provider_unsupported", "Segmentdaten benötigen Jellyfin.", "unsupported")
        if not config.get("url") or not config.get("api_key"):
            raise SegmentError(503, "jellyfin_not_configured", "Jellyfin ist nicht eingerichtet.", "unavailable")
        try:
            base_url = validate_server_url(config["url"])
        except ValueError:
            raise SegmentError(503, "jellyfin_not_configured", "Die Jellyfin-Verbindung ist ungültig.", "unavailable") from None
        profile_id, _ = profile_identity(user, config)
        if not profile_id and user.get("id") == "admin-legacy":
            profile_id = config.get("user_id")
        try:
            profile_id = jellyfin_id(profile_id)
        except (ValueError, TypeError, AttributeError):
            raise SegmentError(403, "profile_required", "Verknüpfe dein Jellyfin-Profil.") from None
        return _Context(str(user["id"]), user["role"], base_url, str(config["api_key"]), generation, profile_id)

    def read(request, item_id, user, *, refresh=False):
        try:
            binding = access.context(request)
            before = context(user)
            result = service.read(before.base_url, before.api_key, before.generation, before.profile_id,
                                  item_id.hex, refresh=refresh)
            # A connection/profile change during network I/O must not return data
            # prepared for the previous identity, even when it came from cache.
            try:
                access.assert_current(request, binding)
                unchanged = context(owner(request)) == before
            except (SegmentError, HTTPException):
                unchanged = False
            if not unchanged:
                raise HTTPException(409, {"code": "media_context_changed", "message": "Medienserver oder Profil wurde geändert. Erneut versuchen."})
        except SegmentError as error:
            result = error.result
        return JSONResponse(result.payload(item_id.hex), status_code=result.http_status,
                            headers={"Cache-Control": "no-store"})

    owner_dependency = Annotated[dict, Depends(owner)]

    @router.get("/api/media-center/items/{item_id}/segments")
    @router.get("/api/v1/media-center/items/{item_id}/segments")
    def segments(request: Request, item_id: UUID, user: owner_dependency):
        return read(request, item_id, user)

    @router.post("/api/media-center/items/{item_id}/segments/refresh")
    @router.post("/api/v1/media-center/items/{item_id}/segments/refresh")
    def refresh_segments(request: Request, item_id: UUID, user: owner_dependency):
        if user["role"] != "admin":
            raise HTTPException(403, "Administratorrechte zum Aktualisieren erforderlich.")
        return read(request, item_id, user, refresh=True)

    return router
