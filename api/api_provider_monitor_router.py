"""Administrator-only Sentinel API; legacy and versioned aliases share handlers."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


class MonitorConfigBody(BaseModel):
    enabled: bool = True
    interval_hours: int = Field(default=12, ge=1, le=168)
    intensity: str = Field(default="standard", pattern="^(light|standard|full)$")
    auto_repair: bool = True
    notify_changes: bool = False


class ProbeBody(BaseModel):
    intensity: str = Field(default="standard", pattern="^(light|standard|full)$")


class RepairActionBody(BaseModel):
    confirmed: bool = False


def create_provider_monitor_router(monitor, current_user):
    def administrator(request: Request):
        user = current_user(request.headers, request.cookies)
        if not user or user.get("role") != "admin":
            raise HTTPException(403, "Administratorrechte erforderlich.")

    router = APIRouter(tags=["administration"], dependencies=[Depends(administrator)])

    def check_provider(provider):
        from providers.catalog import PROVIDER_CATALOG
        if provider not in PROVIDER_CATALOG:
            raise HTTPException(404, "Provider nicht gefunden.")

    @router.get("/api/providers/diagnostics")
    @router.get("/api/v1/providers/diagnostics")
    def overview():
        return monitor.diagnostics()

    @router.put("/api/providers/monitor/config")
    @router.put("/api/v1/providers/monitor/config")
    def configure(body: MonitorConfigBody):
        return monitor.configure(body.model_dump())

    @router.post("/api/providers/probe-all")
    @router.post("/api/v1/providers/probe-all")
    def probe_all(body: ProbeBody):
        # Use the scheduler, not an unbounded job queue. All enabled sources get
        # staggered due times and run as concurrency slots become free.
        now = monitor.clock()
        for index, provider in enumerate(monitor.enabled()):
            monitor.store.update(provider, next_check_at=now + index * 30, requested_intensity=body.intensity)
        monitor.wake.set()
        return {"scheduled": True}

    @router.get("/api/providers/{provider}/diagnostics")
    @router.get("/api/v1/providers/{provider}/diagnostics")
    def detail(provider: str):
        check_provider(provider)
        return monitor.diagnostics(provider)["providers"][0]

    @router.post("/api/providers/{provider}/probe")
    @router.post("/api/v1/providers/{provider}/probe")
    def probe(provider: str, body: ProbeBody):
        check_provider(provider)
        if not monitor.request(provider, body.intensity):
            raise HTTPException(429, "Prüfung läuft oder Prüfbudget ist belegt. Kurz warten.", headers={"Retry-After": "60"})
        return {"started": True}

    @router.get("/api/providers/{provider}/history")
    @router.get("/api/v1/providers/{provider}/history")
    def history(provider: str):
        check_provider(provider)
        return {"history": monitor.store.entry(provider).get("history", [])}

    @router.get("/api/providers/{provider}/repairs")
    @router.get("/api/v1/providers/{provider}/repairs")
    def repairs(provider: str):
        check_provider(provider)
        return {"repairs": monitor.store.entry(provider).get("repairs", [])}

    @router.post("/api/providers/{provider}/repairs/{repair_id}/rollback")
    @router.post("/api/v1/providers/{provider}/repairs/{repair_id}/rollback")
    def rollback(provider: str, repair_id: str, body: RepairActionBody):
        check_provider(provider)
        if not body.confirmed:
            raise HTTPException(400, "Rollback muss bestätigt werden.")
        try:
            monitor.repairs.rollback(provider, repair_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"rolled_back": True}

    @router.post("/api/providers/{provider}/repairs/{repair_id}/activate")
    @router.post("/api/v1/providers/{provider}/repairs/{repair_id}/activate")
    def activate(provider: str, repair_id: str, body: RepairActionBody):
        check_provider(provider)
        if not body.confirmed:
            raise HTTPException(400, "Aktivierung muss bestätigt werden.")
        # Manual activation schedules a fresh full shadow probe. Never trust
        # stale evidence merely because an administrator clicked a button.
        repair = next((item for item in monitor.store.entry(provider).get("repairs", []) if item["id"] == repair_id), None)
        if not repair or repair["confidence"] != "high":
            raise HTTPException(409, "Reparatur nicht eindeutig validiert.")
        if not monitor.request(provider, "full", repair_id=repair_id):
            raise HTTPException(429, "Prüfbudget ist belegt.")
        return {"validation_started": True}

    return router
