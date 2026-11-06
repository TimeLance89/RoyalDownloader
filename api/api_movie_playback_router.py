"""Same-origin Jellyfin movie streaming for RD administrators."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import Response, StreamingResponse

from core import egress_requests as requests
from integrations.jellyfin_auth import jellyfin_auth_headers
from integrations.jellyfin_client import JellyfinClient, track_rd_movie_stream
from integrations.media_center import profile_identity, validate_server_url

MAX_POSITION_TICKS = 24 * 60 * 60 * 10_000_000
RESUME_TYPES = {"Movie", "Episode"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/avif"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024


class MovieProgress(BaseModel):
    profile_id: UUID
    generation: int
    position_ticks: int = Field(ge=0, le=MAX_POSITION_TICKS)
    ended: bool = False


class MovieStream(StreamingResponse):
    def __init__(self, upstream, headers):
        self.upstream = upstream
        super().__init__(upstream.iter_content(chunk_size=128 * 1024),
                         status_code=upstream.status_code, headers=headers, media_type="video/mp4")

    async def __call__(self, scope, receive, send):
        with track_rd_movie_stream():
            try:
                await super().__call__(scope, receive, send)
            finally:
                self.upstream.close()


def _jellyfin_json(base_url, key, endpoint, params):
    try:
        with requests.get(f"{base_url}{endpoint}", params=params,
                          headers=jellyfin_auth_headers(key), timeout=5,
                          allow_redirects=False) as response:
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict):
                    return result
    except (requests.RequestException, ValueError):
        pass
    raise HTTPException(502, "Jellyfin konnte die Wiedergabedaten nicht liefern.")


def _resume_card(item, *, resumable_only=True):
    if item.get("Type") not in RESUME_TYPES or not item.get("Name"):
        return None
    try:
        item_id = UUID(item["Id"]).hex
        position = int((item.get("UserData") or {}).get("PlaybackPositionTicks") or 0)
        duration = int(item.get("RunTimeTicks") or 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not 0 < position <= MAX_POSITION_TICKS or (duration and position >= duration):
        if resumable_only:
            return None
        position = 0
    episode = item["Type"] == "Episode"
    return {
        "id": item_id, "kind": "episode" if episode else "movie",
        "title": (item.get("SeriesName") or item["Name"]) if episode else item["Name"],
        "episode_title": item["Name"] if episode else "",
        "season": item.get("ParentIndexNumber"), "episode": item.get("IndexNumber"),
        "year": item.get("ProductionYear"), "position_ticks": position, "duration_ticks": duration,
        "has_image": bool(item.get("BackdropImageTags") or (item.get("ImageTags") or {}).get("Primary")),
    }


def _movie_id(client, items, title, year, tmdb_id):
    exact = [item for item in items if tmdb_id and str(item.get("tmdb_id") or "") == str(tmdb_id)]
    if exact:
        matches = exact
    elif client.match(title, year, items=items, tmdb_id=tmdb_id):
        matches = [item for item in items if client.match(title, year, items=[item], tmdb_id=tmdb_id)]
        if len(matches) > 1:
            raise HTTPException(409, "Der Film konnte in Jellyfin nicht eindeutig zugeordnet werden.")
    else:
        matches = []
    if not matches:
        raise HTTPException(404, "Der Film wurde in Jellyfin nicht gefunden.")
    try:
        return UUID(matches[0]["id"]).hex
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(502, "Jellyfin hat keine gültige Film-ID geliefert.") from None


def _stream_options(base_url, headers, item_id, start_ticks=0):
    with requests.get(f"{base_url}/Items/{item_id}/PlaybackInfo", headers=headers,
                      timeout=10, allow_redirects=False) as info:
        if info.status_code == 404:
            raise HTTPException(404, "Der Film ist in Jellyfin nicht mehr vorhanden.")
        if info.status_code != 200:
            raise HTTPException(502, "Jellyfin konnte keine Wiedergabedaten liefern.")
        sources = info.json().get("MediaSources") or []
    source = next((source for source in sources if source.get("Protocol") == "File"
                   and any(stream.get("Type") == "Video" for stream in source.get("MediaStreams") or [])), None)
    if not source:
        raise HTTPException(502, "Für den Film ist keine lokale Jellyfin-Mediendatei verfügbar.")

    streams = source.get("MediaStreams") or []
    video = next(stream for stream in streams if stream.get("Type") == "Video")
    audio = [stream for stream in streams if stream.get("Type") == "Audio"]
    options = {"MediaSourceId": source["Id"]}
    if (not start_ticks and "mp4" in (source.get("Container") or "").split(",")
            and video.get("Codec") == "h264" and video.get("BitDepth") == 8
            and (not audio or (len(audio) == 1 and audio[0].get("Codec") == "aac"))):
        return options | {"Static": "true"}
    options.update({
        "Static": "false", "VideoCodec": "h264", "AudioCodec": "aac",
        "MaxVideoBitDepth": 8, "MaxWidth": 1920, "VideoBitRate": 8_000_000,
        "AudioBitRate": 192_000, "MaxAudioChannels": 2, "RequireAvc": "true",
    })
    if start_ticks:
        if source.get("RunTimeTicks") and start_ticks >= source["RunTimeTicks"]:
            raise HTTPException(409, "Der Wiedergabestand liegt außerhalb der verfügbaren Filmversion.")
        options["StartTimeTicks"] = start_ticks
        options["CopyTimestamps"] = "false"
    return options


def create_movie_playback_router(backend, administrator):
    router = APIRouter(tags=["media-center"], dependencies=[Depends(administrator)])

    def connection():
        state = backend.state
        with state.jellyfin_cache_lock:
            config = dict(state.jellyfin_cfg)
            generation = state.jellyfin_config_generation
        if config.get("provider", "jellyfin") != "jellyfin" or not config.get("api_key") or not config.get("url"):
            return None
        try:
            base_url = validate_server_url(config["url"])
        except ValueError as error:
            raise HTTPException(503, str(error)) from None
        return config, generation, base_url

    def linked_profile(request, config):
        user = backend.current_user(request.headers, request.cookies) or {}
        user_id, _ = profile_identity(user, config)
        if not user_id and user.get("id") == "admin-legacy":
            user_id = config.get("user_id")
        try:
            return UUID(user_id).hex if user_id else None
        except ValueError:
            return None

    def profile_video(base_url, config, profile_id, item_id):
        if not profile_id:
            raise HTTPException(403, "Verknüpfe dein Jellyfin-Profil, um den Inhalt abzuspielen.")
        result = _jellyfin_json(base_url, config["api_key"], "/Items", {
            "UserId": profile_id, "Ids": item_id, "IncludeItemTypes": "Movie,Episode",
            "Recursive": "true", "Limit": 1, "EnableUserData": "true",
        })
        item = next(iter(result.get("Items") or []), {})
        if (not isinstance(item, dict) or item.get("Type") not in RESUME_TYPES
                or str(item.get("Id", "")).replace("-", "").lower() != item_id):
            raise HTTPException(404, "Dieser Inhalt ist im verknüpften Jellyfin-Profil nicht verfügbar.")
        return item

    @router.get("/api/media-center/series/episodes")
    def series_episodes(request: Request, title: str = Query(min_length=1, max_length=400),
                        tmdb_id: int | None = Query(default=None, gt=0),
                        aliases: Annotated[list[str] | None, Query(max_length=8)] = None):
        active = connection()
        if active is None:
            return {"items": []}
        config, generation, base_url = active
        profile_id = linked_profile(request, config)
        if not profile_id:
            return {"items": []}
        library = backend.get_jellyfin_series()
        if library is None:
            raise HTTPException(503, "Die Jellyfin-Serienbibliothek ist nicht erreichbar.")
        client = JellyfinClient(base_url, config["api_key"])
        matches = client.series_ids_for(title, tmdb_id, aliases or (), items=library)
        if not matches or len(matches) != 1:
            return {"items": []}
        try:
            series_id = UUID(next(iter(matches))).hex
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(502, "Jellyfin hat keine gültige Serien-ID geliefert.") from None
        result = _jellyfin_json(base_url, config["api_key"], f"/Shows/{series_id}/Episodes", {
            "UserId": profile_id, "IsMissing": "false", "EnableUserData": "true",
            "ImageTypeLimit": 1, "EnableImageTypes": "Primary",
        })
        episodes = []
        for item in result.get("Items") or []:
            if (not isinstance(item, dict) or item.get("Type") != "Episode"
                    or not isinstance(item.get("ParentIndexNumber"), int)
                    or not isinstance(item.get("IndexNumber"), int)
                    or item.get("LocationType") in {"Virtual", "Offline"}):
                continue
            card = _resume_card(item, resumable_only=False)
            if card:
                user_data = item.get("UserData") or {}
                episodes.append(card | {
                    "played": bool(user_data.get("Played")),
                    "last_played": user_data.get("LastPlayedDate") or "",
                })
        return {"items": episodes, "profile_id": profile_id, "generation": generation}

    @router.get("/api/media-center/continue-watching")
    def continue_watching(request: Request):
        active = connection()
        if active is None:
            return {"items": []}
        config, generation, base_url = active
        profile_id = linked_profile(request, config)
        if not profile_id:
            return {"items": []}
        result = _jellyfin_json(base_url, config["api_key"], "/UserItems/Resume", {
            "UserId": profile_id, "IncludeItemTypes": "Movie,Episode", "Limit": 30,
            "EnableUserData": "true", "EnableTotalRecordCount": "false", "ImageTypeLimit": 1,
            "EnableImageTypes": "Primary,Backdrop",
        })
        cards = [_resume_card(item) for item in (result.get("Items") or [])[:30] if isinstance(item, dict)]
        return {"items": [card for card in cards if card], "generation": generation, "profile_id": profile_id}

    @router.get("/api/media-center/continue-watching/{item_id}/image")
    def continue_watching_image(request: Request, item_id: UUID):
        active = connection()
        if active is None:
            raise HTTPException(404)
        config, _, base_url = active
        item = profile_video(base_url, config, linked_profile(request, config), item_id.hex)
        image_type = "Backdrop" if item.get("BackdropImageTags") else "Primary"
        try:
            with requests.get(f"{base_url}/Items/{item_id.hex}/Images/{image_type}",
                              params={"maxWidth": 640, "quality": 85},
                              headers=jellyfin_auth_headers(config["api_key"]), stream=True,
                              timeout=5, allow_redirects=False) as image:
                mime = image.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if image.status_code != 200 or mime not in IMAGE_TYPES:
                    raise HTTPException(404)
                content = bytearray()
                for chunk in image.iter_content(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise HTTPException(502, "Jellyfin-Bild ist zu groß.")
        except requests.RequestException:
            raise HTTPException(502, "Jellyfin-Bild ist nicht erreichbar.") from None
        return Response(bytes(content), media_type=mime)

    def resolve_movie(request: Request, title: str = Query(default="", max_length=400),
                      year: str = Query(default="", max_length=10),
                      tmdb_id: int | None = Query(default=None, gt=0), item_id: UUID | None = None):
        active = connection()
        if active is None:
            raise HTTPException(404, "Jellyfin ist nicht als Mediencenter eingerichtet.")
        config, generation, base_url = active
        if item_id is not None:
            item = profile_video(base_url, config, linked_profile(request, config), item_id.hex)
            return config, generation, base_url, item_id.hex, item
        if not title:
            raise HTTPException(422, "Ein Filmtitel ist erforderlich.")

        client = JellyfinClient(base_url, config["api_key"])
        items = backend.get_jellyfin_movie_identities()
        state = backend.state
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                raise HTTPException(409, "Die Jellyfin-Verbindung wurde geändert. Bitte erneut versuchen.")
        if items is None:
            raise HTTPException(503, "Die Jellyfin-Filmbibliothek ist nicht erreichbar.")
        matched_id = _movie_id(client, items, backend.clean_movie_title(title), year, tmdb_id)
        return config, generation, base_url, matched_id, None

    movie_dependency = Annotated[tuple[dict, int, str, str, dict | None], Depends(resolve_movie)]

    @router.get("/api/media-center/movies/progress")
    def read_progress(request: Request, movie: movie_dependency):
        config, generation, base_url, item_id, item = movie
        profile_id = linked_profile(request, config)
        endpoint = f"/Items/{item_id}" if profile_id else "/Items"
        params = {"userId": profile_id} if profile_id else {
            "Ids": item_id, "IncludeItemTypes": "Movie", "Recursive": "true",
            "Limit": 1, "EnableImages": "false",
        }
        try:
            if item is None:
                item = _jellyfin_json(base_url, config["api_key"], endpoint, params)
                if not profile_id:
                    item = next(iter(item.get("Items") or []), {})
            duration = int(item.get("RunTimeTicks") or 0)
            position = int((item.get("UserData") or {}).get("PlaybackPositionTicks") or 0) if profile_id else 0
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(502, "Jellyfin konnte den Wiedergabestand nicht laden.") from None
        if not 0 < position <= MAX_POSITION_TICKS or (duration and position >= duration):
            position = 0
        return {"position_ticks": position, "duration_ticks": duration,
                "profile_id": profile_id, "generation": generation}

    @router.post("/api/media-center/movies/progress", status_code=204)
    def save_progress(request: Request, progress: MovieProgress, movie: movie_dependency):
        config, generation, base_url, item_id, _ = movie
        profile_id = linked_profile(request, config)
        if generation != progress.generation or profile_id != progress.profile_id.hex:
            raise HTTPException(409, "Das verknüpfte Jellyfin-Profil oder der Server wurde geändert.")
        data = {
            "PlaybackPositionTicks": 0 if progress.ended else progress.position_ticks,
            "LastPlayedDate": datetime.now(UTC).isoformat(),
        }
        if progress.ended:
            data["Played"] = True
        try:
            with requests.post(f"{base_url}/UserItems/{item_id}/UserData", params={"userId": profile_id},
                               json=data, headers=jellyfin_auth_headers(config["api_key"]),
                               timeout=5, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise HTTPException(502, "Jellyfin konnte den Wiedergabestand nicht speichern.")
        except requests.RequestException:
            raise HTTPException(502, "Jellyfin konnte den Wiedergabestand nicht speichern.") from None
        return Response(status_code=204)

    @router.get("/api/media-center/movies/stream")
    def stream_movie(request: Request, movie: movie_dependency,
                     start_ticks: int = Query(default=0, ge=0, le=MAX_POSITION_TICKS)):
        config, _, base_url, item_id, _ = movie
        headers = jellyfin_auth_headers(config["api_key"])
        try:
            options = _stream_options(base_url, headers, item_id, start_ticks)
            headers["Accept-Encoding"] = "identity"
            if options["Static"] == "true" and request.headers.get("range"):
                headers["Range"] = request.headers["range"]
            upstream = requests.get(f"{base_url}/Videos/{item_id}/stream.mp4",
                                    params=options, headers=headers, timeout=(5, 30),
                                    stream=True, allow_redirects=False)
        except (requests.RequestException, KeyError, ValueError, AttributeError, TypeError):
            raise HTTPException(502, "Der Jellyfin-Stream konnte nicht geöffnet werden.") from None

        response_headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        for name in ("Accept-Ranges", "Content-Range", "Content-Length"):
            if name in upstream.headers:
                response_headers[name] = upstream.headers[name]
        if upstream.status_code in (200, 206) and upstream.headers.get("Content-Type", "").split(";")[0] == "video/mp4":
            return MovieStream(upstream, response_headers)
        upstream.close()
        if upstream.status_code == 416:
            response_headers.pop("Content-Length", None)
            return Response(status_code=416, headers=response_headers)
        raise HTTPException(502, "Jellyfin konnte den Film nicht als MP4-Stream liefern.")

    return router
