"""Optional AI ranking layer over RoyalDownloader's existing discovery pool."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Mapping

from ollama_client import OllamaClient, OllamaError


class AiDiscoveryService:
    def __init__(self, config: Mapping[str, Any]):
        self._lock = threading.RLock()
        self._config = dict(config)
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def configure(self, config: Mapping[str, Any]) -> None:
        with self._lock:
            self._config = dict(config)
            self._cache.clear()

    def config(self) -> dict:
        with self._lock:
            return dict(self._config)

    def test(self) -> dict:
        cfg = self.config()
        models = OllamaClient(
            cfg["url"], cfg.get("model", ""), cfg.get("timeout_seconds", 180)
        ).models()
        return {
            "connected": True,
            "models": models,
            "model_available": cfg.get("model") in models,
        }

    @staticmethod
    def _profile_summary(profile: Mapping[str, Any]) -> dict:
        dimensions = profile.get("dimensions") or {}
        summarized = {}
        for name in ("genres", "tags", "directors", "actors", "media_types", "decades"):
            values = dimensions.get(name) or {}
            summarized[name] = sorted(
                ((str(key)[:80], round(float(value), 2)) for key, value in values.items()),
                key=lambda item: abs(item[1]), reverse=True,
            )[:8]
        return {
            "preferences": summarized,
            "interactions": int(profile.get("interactions") or 0),
            "confidence": float(profile.get("confidence") or 0),
        }

    def recommend(self, candidates: list[dict], profile: Mapping[str, Any]) -> list[dict]:
        cfg = self.config()
        if not cfg.get("enabled"):
            return []
        compact = [{
            "key": item["key"],
            "title": item["title"],
            "kind": item["kind"],
            "year": item.get("year"),
            "rating": item.get("rating"),
            "genres": item.get("genres", [])[:10],
            "description": str(item.get("description") or "")[:180],
        } for item in candidates[:24]]
        fingerprint = hashlib.sha256(json.dumps(
            {"model": cfg.get("model"), "profile": self._profile_summary(profile), "items": compact},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._cache.get(fingerprint)
            if cached and time.time() - cached[0] < 6 * 60 * 60:
                return list(cached[1])

        prompt = json.dumps({
            "task": "Wähle bis zu 8 interessante Downloads, vielfältig über Typ und Genre.",
            "taste_profile": self._profile_summary(profile),
            "candidates": compact,
        }, ensure_ascii=False)
        raw = OllamaClient(
            cfg["url"], cfg.get("model", ""), cfg.get("timeout_seconds", 180)
        ).recommend(prompt)
        allowed = {item["key"] for item in compact}
        recommendations = []
        seen = set()
        raw_recommendations = raw.get("recommendations", [])
        if not isinstance(raw_recommendations, list):
            raise OllamaError("Ollama hat keine gültige Empfehlungsliste geliefert.")
        for item in raw_recommendations:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if key not in allowed or key in seen:
                continue
            seen.add(key)
            try:
                score = max(0, min(100, int(round(float(item.get("score") or 0)))))
            except (TypeError, ValueError):
                score = 0
            angle = str(item.get("angle") or "taste").strip().lower()
            if angle not in {"taste", "adjacent", "surprise"}:
                angle = "taste"
            recommendations.append({
                "key": key,
                "score": score,
                "reason": str(item.get("reason") or "Passt zu deinem Royal-Profil.").strip()[:180],
                "angle": angle,
            })
            if len(recommendations) >= 8:
                break
        if not recommendations:
            raise OllamaError("Ollama hat keine gültigen Kandidaten ausgewählt.")
        with self._lock:
            self._cache = {fingerprint: (time.time(), recommendations)}
        return recommendations
