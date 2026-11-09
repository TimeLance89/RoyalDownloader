"""Playback authorization using existing household accounts and SessionStore."""

from dataclasses import dataclass, field
from time import monotonic
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from core.auth import SESSION_KIND_MOBILE, SESSION_KIND_WEB
from integrations.jellyfin_permissions import JellyfinPermissionError, require_jellyfin_profile
from integrations.media_center import profile_identity


@dataclass(frozen=True)
class PlaybackContext:
    owner: str
    role: str
    revision: str
    session: object = field(repr=False)
    config: dict = field(repr=False)
    generation: int
    profile_id: str | None


class PlaybackAccess:
    def __init__(self, backend, read_json):
        self.backend, self.read_json = backend, read_json

    def snapshot(self, request):
        user = self.backend.current_user(request.headers, request.cookies)
        if not user or not user.get("enabled", True) or not user.get("id"):
            raise HTTPException(401, "Anmeldung erforderlich.")
        if user.get("role") not in ("admin", "member"):
            raise HTTPException(403, "Kein Wiedergabezugriff.")
        store = self.backend.SESSION_STORE
        identity = None
        for token, kind in ((self.backend.authenticated_mobile_token(request.headers, touch=False), SESSION_KIND_MOBILE),
                            (self.backend.authenticated_web_token(request.cookies, touch=False), SESSION_KIND_WEB)):
            if token:
                identity = store.authorization_context(token, kind)
                if identity is not None:
                    break
        if identity is None or identity[1] != str(user["id"]):
            raise HTTPException(401, "Die Sitzung ist nicht mehr gültig.")
        with self.backend.state.jellyfin_cache_lock:
            config = dict(self.backend.state.jellyfin_cfg)
            generation = self.backend.state.jellyfin_config_generation
        profile_id, _ = profile_identity(user, config)
        if not profile_id and user["id"] == "admin-legacy" and user["role"] == "admin":
            profile_id = config.get("user_id")
        try:
            profile_id = UUID(str(profile_id)).hex if profile_id else None
        except (ValueError, TypeError, AttributeError):
            profile_id = None
        return PlaybackContext(str(user["id"]), user["role"], str(user.get("updated_at", "")),
                               identity[0], config, generation, profile_id)

    def enabled_user(self, request: Request):
        request.state.playback_context = self.snapshot(request)

    def context(self, request):
        context = getattr(request.state, "playback_context", None)
        if context is None:
            raise HTTPException(401, "Anmeldung erforderlich.")
        return context

    def assert_current(self, request, expected=None):
        expected = expected if expected is not None else self.context(request)
        if self.snapshot(request) != expected:
            raise HTTPException(409, "Das Konto, die Sitzung oder die Jellyfin-Zuordnung wurde geändert.")

    def profile(self, request, base_url, *, force=False):
        context = self.context(request)
        if not context.profile_id:
            raise HTTPException(403, "Verknüpfe dein Jellyfin-Profil, um Inhalte anzusehen.")
        if force or not getattr(request.state, "playback_profile_checked", False):
            user = self.read_json(base_url, context.config["api_key"], f"/Users/{context.profile_id}", {})
            try:
                require_jellyfin_profile(user, context.profile_id)
            except JellyfinPermissionError as error:
                raise HTTPException(error.status, str(error)) from None
            self.assert_current(request)
            request.state.playback_profile_checked = True
        return context.profile_id

    def stream_guard(self, request, verify_remote, *, invalidate=lambda: None):
        expected = self.context(request)
        next_local, next_remote = 0.0, monotonic() + 10

        def guard():
            nonlocal next_local, next_remote
            now = monotonic()
            try:
                if now >= next_local:
                    self.assert_current(request, expected)
                    next_local = now + 2
                if now >= next_remote:
                    verify_remote()
                    self.assert_current(request, expected)
                    next_remote = now + 10
                return True
            except HTTPException:
                invalidate()
                return False

        return guard

    def route_class(self):
        access = self

        class AuthorizedPlaybackRoute(APIRoute):
            def get_route_handler(self):
                original = super().get_route_handler()

                async def handler(request):
                    response = None
                    try:
                        response = await original(request)
                        await run_in_threadpool(access.assert_current, request)
                        response.headers["Cache-Control"] = "no-store"
                        return response
                    except BaseException:
                        close = getattr(response, "close", None)
                        if close is not None:
                            await run_in_threadpool(close)
                        raise

                return handler

        return AuthorizedPlaybackRoute
