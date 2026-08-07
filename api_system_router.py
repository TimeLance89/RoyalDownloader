"""System and administration routes with no domain-state dependencies."""

import os
import time
from collections.abc import Callable

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool


# A browser can survive an in-app update while the Python process is replaced.
# The instance token lets the already-open frontend notice that it is talking to
# a new server process and reload its CSS/JavaScript exactly once.
SERVER_INSTANCE = f"{os.getpid()}-{time.time_ns()}"


async def v1_health() -> dict[str, str | int]:
    return {"status": "ok", "api_version": 1, "instance": SERVER_INSTANCE}


async def legacy_health() -> dict[str, str]:
    return {"status": "ok", "instance": SERVER_INSTANCE}


def create_system_router(
    cache_diagnostics: Callable[[], list[dict]],
    capabilities: Callable[[], dict] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["system"])

    router.add_api_route("/api/v1/health", v1_health, methods=["GET"])
    router.add_api_route("/api/health", legacy_health, methods=["GET"])

    if capabilities is not None:
        router.add_api_route("/api/v1/capabilities", capabilities, methods=["GET"])

    @router.get("/api/v1/diagnostics/caches")
    async def api_runtime_cache_diagnostics():
        return {"caches": await run_in_threadpool(cache_diagnostics)}

    return router
