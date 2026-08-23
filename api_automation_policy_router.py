"""Supplemental administration API for smart unattended automation."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import smart_automation as smart_policy

router = APIRouter(tags=["administration"])


class AutomationPolicyBody(BaseModel):
    auto_download: bool = False
    check_interval_min: int = 30
    weekday_window_start: int | None = None
    weekday_window_end: int | None = None
    weekend_window_start: int | None = None
    weekend_window_end: int | None = None
    max_parallel_downloads: int = smart_policy.DEFAULT_PARALLEL_DOWNLOADS
    max_bandwidth_mbps: float = 0.0
    min_free_space_gb: float = 0.0
    jellyfin_throttle_enabled: bool = False
    jellyfin_streaming_bandwidth_mbps: float = smart_policy.DEFAULT_JELLYFIN_STREAMING_MBPS
    movie_upgrades_night_only: bool = False
    movie_upgrade_window_start: int | None = smart_policy.DEFAULT_MOVIE_UPGRADE_START
    movie_upgrade_window_end: int | None = smart_policy.DEFAULT_MOVIE_UPGRADE_END


def _runtime_backend():
    backend = smart_policy.backend()
    if backend is None or getattr(backend, "state", None) is None:
        raise HTTPException(503, "Automatik-Runtime ist noch nicht bereit.")
    return backend


def _validate_optional_window(start: int | None, end: int | None, label: str) -> None:
    if (start is None) != (end is None):
        raise HTTPException(
            400,
            f"{label}: Start und Ende müssen entweder beide gesetzt oder beide leer sein.",
        )
    for value in (start, end):
        if value is not None and not 0 <= int(value) <= 23:
            raise HTTPException(400, f"{label}: Stunden müssen zwischen 0 und 23 liegen.")


def _validated_payload(body: AutomationPolicyBody) -> dict[str, Any]:
    _validate_optional_window(body.weekday_window_start, body.weekday_window_end, "Mo–Fr")
    _validate_optional_window(body.weekend_window_start, body.weekend_window_end, "Wochenende")
    _validate_optional_window(
        body.movie_upgrade_window_start,
        body.movie_upgrade_window_end,
        "Film-Upgrades",
    )
    if not smart_policy.MIN_PARALLEL_DOWNLOADS <= body.max_parallel_downloads <= smart_policy.MAX_PARALLEL_DOWNLOADS:
        raise HTTPException(400, "Parallele Downloads müssen zwischen 1 und 4 liegen.")
    if body.max_bandwidth_mbps < 0:
        raise HTTPException(400, "Das Bandbreitenlimit darf nicht negativ sein.")
    if body.min_free_space_gb < 0:
        raise HTTPException(400, "Der Speicher-Mindestwert darf nicht negativ sein.")
    if body.jellyfin_streaming_bandwidth_mbps <= 0:
        raise HTTPException(400, "Das Jellyfin-Bandbreitenbudget muss größer als 0 MB/s sein.")
    return body.model_dump()


@router.get("/api/v1/automation/policy")
@router.get("/api/automation/policy")
async def api_automation_policy_get():
    backend = _runtime_backend()
    return await run_in_threadpool(smart_policy.policy_payload, backend.state)


@router.post("/api/v1/automation/policy")
@router.post("/api/automation/policy")
async def api_automation_policy_set(body: AutomationPolicyBody):
    backend = _runtime_backend()
    payload = _validated_payload(body)

    saved = await run_in_threadpool(smart_policy.save_automation_policy, **payload)
    if not saved:
        raise HTTPException(500, "Automatik-Regeln konnten nicht gespeichert werden.")

    policy = await run_in_threadpool(smart_policy.load_automation_policy)
    backend.state.automation = policy
    smart_policy.apply_runtime_policy(backend.state, policy)

    if policy.get("auto_download"):
        threading.Thread(
            target=backend._auto_download_new_episodes,
            name="smart-automation-series-kick",
            daemon=True,
        ).start()
    movie_allowed, _reason = smart_policy.automatic_movie_upgrade_decision(backend.state)
    if movie_allowed:
        threading.Thread(
            target=backend.check_movie_subscriptions,
            name="smart-automation-movie-kick",
            daemon=True,
        ).start()

    return {**smart_policy.policy_payload(backend.state), "saved": True}
