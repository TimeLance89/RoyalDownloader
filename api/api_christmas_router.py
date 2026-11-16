"""Christmas discovery with server-side door release dates and profile isolation."""
import logging
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import core.config as appconfig
from api.profile_owner_guard import require_profile_owner
from features.christmas import ChristmasService, christmas_evidence, daily_selection
from integrations.jellyfin_saved import jellyfin_id
from integrations.jellyfin_permissions import require_jellyfin_profile
from integrations.media_center import media_client, profile_identity

logger = logging.getLogger(__name__)


def christmas_episodes(backend, user):
    with backend.state.jellyfin_cache_lock:
        config = dict(backend.state.jellyfin_cfg)
    if config.get("provider", "jellyfin") != "jellyfin" or not config.get("url") or not config.get("api_key"):
        return []
    profile, _ = profile_identity(user, config)
    if not profile:
        return []
    client = media_client(config, timeout=6)
    require_jellyfin_profile(client.media_segment_user(profile), profile)
    found = {}
    # Name and tag searches are bounded and use the viewer's library visibility.
    for field, word in (("SearchTerm", "weihnacht"), ("SearchTerm", "christmas"),
                        ("SearchTerm", "xmas"), ("Tags", "Christmas"), ("Tags", "Weihnachten")):
        payload = client._saved_request("GET", f"/Users/{jellyfin_id(profile)}/Items", params={
            "Recursive": "true", "IncludeItemTypes": "Episode", "Limit": 100,
            "ExcludeLocationTypes": "Virtual,Offline", "IsMissing": "false",
            "IsPlaceHolder": "false", "Fields": "Overview,Tags", field: word,
        })
        for raw in payload.get("Items") or []:
            evidence = christmas_evidence(raw)
            if raw.get("Type") != "Episode" or not evidence:
                continue
            identity = jellyfin_id(raw["Id"])
            found[identity] = {
                "id": identity, "kind": "episode", "seasonal_kind": "episode",
                "title": raw.get("SeriesName") or raw["Name"], "series_title": raw.get("SeriesName"),
                "episode_title": raw["Name"], "season": raw.get("ParentIndexNumber"),
                "episode": raw.get("IndexNumber"), "description": raw.get("Overview") or "",
                "has_image": bool(raw.get("BackdropImageTags") or (raw.get("ImageTags") or {}).get("Primary")),
                "seasonal_reason": evidence, "in_jellyfin": True,
            }
    return list(found.values())


def create_christmas_router(backend, *, service=None):
    service = service or ChristmasService(appconfig.data_dir() / "christmas.sqlite3")
    router = APIRouter(tags=["christmas"])
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="christmas")
    lock = threading.Lock()
    pending = set()
    episode_cache = {}
    attempts = {}

    def owner(request):
        user = backend.current_user(request.headers, request.cookies)
        if not user or not user.get("enabled", True):
            raise HTTPException(401, "Anmeldung erforderlich.")
        require_profile_owner(request.headers, str(user["id"]))
        return user

    def prepare(user, key):
        try:
            from application_services.media_clients import get_tmdb_client
            payload = service.status(str(user["id"]), get_tmdb_client())
            if payload["carousel_active"]:
                items = christmas_episodes(backend, user)
                with lock:
                    episode_cache[key] = (time.monotonic(), items)
        except Exception:
            logger.exception("Weihnachtsauswahl konnte nicht vorbereitet werden")
        finally:
            with lock:
                pending.discard(key)

    def status(user):
        payload = service.status(str(user["id"]), None)
        key = (str(user["id"]), service.today().year,
               getattr(backend.state, "jellyfin_config_generation", 0), user.get("jellyfin_user_id"))
        preparing = payload["preparing"]
        with lock:
            cached = episode_cache.get(key)
            stale = not cached or time.monotonic() - cached[0] > 6 * 3600
            if ((preparing or payload["carousel_active"] and stale) and key not in pending
                    and len(pending) < 8 and time.monotonic() - attempts.get(key, -60) >= 60):
                pending.add(key)
                attempts[key] = time.monotonic()
                pool.submit(prepare, dict(user), key)
            episodes = cached[1] if cached else []
        if payload["carousel_active"] and episodes:
            # Use the complete annual pool so daily offsets are not applied twice.
            with service.connect() as db:
                row = db.execute("SELECT movies FROM seasons WHERE year=?", (payload["year"],)).fetchone()
            movies = json.loads(row[0]) if row else []
            payload["items"] = daily_selection(movies, episodes, payload["server_date"])
        return payload

    @router.get("/api/home/christmas")
    async def get_christmas(request: Request):
        user = await run_in_threadpool(owner, request)
        payload = await run_in_threadpool(status, user)
        # No shared HTTP cache may expose another profile's calendar.
        from starlette.responses import JSONResponse
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @router.post("/api/home/christmas/doors/{day}")
    async def open_door(day: int, request: Request):
        user = await run_in_threadpool(owner, request)
        try:
            return await run_in_threadpool(service.open, str(user["id"]), day)
        except ValueError as error:
            raise HTTPException(403, str(error)) from error
        except LookupError as error:
            raise HTTPException(503, str(error)) from error

    return router
