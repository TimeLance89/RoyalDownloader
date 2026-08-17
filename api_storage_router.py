"""Storage telemetry, multi-volume registry, scanning, cleanup, and guarded moves."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config as appconfig
from storage_locations import (
    LOCATION_MODE_MONITOR,
    cleanup_configured_candidate,
    combined_storage_status,
    load_storage_locations,
    remove_storage_location,
    save_storage_location,
    scan_configured_storage,
)
from storage_move import plan_move_candidate
from storage_move_runtime import create_move_job, list_move_jobs

router = APIRouter(tags=["administration", "storage"])


def _media_paths() -> dict[str, str]:
    movies = str(appconfig.load() or "").strip()
    series = str(appconfig.load_series_path() or "").strip() or movies
    return {"movies": movies, "series": series}


class StorageScanBody(BaseModel):
    max_candidates: int = Field(default=40, ge=5, le=80)


class StorageCleanupBody(BaseModel):
    root: str = Field(min_length=1, max_length=96)
    relative_path: str = Field(min_length=1, max_length=2048)
    token: str = Field(min_length=32, max_length=256)
    expected_size: int = Field(ge=0)
    expires_at: int = Field(gt=0)
    confirm: bool = False


class StorageMovePlanBody(BaseModel):
    root: str = Field(min_length=1, max_length=96)
    relative_path: str = Field(min_length=1, max_length=2048)
    token: str = Field(min_length=32, max_length=256)
    expected_size: int = Field(ge=0)
    expires_at: int = Field(gt=0)


class StorageMoveBody(StorageMovePlanBody):
    destination_root: str = Field(min_length=1, max_length=96)
    confirm: bool = False


class StorageLocationBody(BaseModel):
    location_id: str = Field(default="", max_length=64)
    label: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=2048)
    mode: Literal["monitor", "media"] = LOCATION_MODE_MONITOR


class StorageLocationRemoveBody(BaseModel):
    location_id: str = Field(min_length=1, max_length=64)


@router.get("/api/v1/storage/status")
@router.get("/api/storage/status")
async def api_storage_status():
    return await run_in_threadpool(
        combined_storage_status,
        _media_paths(),
        appconfig.load_deployment_mode(),
        load_storage_locations(),
    )


@router.get("/api/v1/storage/locations")
@router.get("/api/storage/locations")
async def api_storage_locations():
    locations = await run_in_threadpool(load_storage_locations)
    return {
        "locations": locations,
        "modes": ["monitor", "media"],
    }


@router.get("/api/v1/storage/move/jobs")
@router.get("/api/storage/move/jobs")
async def api_storage_move_jobs():
    return await run_in_threadpool(list_move_jobs)


@router.post("/api/v1/storage/locations/save")
@router.post("/api/storage/locations/save")
async def api_storage_location_save(body: StorageLocationBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine realen Speicherorte verwaltet werden.")
    try:
        location = await run_in_threadpool(
            save_storage_location,
            label=body.label,
            path=body.path,
            mode=body.mode,
            location_id=body.location_id,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"saved": True, "location": location}


@router.post("/api/v1/storage/locations/remove")
@router.post("/api/storage/locations/remove")
async def api_storage_location_remove(body: StorageLocationRemoveBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine realen Speicherorte verwaltet werden.")
    removed = await run_in_threadpool(remove_storage_location, body.location_id)
    if not removed:
        raise HTTPException(404, "Der Speicherort wurde nicht gefunden.")
    return {"removed": True, "location_id": body.location_id}


@router.post("/api/v1/storage/scan")
@router.post("/api/storage/scan")
async def api_storage_scan(body: StorageScanBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus gibt es keinen realen Medienspeicher.")
    return await run_in_threadpool(
        scan_configured_storage,
        _media_paths(),
        load_storage_locations(),
        max_candidates=body.max_candidates,
    )


@router.post("/api/v1/storage/move/plan")
@router.post("/api/storage/move/plan")
async def api_storage_move_plan(body: StorageMovePlanBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine Mediendateien verschoben werden.")
    try:
        return await run_in_threadpool(
            plan_move_candidate,
            _media_paths(),
            load_storage_locations(),
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


@router.post("/api/v1/storage/move")
@router.post("/api/storage/move")
async def api_storage_move(body: StorageMoveBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine Mediendateien verschoben werden.")
    if not body.confirm:
        raise HTTPException(400, "Das Verschieben muss ausdrücklich bestätigt werden.")
    try:
        job = await run_in_threadpool(
            create_move_job,
            _media_paths(),
            load_storage_locations(),
            root_key=body.root,
            relative_path=body.relative_path,
            token=body.token,
            expected_size=body.expected_size,
            expires_at=body.expires_at,
            destination_root=body.destination_root,
        )
    except FileNotFoundError as exc:
        raise HTTPException(409, "Der Inhalt existiert nicht mehr. Bitte erneut scannen.") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"accepted": True, "job": job}


@router.post("/api/v1/storage/cleanup")
@router.post("/api/storage/cleanup")
async def api_storage_cleanup(body: StorageCleanupBody):
    if appconfig.demo_mode_enabled():
        raise HTTPException(409, "Im Demo-Modus können keine Mediendateien gelöscht werden.")
    if not body.confirm:
        raise HTTPException(400, "Die dauerhafte Bereinigung muss ausdrücklich bestätigt werden.")
    try:
        return await run_in_threadpool(
            cleanup_configured_candidate,
            _media_paths(),
            load_storage_locations(),
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
