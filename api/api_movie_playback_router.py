"""Same-origin Jellyfin movie streaming for RD administrators."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import Response, StreamingResponse

from api.jellyfin_playback import PlaybackSessions
from core import egress_requests as requests
from core.config import home_layout_file
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


class ResumeAction(BaseModel):
    profile_id: UUID
    generation: int
    action: Literal["hide", "watched", "undo"]
    undo_token: UUID | None = None


def _resume_stamp(item):
    data = item.get("UserData") or {}
    return [data.get("PlaybackPositionTicks") or 0, data.get("LastPlayedDate") or ""]


def _write_hidden(path, hidden):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = NamedTemporaryFile(dir=path.parent, delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(json.dumps(hidden).encode())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _save_jellyfin_data(base_url, key, profile_id, item_id, data):
    try:
        with requests.post(f"{base_url}/UserItems/{item_id}/UserData", params={"userId": profile_id},
                           json=data, headers=jellyfin_auth_headers(key),
                           timeout=5, allow_redirects=False) as response:
            if response.status_code == 200:
                return response.json()
    except (requests.RequestException, ValueError):
        pass
    raise HTTPException(502, "Jellyfin konnte den Wiedergabestand nicht speichern.")


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


def _episode_cards(items):
    episodes = []
    for item in items:
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
    return episodes


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
        # AAC from downloaded TS sources can contain ADTS headers. Copying it
        # into progressive MP4 may abort the muxer after the first video frame.
        "AllowAudioStreamCopy": "false",
        # Keep retries and simultaneous viewers out of a failed transcode file.
        "PlaySessionId": uuid4().hex, "DeviceId": "RoyalDownloader",
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
    resume_lock = Lock()
    undo_actions = {}
    playback_sessions = PlaybackSessions()

    def resume_path(request, base_url, profile_id):
        user = backend.current_user(request.headers, request.cookies) or {}
        owner = sha256(json.dumps([base_url, user.get("id"), profile_id]).encode()).hexdigest()
        return home_layout_file().with_name("continue-watching") / f"{owner}.json"

    def read_hidden(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

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
            "Recursive": "true", "Limit": 1, "EnableUserData": "true", "Fields": "Overview,ProviderIds,Genres",
        })
        item = next(iter(result.get("Items") or []), {})
        if (not isinstance(item, dict) or item.get("Type") not in RESUME_TYPES
                or str(item.get("Id", "")).replace("-", "").lower() != item_id):
            raise HTTPException(404, "Dieser Inhalt ist im verknüpften Jellyfin-Profil nicht verfügbar.")
        return item

    def series_inventory(base_url, config, profile_id, series_id):
        result = _jellyfin_json(base_url, config["api_key"], f"/Shows/{series_id}/Episodes", {
            "UserId": profile_id, "IsMissing": "false", "EnableUserData": "true",
            "ImageTypeLimit": 1, "EnableImageTypes": "Primary",
        })
        return _episode_cards(result.get("Items") or [])

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
        episodes = series_inventory(base_url, config, profile_id, series_id)
        return {"items": episodes, "profile_id": profile_id, "generation": generation}

    @router.get("/api/media-center/episodes/{item_id}/navigation")
    def episode_navigation(request: Request, item_id: UUID):
        active = connection()
        if active is None:
            raise HTTPException(404)
        config, generation, base_url = active
        profile_id = linked_profile(request, config)
        current = profile_video(base_url, config, profile_id, item_id.hex)
        if current.get("Type") != "Episode":
            raise HTTPException(404)
        try:
            series_id = UUID(current["SeriesId"]).hex
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(502, "Die Serie konnte in Jellyfin nicht zugeordnet werden.") from None
        return {
            "items": series_inventory(base_url, config, profile_id, series_id),
            "profile_id": profile_id, "generation": generation,
        }

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
        hidden = read_hidden(resume_path(request, base_url, profile_id))
        cards = []
        for item in (result.get("Items") or [])[:30]:
            card = _resume_card(item) if isinstance(item, dict) else None
            if card and hidden.get(card["id"]) != _resume_stamp(item):
                cards.append(card)
        return {"items": cards, "generation": generation, "profile_id": profile_id}

    @router.post("/api/media-center/continue-watching/{item_id}/action")
    def resume_action(request: Request, item_id: UUID, body: ResumeAction):
        active = connection()
        if active is None:
            raise HTTPException(404)
        config, generation, base_url = active
        profile_id = linked_profile(request, config)
        if profile_id != body.profile_id.hex or generation != body.generation:
            raise HTTPException(409, "Das verknüpfte Jellyfin-Profil oder der Server wurde geändert.")
        path = resume_path(request, base_url, profile_id)
        item_key = item_id.hex
        with resume_lock:
            now = monotonic()
            for token, (expires, *_) in list(undo_actions.items()):
                if expires <= now:
                    del undo_actions[token]
            item = profile_video(base_url, config, profile_id, item_key)
            stamp = _resume_stamp(item)
            if body.action == "undo":
                entry = undo_actions.get(body.undo_token)
                if not entry or entry[1:4] != (path, generation, item_key):
                    raise HTTPException(409, "Diese Aktion kann nicht mehr rückgängig gemacht werden.")
                _, _, _, _, action, expected, previous = entry
                if action == "hide":
                    hidden = read_hidden(path)
                    if hidden.get(item_key) == expected:
                        hidden.pop(item_key)
                        _write_hidden(path, hidden)
                else:
                    if stamp != expected or not (item.get("UserData") or {}).get("Played"):
                        raise HTTPException(409, "Der Wiedergabestand wurde inzwischen geändert.")
                    _save_jellyfin_data(base_url, config["api_key"], profile_id, item_key, previous)
                del undo_actions[body.undo_token]
                return {}

            if not _resume_card(item):
                raise HTTPException(409, "Dieser Inhalt steht nicht mehr unter Weiterschauen.")
            previous = None
            if body.action == "hide":
                hidden = read_hidden(path)
                if hidden.get(item_key) == stamp:
                    raise HTTPException(409, "Dieser Inhalt wurde bereits ausgeblendet.")
                hidden.pop(item_key, None)
                hidden[item_key] = stamp
                _write_hidden(path, dict(list(hidden.items())[-500:]))
            else:
                data = item.get("UserData") or {}
                previous = {"PlaybackPositionTicks": stamp[0], "Played": bool(data.get("Played"))}
                saved = _save_jellyfin_data(base_url, config["api_key"], profile_id, item_key, {
                    "PlaybackPositionTicks": 0, "Played": True,
                })
                stamp = _resume_stamp({"UserData": saved})
            token = uuid4()
            if len(undo_actions) >= 512:
                del undo_actions[next(iter(undo_actions))]
            undo_actions[token] = (monotonic() + 30, path, generation, item_key, body.action, stamp, previous)
            return {"undo_token": token}

    @router.get("/api/media-center/continue-watching/{item_id}/details")
    def resume_details(request: Request, item_id: UUID):
        active = connection()
        if active is None:
            raise HTTPException(404)
        config, generation, base_url = active
        profile_id = linked_profile(request, config)
        item = profile_video(base_url, config, profile_id, item_id.hex)
        context = {}
        if item["Type"] == "Episode":
            try:
                series_id = UUID(item["SeriesId"]).hex
            except (KeyError, TypeError, ValueError, AttributeError):
                raise HTTPException(404, "Die zugehörige Serie ist nicht verfügbar.") from None
            episodes = series_inventory(base_url, config, profile_id, series_id)
            if not any(episode["id"] == item_id.hex for episode in episodes):
                episodes.extend(_episode_cards([item]))
            context = {
                "series_id": series_id,
                "inventory": {"items": episodes, "profile_id": profile_id, "generation": generation},
            }
            item = _jellyfin_json(base_url, config["api_key"], f"/Items/{series_id}", {"userId": profile_id})
        return {
            "title": item.get("Name"), "year": item.get("ProductionYear"),
            "description": item.get("Overview"), "tmdb_id": (item.get("ProviderIds") or {}).get("Tmdb"),
            "genres": item.get("Genres") or [],
        } | context

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

    def playback_context(request):
        active = connection()
        if active is None:
            raise HTTPException(404)
        config, generation, _ = active
        user = backend.current_user(request.headers, request.cookies) or {}
        return str(user.get("id") or ""), linked_profile(request, config), generation

    @router.post("/api/media-center/movies/session")
    def prepare_playback(request: Request, movie: movie_dependency, force_transcode: bool = False):
        config, generation, base_url, item_id, _ = movie
        owner, profile_id, active_generation = playback_context(request)
        if generation != active_generation:
            raise HTTPException(409, "Die Jellyfin-Verbindung wurde geändert.")
        profile_video(base_url, config, profile_id, item_id)
        return playback_sessions.open(base_url, config["api_key"], item_id, profile_id, generation, owner, force_transcode)

    @router.get("/api/media-center/playback/{token}/asset/{name}")
    def playback_asset(request: Request, token: str, name: str):
        session = playback_sessions.get(token, *playback_context(request))
        return playback_sessions.response(session, name, request.headers.get("range"))

    @router.post("/api/media-center/playback/{token}/seek", status_code=204)
    def interrupt_playback(request: Request, token: str):
        playback_sessions.interrupt(playback_sessions.get(token, *playback_context(request)))
        return Response(status_code=204)

    @router.post("/api/media-center/playback/{token}/heartbeat", status_code=204)
    def playback_heartbeat(request: Request, token: str):
        playback_sessions.get(token, *playback_context(request))
        return Response(status_code=204)

    @router.delete("/api/media-center/playback/{token}", status_code=204)
    def stop_playback(request: Request, token: str):
        playback_sessions.get(token, *playback_context(request))
        playback_sessions.close(token)
        return Response(status_code=204)

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
        _save_jellyfin_data(base_url, config["api_key"], profile_id, item_id, data)
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
