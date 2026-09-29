"""Admin-only storage policy and explicitly confirmed recommendation actions."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from application_services.storage_autopilot_runtime import optimize, playback_idle, queue_context, wake
from application_services.runtime import backend_value
from storage.storage_actions import apply_recommendation
from storage.storage_autopilot import dismiss_recommendation, get_autopilot, refresh_recommendations, save_policy, save_volume
from storage.storage_inventory import protect_item
from storage.storage_cleanup_policy import preview_cleanup

def administrator(request: Request):
    user = backend_value("current_user")(request.headers, request.cookies)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Administratorrechte erforderlich.")


router = APIRouter(tags=["administration", "storage"], dependencies=[Depends(administrator)])


class PolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy: dict
    delete_confirmed: bool = False


class VolumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: str = Field(min_length=1, max_length=96)
    policy: dict
    confirm_mount: bool = False


class ConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: bool = False


class ProtectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protection: dict


async def _invoke(function, *args, **kwargs):
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/v1/storage/autopilot")
@router.get("/api/storage/autopilot")
async def api_storage_autopilot():
    return await _invoke(lambda: get_autopilot(queue_jobs=queue_context()))


@router.put("/api/v1/storage/autopilot")
@router.put("/api/storage/autopilot")
async def api_storage_autopilot_save(body: PolicyBody):
    policy = await _invoke(save_policy, body.policy, delete_confirmed=body.delete_confirmed)
    wake()
    return {"saved": True, "policy": policy}


@router.put("/api/v1/storage/autopilot/volume")
@router.put("/api/storage/autopilot/volume")
async def api_storage_autopilot_volume(body: VolumeBody):
    policy = await _invoke(save_volume, body.root, body.policy, confirm_mount=body.confirm_mount)
    wake()
    return {"saved": True, "policy": policy}


@router.get("/api/v1/storage/recommendations")
@router.get("/api/storage/recommendations")
async def api_storage_recommendations():
    return {"recommendations": await _invoke(lambda: refresh_recommendations(queue_context()))}


@router.post("/api/v1/storage/recommendations/{recommendation_id}/apply")
@router.post("/api/storage/recommendations/{recommendation_id}/apply")
async def api_storage_recommendation_apply(recommendation_id: str, body: ConfirmationBody):
    if not body.confirm:
        raise HTTPException(400, "Verschieben muss ausdrücklich bestätigt werden.")
    return {"job": await _invoke(lambda: apply_recommendation(recommendation_id, queue_jobs=queue_context(), playback_check=playback_idle, queue_check=queue_context))}


@router.post("/api/v1/storage/recommendations/{recommendation_id}/dismiss")
@router.post("/api/storage/recommendations/{recommendation_id}/dismiss")
async def api_storage_recommendation_dismiss(recommendation_id: str):
    await _invoke(dismiss_recommendation, recommendation_id)
    return {"dismissed": True}


@router.get("/api/v1/storage/activity")
@router.get("/api/storage/activity")
async def api_storage_activity():
    return {"activity": (await api_storage_autopilot())["activity"]}


@router.get("/api/v1/storage/cleanup/preview")
@router.get("/api/storage/cleanup/preview")
async def api_storage_cleanup_preview():
    return await _invoke(lambda: preview_cleanup(queue_context()))


@router.put("/api/v1/storage/inventory/{item_id}/protection")
@router.put("/api/storage/inventory/{item_id}/protection")
async def api_storage_protection(item_id: str, body: ProtectionBody):
    return {"protection": await _invoke(protect_item, item_id, body.protection)}


@router.post("/api/v1/storage/optimize")
@router.post("/api/storage/optimize")
async def api_storage_optimize():
    return await _invoke(optimize, manual=True)
