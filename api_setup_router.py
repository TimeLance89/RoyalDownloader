"""First-run setup HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from setup_bootstrap import (
    SetupBootstrapError,
    SetupBootstrapLocked,
    bootstrap_status,
    consume_setup_token,
    verify_setup_token,
)


class SetupCompleteBody(BaseModel):
    deployment_mode: str = "desktop"
    save_path: str = ""
    series_path: str = ""
    ui_language: str = "de"
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    jellyfin_user_name: str = ""
    tmdb_api_key: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    auto_download: bool = False
    check_interval_min: int = 30
    dl_window_start: int | None = None
    dl_window_end: int | None = None
    movie_provider_order: list[str] | None = None
    series_provider_order: list[str] | None = None
    anime_provider_order: list[str] | None = None
    movie_providers: list[str] | None = None
    series_providers: list[str] | None = None
    anime_providers: list[str] | None = None
    content_languages: list[str] | None = None
    auth_username: str = ""
    auth_password: str = ""
    bootstrap_token: str = Field(default="", max_length=256)


@dataclass(frozen=True)
class SetupDependencies:
    """Setup state and transaction callbacks from the composition root."""

    status_payload: Callable[[], dict]
    completion_lock: Callable[[], Any]
    complete: Callable[[SetupCompleteBody, Request], Any]


def create_setup_router(dependencies: SetupDependencies) -> APIRouter:
    router = APIRouter(tags=["auth-setup"])

    @router.get("/api/setup/status")
    async def api_setup_status():
        payload = dependencies.status_payload()
        if payload.get("required"):
            payload.update(bootstrap_status())
        else:
            payload.update({"bootstrap_required": False, "bootstrap_hint": ""})
        return payload

    @router.post("/api/setup/complete")
    async def api_setup_complete(body: SetupCompleteBody, request: Request):
        # Once an installation is configured this endpoint is protected by the
        # normal authentication middleware.  During the public first-run state,
        # the one-time bootstrap secret is the trust anchor for claiming it.
        if dependencies.status_payload().get("required"):
            try:
                verify_setup_token(body.bootstrap_token, request)
            except SetupBootstrapLocked as exc:
                raise HTTPException(
                    429,
                    detail={
                        "code": "setup_bootstrap_locked",
                        "message": str(exc),
                    },
                    headers={"Retry-After": str(exc.retry_after)},
                ) from exc
            except SetupBootstrapError as exc:
                raise HTTPException(
                    403,
                    detail={
                        "code": "setup_bootstrap_invalid",
                        "message": str(exc),
                    },
                ) from exc

        lock = dependencies.completion_lock()
        if not lock.acquire(blocking=False):
            raise HTTPException(
                409,
                detail={
                    "code": "setup_in_progress",
                    "message": "Die Ersteinrichtung wird bereits abgeschlossen.",
                },
            )
        try:
            result = await dependencies.complete(body, request)
            consume_setup_token()
            return result
        finally:
            lock.release()

    return router
