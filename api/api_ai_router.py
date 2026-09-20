"""Provider-neutral HTTP boundary for optional Royal Intelligence."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import core.config as appconfig
from integrations.ollama_client import OllamaError, normalize_ollama_url
from integrations.royal_reflex import ReflexError


class AiConfigBody(BaseModel):
    enabled: bool = False
    url: str = Field(default="http://127.0.0.1:11434", max_length=500)
    model: str = Field(default="llama3.2:3b", max_length=120)
    timeout_seconds: int = Field(default=180, ge=5, le=300)


class AiCandidate(BaseModel):
    key: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["movie", "series", "anime"]
    year: str | int | None = None
    rating: float | None = Field(default=None, ge=0, le=10)
    genres: list[str] = Field(default_factory=list, max_length=12)
    description: str = Field(default="", max_length=800)


class AiRecommendationBody(BaseModel):
    candidates: list[AiCandidate] = Field(min_length=1, max_length=48)


def _public_config(config: dict, availability: tuple[bool, str] | None = None) -> dict:
    configured = bool(config.get("enabled") and config.get("url") and config.get("model"))
    return {"enabled": bool(config.get("enabled")), "backend": "ollama", "url": config.get("url", "http://127.0.0.1:11434"), "model": config.get("model", "llama3.2:3b"), "timeout_seconds": int(config.get("timeout_seconds", 180)), "configured": configured, "module_available": bool(availability and availability[0]), "module_detail": availability[1] if availability else "", "privacy": "Royal Reflex verarbeitet kompakte Katalogmetadaten und ein Geschmacksprofil ausschließlich lokal über Ollama."}


def _availability(state) -> tuple[bool, str]:
    return state.module_manager.availability("royal-intelligence")


def create_ai_router(state) -> APIRouter:
    router = APIRouter(tags=["royal-intelligence"])

    @router.get("/api/v1/intelligence/config")
    @router.get("/api/intelligence/config")
    @router.get("/api/v1/ai/config")
    @router.get("/api/ai/config")
    async def get_config():
        return _public_config(state.ai_discovery.config(), _availability(state))

    @router.post("/api/v1/intelligence/config")
    @router.post("/api/intelligence/config")
    @router.post("/api/v1/ai/config")
    @router.post("/api/ai/config")
    async def set_config(body: AiConfigBody):
        try:
            url = normalize_ollama_url(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if body.enabled and not body.model.strip():
            raise HTTPException(400, "Für Ollama fehlt ein Modell.")
        config = {"enabled": body.enabled, "provider": "ollama", "url": url, "model": body.model.strip(), "timeout_seconds": body.timeout_seconds}
        saved = await run_in_threadpool(appconfig.save_ai, body.enabled, url, config["model"], body.timeout_seconds)
        if not saved: raise HTTPException(500, "Intelligence-Einstellungen konnten nicht gespeichert werden.")
        state.ai_discovery.configure(config)
        # The visible activation control maps to the authoritative module
        # lifecycle; it never starts a provider independently.
        if state.module_manager.is_enabled("royal-intelligence") != body.enabled:
            state.module_manager.set_enabled("royal-intelligence", body.enabled)
        else:
            state.module_manager.reconcile("royal-intelligence")
        return {**_public_config(config, _availability(state)), "saved": True}

    @router.post("/api/v1/intelligence/test")
    @router.post("/api/intelligence/test")
    @router.post("/api/v1/ai/test")
    @router.post("/api/ai/test")
    async def test_connection(body: AiConfigBody | None = None):
        config = state.ai_discovery.config() if body is None else body.model_dump()
        try: result = await run_in_threadpool(state.ai_discovery.test, config)
        except (ReflexError, OllamaError, ValueError) as exc: raise HTTPException(502, "Ollama ist nicht erreichbar oder antwortet ungültig.") from exc
        return result

    @router.post("/api/v1/intelligence/recommendations")
    @router.post("/api/intelligence/recommendations")
    @router.post("/api/v1/ai/recommendations")
    @router.post("/api/ai/recommendations")
    async def recommendations(body: AiRecommendationBody):
        config, available = state.ai_discovery.config(), _availability(state)
        if not available[0]: return {"enabled": bool(config.get("enabled")), "available": False, "recommendations": [], "message": available[1]}
        try: ranked = await run_in_threadpool(state.ai_discovery.recommend, [candidate.model_dump() for candidate in body.candidates], state.taste_profile.public_profile())
        except (ReflexError, OllamaError, ValueError): return {"enabled": True, "available": False, "recommendations": [], "message": "Royal Reflex ist derzeit nicht verfügbar. Die klassische Startseite bleibt unverändert."}
        return {"enabled": True, "available": True, "backend": "ollama", "model": config.get("model"), "recommendations": ranked, "diagnostics": dict(state.ai_discovery.diagnostics)}

    return router
