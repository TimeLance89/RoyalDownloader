"""HTTP boundary for the built-in module manager."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.module_manager import ModuleDependencyError


class ModuleStateBody(BaseModel):
    enabled: bool
    cascade: bool = False


def create_module_router(manager) -> APIRouter:
    router = APIRouter(tags=["modules"])

    @router.get("/api/modules")
    @router.get("/api/v1/modules")
    def get_modules():
        return manager.payload()

    @router.put("/api/modules/{module_id}")
    @router.put("/api/v1/modules/{module_id}")
    def set_module(module_id: str, body: ModuleStateBody):
        try:
            return manager.set_enabled(module_id, body.enabled, body.cascade)
        except KeyError as exc:
            raise HTTPException(404, "Modul nicht gefunden.") from exc
        except ModuleDependencyError as exc:
            raise HTTPException(409, {"message": str(exc), "modules": exc.modules}) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    return router
