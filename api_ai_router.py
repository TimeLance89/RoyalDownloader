"""Authenticated configuration and inference routes for optional local AI."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config as appconfig
from ollama_client import OllamaClient, OllamaError, normalize_ollama_url


class AiConfigBody(BaseModel):
    enabled: bool = False
    url: str = Field(default="http://127.0.0.1:11434", max_length=500)
    model: str = Field(
        default="llama3.2:3b", min_length=1, max_length=120,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    timeout_seconds: int = Field(default=180, ge=30, le=300)


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


def _public_config(config: dict) -> dict:
    return {
        "enabled": bool(config.get("enabled")),
        "provider": "ollama",
        "url": config.get("url", "http://127.0.0.1:11434"),
        "model": config.get("model", "llama3.2:3b"),
        "timeout_seconds": int(config.get("timeout_seconds", 180)),
        "configured": bool(config.get("enabled") and config.get("url") and config.get("model")),
        "privacy": "An Ollama werden nur Metadaten und ein kompaktes Geschmacksprofil gesendet.",
    }


def create_ai_router(state) -> APIRouter:
    router = APIRouter(tags=["ai-discovery"])

    @router.get("/api/v1/ai/config")
    @router.get("/api/ai/config")
    async def get_config():
        return _public_config(state.ai_discovery.config())

    @router.post("/api/v1/ai/config")
    @router.post("/api/ai/config")
    async def set_config(body: AiConfigBody):
        try:
            url = normalize_ollama_url(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        model = body.model.strip()
        if body.enabled and not model:
            raise HTTPException(400, "Für Ollama fehlt ein Modell.")

        config = {
            "enabled": body.enabled,
            "provider": "ollama",
            "url": url,
            "model": model,
            "timeout_seconds": body.timeout_seconds,
        }
        saved = await run_in_threadpool(
            appconfig.save_ai, body.enabled, url, model, body.timeout_seconds,
        )
        if not saved:
            raise HTTPException(500, "KI-Einstellungen konnten nicht gespeichert werden.")
        state.ai_discovery.configure(config)
        return {**_public_config(config), "saved": True}

    @router.post("/api/v1/ai/test")
    @router.post("/api/ai/test")
    async def test_connection(body: AiConfigBody | None = None):
        try:
            if body is None:
                result = await run_in_threadpool(state.ai_discovery.test)
            else:
                client = OllamaClient(body.url, body.model, body.timeout_seconds)
                models = await run_in_threadpool(client.models)
                result = {
                    "connected": True,
                    "models": models,
                    "model_available": body.model.strip() in models,
                }
        except (OllamaError, ValueError) as exc:
            raise HTTPException(
                502, "Ollama ist nicht erreichbar oder antwortet ungültig."
            ) from exc
        return {**result, "provider": "ollama"}

    @router.post("/api/v1/ai/recommendations")
    @router.post("/api/ai/recommendations")
    async def recommendations(body: AiRecommendationBody):
        config = state.ai_discovery.config()
        if not config.get("enabled"):
            return {"enabled": False, "recommendations": []}
        try:
            ranked = await run_in_threadpool(
                state.ai_discovery.recommend,
                [candidate.model_dump() for candidate in body.candidates],
                state.taste_profile.public_profile(),
            )
        except (OllamaError, ValueError):
            # AI failure is a presentation-level degradation, not an API-wide
            # or downloader failure. The UI keeps the classic Royal ranking.
            return {
                "enabled": True,
                "available": False,
                "recommendations": [],
                "message": (
                    "Ollama konnte keine gültige Auswahl liefern. Verbindung prüfen, "
                    "Zeitlimit erhöhen oder ein kleineres Modell wählen."
                ),
            }
        return {
            "enabled": True,
            "available": True,
            "model": config.get("model", ""),
            "recommendations": ranked,
        }

    return router
