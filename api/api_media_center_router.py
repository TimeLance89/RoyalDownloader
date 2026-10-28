"""Validated media-center onboarding and atomic activation."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import core.config as appconfig
from integrations.media_center import media_client, validate_server_url
from integrations.plex_client import PlexError

logger = logging.getLogger(__name__)


class ConnectionBody(BaseModel):
    provider: Literal["jellyfin", "plex"]
    url: str = Field(max_length=2048)
    api_key: str = Field(default="", max_length=4096)
    libraries: list[str] = Field(default_factory=list, max_length=100)
    user_id: str = Field(default="", max_length=128)
    server_id: str = Field(default="", max_length=256)
    expected_generation: int = 0


def create_media_center_router(backend):
    def administrator(request: Request):
        user = backend.current_user(request.headers, request.cookies)
        if not user or user.get("role") != "admin":
            raise HTTPException(403, "Administratorrechte erforderlich.")

    router = APIRouter(tags=["media-center"])

    def config_payload():
        with backend.state.jellyfin_cache_lock:
            config = dict(backend.state.jellyfin_cfg)
            generation = backend.state.jellyfin_config_generation
        return {key: config.get(key, "") for key in ("url", "user_id", "user_name", "server_id", "server_name")} | {
            "provider": config.get("provider", "jellyfin"), "has_api_key": bool(config.get("api_key")),
            "configured": bool(config.get("url") and config.get("api_key")),
            "libraries": config.get("libraries", []), "generation": generation,
            "cleanup_supported": config.get("provider") != "plex",
        }

    @router.get("/api/media-center/status")
    def status():
        payload = config_payload()
        return {key: payload[key] for key in ("provider", "configured", "generation", "cleanup_supported")}

    @router.get("/api/media-center/config", dependencies=[Depends(administrator)])
    def config():
        connections = {}
        for provider in ("jellyfin", "plex"):
            stored = appconfig.load_media_connection(provider)
            connections[provider] = {key: stored.get(key, "") for key in ("url", "user_id", "user_name", "server_id")}
            connections[provider].update(has_api_key=bool(stored.get("api_key")), libraries=stored.get("libraries", []))
        return config_payload() | {"connections": connections}

    def probe(body):
        try:
            url = validate_server_url(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        previous = appconfig.load_media_connection(body.provider)
        token = body.api_key.strip()
        if not token and url == str(previous.get("url", "")).rstrip("/"):
            token = previous.get("api_key", "")
        if not token:
            raise HTTPException(400, "API-Schlüssel beziehungsweise Plex-Token fehlt.")
        cfg = {"provider": body.provider, "url": url, "api_key": token, "cleanup_default": "keep"}
        client = media_client(cfg, timeout=8)
        try:
            if body.provider == "plex":
                info = client.server_info()
                libraries = client.list_libraries()
            else:
                info = {"id": url, "name": "Jellyfin"}
                # Jellyfin's existing integration scans all libraries.
                libraries = []
            users = client.list_users()
            if users is None:
                raise PlexError("Server oder Zugangsdaten konnten nicht geprüft werden.")
            if body.server_id and body.server_id != info["id"]:
                raise PlexError("Die Serveridentität hat sich seit der Prüfung geändert.")
        except (PlexError, ValueError) as exc:
            raise HTTPException(502, str(exc)) from None
        cfg.update(server_id=info["id"], server_name=info["name"])
        return cfg, users, libraries

    @router.post("/api/media-center/probe", dependencies=[Depends(administrator)])
    async def test_connection(body: ConnectionBody):
        cfg, users, libraries = await run_in_threadpool(probe, body)
        return {"provider": body.provider, "server_id": cfg["server_id"], "server_name": cfg["server_name"],
                "users": users, "libraries": libraries,
                "profile_hint": "Der Gesehen-Status gehört zum Plex-Konto des Tokens. Weitere Plex-Home-Konten werden nicht stellvertretend gelesen." if body.provider == "plex" else "Persönliche Profile werden im Haushalt verknüpft."}

    @router.post("/api/media-center/activate", dependencies=[Depends(administrator)])
    async def activate(body: ConnectionBody):
        warnings = []
        # Probe again on commit: client-side success is never an activation grant.
        cfg, users, libraries = await run_in_threadpool(probe, body)
        if body.provider == "plex":
            available = {row["id"] for row in libraries}
            selected = list(dict.fromkeys(body.libraries))
            if not selected or not set(selected) <= available:
                raise HTTPException(400, "Mindestens eine verfügbare Plex-Bibliothek auswählen.")
            cfg["libraries"] = selected
        selected_user = next((user for user in users if user["id"] == body.user_id), None)
        if body.user_id and selected_user is None:
            raise HTTPException(400, "Das gewählte Profil ist nicht verfügbar.")
        cfg.update(user_id=body.user_id, user_name=selected_user["name"] if selected_user else "")

        def commit():
            state = backend.state
            with state.jellyfin_config_update_lock:
                with state.jellyfin_cache_lock:
                    if state.jellyfin_config_generation != body.expected_generation:
                        raise HTTPException(409, "Die Verbindung wurde zwischenzeitlich geändert. Einstellungen neu laden.")
                    previous = dict(state.jellyfin_cfg)
                if not appconfig.save_media_center(body.provider, cfg):
                    raise HTTPException(500, "Verbindung konnte nicht gespeichert werden; bisheriger Dienst bleibt aktiv.")
                try:
                    backend._set_runtime_jellyfin_config(cfg)
                except RuntimeError:
                    restored = appconfig.save_media_center(previous.get("provider", "jellyfin"), previous)
                    backend._set_runtime_jellyfin_config(previous)
                    if not restored:
                        raise HTTPException(500, "Aktivierung fehlgeschlagen. Die gespeicherten Einstellungen konnten nicht wiederhergestellt werden; Mediencenter-Einstellungen prüfen.") from None
                    raise HTTPException(500, "Aktivierung fehlgeschlagen; bisherige Verbindung wurde wiederhergestellt.") from None
                for user in backend.USER_STORE.list():
                    try:
                        backend.state.taste_profiles.for_user(user["id"]).replace_jellyfin_items([])
                    except (OSError, RuntimeError, ValueError):
                        logger.warning("Mediencenter gespeichert; abgeleitetes Geschmacksprofil konnte nicht zurückgesetzt werden.")
                        warnings.append("Profilabgleich wird beim nächsten Hintergrundlauf erneut versucht.")
                backend._recommender_wake_event.set()
            # Do not delete existing media or automatically run cleanup on a switch.
            return config_payload() | {"saved": True, "warnings": warnings}
        result = await run_in_threadpool(commit)
        try:
            backend.broadcast({"type": "media_center_update", "provider": body.provider})
        except (OSError, RuntimeError):
            logger.warning("Mediencenter gespeichert; Live-Benachrichtigung wird später aktualisiert.")
            warnings.append("Andere geöffnete Ansichten gegebenenfalls neu laden.")
        return result

    return router
