"""System and administration routes with no domain-state dependencies."""

from collections.abc import Callable

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool


async def v1_health() -> dict[str, str | int]:
    return {"status": "ok", "api_version": 1}


async def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


def create_system_router(cache_diagnostics: Callable[[], list[dict]]) -> APIRouter:
    router = APIRouter(tags=["system"])

    router.add_api_route("/api/v1/health", v1_health, methods=["GET"])
    router.add_api_route("/api/health", legacy_health, methods=["GET"])

    @router.get("/api/v1/diagnostics/caches")
    async def api_runtime_cache_diagnostics():
        return {"caches": await run_in_threadpool(cache_diagnostics)}

    return router
