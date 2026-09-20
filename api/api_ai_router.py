"""Provider-neutral HTTP boundary for optional Royal Intelligence."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import core.config as appconfig
from integrations.jev_client import JevAuthenticationError, JevError, JevRateLimitError, normalize_jev_endpoint
from integrations.ollama_client import OllamaError, normalize_ollama_url


class AiConfigBody(BaseModel):
    enabled: bool = False
    provider: Literal["jev", "ollama"] = "ollama"
    url: str = Field(default="http://127.0.0.1:11434", max_length=500)
    model: str = Field(default="llama3.2:3b", max_length=120)
    timeout_seconds: int = Field(default=180, ge=5, le=300)
    jev_api_key: str = Field(default="", max_length=500)
    jev_endpoint: str = Field(default="https://api.typesafe.ai/v1/systemone", max_length=500)
    jev_model: str = Field(default="jev-latest", max_length=120)


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
    provider = config.get("provider", "ollama")
    configured = bool(config.get("enabled")) and (bool(config.get("jev_api_key")) if provider == "jev" else bool(config.get("url") and config.get("model")))
    return {"enabled": bool(config.get("enabled")), "provider": provider, "url": config.get("url", "http://127.0.0.1:11434"), "model": config.get("model", "llama3.2:3b"), "timeout_seconds": int(config.get("timeout_seconds", 180)), "jev_endpoint": config.get("jev_endpoint", "https://api.typesafe.ai/v1/systemone"), "jev_model": config.get("jev_model", "jev-latest"), "has_jev_api_key": bool(config.get("jev_api_key")), "configured": configured, "module_available": bool(availability and availability[0]), "module_detail": availability[1] if availability else "", "privacy": "JEV erhält kompakte Katalogmetadaten und ein Geschmacksprofil über eine Cloud-Entscheidungs-API." if provider == "jev" else "Ollama verarbeitet kompakte Katalogmetadaten und ein Geschmacksprofil lokal."}


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
            url, endpoint = normalize_ollama_url(body.url), normalize_jev_endpoint(body.jev_endpoint)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        current = state.ai_discovery.config()
        api_key = body.jev_api_key.strip() or current.get("jev_api_key", "")
        if body.enabled and body.provider == "jev" and not api_key:
            raise HTTPException(400, "Für JEV fehlt der API-Key.")
        if body.enabled and body.provider == "ollama" and not body.model.strip():
            raise HTTPException(400, "Für Ollama fehlt ein Modell.")
        config = {"enabled": body.enabled, "provider": body.provider, "url": url, "model": body.model.strip(), "timeout_seconds": body.timeout_seconds, "jev_api_key": api_key, "jev_endpoint": endpoint, "jev_model": body.jev_model.strip() or "jev-latest"}
        saved = await run_in_threadpool(appconfig.save_ai, body.enabled, url, config["model"], body.timeout_seconds, body.provider, config["jev_api_key"], endpoint, config["jev_model"])
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
        except JevAuthenticationError as exc: raise HTTPException(401, "JEV-Authentifizierung fehlgeschlagen.") from exc
        except JevRateLimitError as exc: raise HTTPException(429, "JEV-Anfragelimit erreicht.") from exc
        except (JevError, OllamaError, ValueError) as exc: raise HTTPException(502, "Intelligence-Provider ist nicht erreichbar oder antwortet ungültig.") from exc
        return result

    @router.post("/api/v1/intelligence/recommendations")
    @router.post("/api/intelligence/recommendations")
    @router.post("/api/v1/ai/recommendations")
    @router.post("/api/ai/recommendations")
    async def recommendations(body: AiRecommendationBody):
        config, available = state.ai_discovery.config(), _availability(state)
        if not available[0]: return {"enabled": bool(config.get("enabled")), "available": False, "recommendations": [], "message": available[1]}
        try: ranked = await run_in_threadpool(state.ai_discovery.recommend, [candidate.model_dump() for candidate in body.candidates], state.taste_profile.public_profile())
        except (JevError, OllamaError, ValueError): return {"enabled": True, "available": False, "recommendations": [], "message": "Royal Intelligence ist derzeit nicht verfügbar. Die klassische Startseite bleibt unverändert."}
        return {"enabled": True, "available": True, "provider": config.get("provider"), "model": config.get("jev_model") if config.get("provider") == "jev" else config.get("model"), "recommendations": ranked, "diagnostics": dict(state.ai_discovery.diagnostics)}

    return router
