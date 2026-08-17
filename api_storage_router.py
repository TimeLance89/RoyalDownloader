"""Storage telemetry and guarded cleanup endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config as appconfig
from storage_manager import cleanup_candidate, scan_large_content, storage_status

router = APIRouter(tags=["administration", "storage"])


def _media_paths() -> dict[str, str]:
    movies = str(appconfig.load() or "").strip()
    series = str(appconfig.load_series_path() or "").strip() or movies
    return {"movies": movies, "series": series}


class StorageScanBody(BaseModel):
    max_candidates: int = Field(default=40, ge=5, le=80)


class StorageCleanupBody(BaseModel):
    root: str
    relative_path: str = Field(min_length=1, max_length=2048)
    token: str = Field(min_length=32, max_length=256)
    expected_size: int = Field(ge=0)
    expires_at: int = Field(gt=0)
    confirm: bool = False


@router.get("/api/v1/storage/status")
@router.get("/api/storage/status")
async def api_storage_status():
    return await run_in_threadpool(
        storage_status,
        _media_paths(),
        appconfig.load_deployment_mode(),
    )


@router.post("/api/v1/storage/scan")
@router.post("/api/storage/scan")
async def api_storage_scan(body: StorageScanBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus gibt es keinen realen Medienspeicher.")
    return await run_in_threadpool(
        scan_large_content,
        _media_paths(),
        max_candidates=body.max_candidates,
    )


@router.post("/api/v1/storage/cleanup")
@router.post("/api/storage/cleanup")
async def api_storage_cleanup(body: StorageCleanupBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine Mediendateien gelöscht werden.")
    if not body.confirm:
        raise HTTPException(400, "Die dauerhafte Bereinigung muss ausdrücklich bestätigt werden.")
    try:
        return await run_in_threadpool(
            cleanup_candidate,
            _media_paths(),
            root_key=body.root,
            relative_path=body.relative_path,
            token=body.token,
            expected_size=body.expected_size,
            expires_at=body.expires_at,
        )
    except FileNotFoundError as exc:
        raise HTTPException(409, "Der Inhalt existiert nicht mehr. Bitte erneut scannen.") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
