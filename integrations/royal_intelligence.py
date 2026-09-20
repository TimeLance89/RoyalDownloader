"""Presentation-only ranking over existing catalog candidates via Royal Reflex."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Mapping, Protocol

from integrations.ollama_client import OllamaClient, OllamaError
from integrations.royal_reflex import ReflexError, RoyalReflex


class IntelligenceProvider(Protocol):
    def test(self) -> dict: ...
    def score_candidates(self, profile: dict, candidates: list[dict]) -> list[dict]: ...


def profile_summary(profile: Mapping[str, Any]) -> dict:
    dimensions, preferences = profile.get("dimensions") or {}, {}
    for name in ("genres", "tags", "directors", "actors", "media_types", "decades"):
        values = dimensions.get(name) or {}
        preferences[name] = [str(key)[:80] for key, _ in sorted(values.items(), key=lambda item: abs(float(item[1])), reverse=True)[:8]]
    return {"preferences": preferences, "interactions": int(profile.get("interactions") or 0), "confidence": round(float(profile.get("confidence") or 0), 2)}


def compact_candidates(candidates: list[dict]) -> list[dict]:
    return [{"key": str(item["key"]), "title": str(item["title"])[:80], "kind": str(item["kind"]), "year": item.get("year"), "rating": item.get("rating"), "genres": [str(value)[:40] for value in item.get("genres", [])[:5]], "description": str(item.get("description") or "")[:70]} for item in candidates[:24]]


def pre_rank(candidates: list[dict], profile: dict, limit: int = 10) -> list[dict]:
    """Cheap deterministic filter before the single local inference."""
    preferred = {value.casefold() for value in profile["preferences"].get("genres", [])}
    def score(item):
        overlap = len(preferred & {str(genre).casefold() for genre in item.get("genres", [])})
        return overlap * 25 + min(10, float(item.get("rating") or 0)) * 3
    return sorted(candidates, key=lambda item: (-score(item), item["key"]))[:limit]


class OllamaReflexProvider:
    def __init__(self, config: Mapping[str, Any]): self.config = dict(config)
    def _client(self): return OllamaClient(self.config["url"], self.config.get("model", ""), self.config.get("timeout_seconds", 180))
    def test(self) -> dict:
        models = self._client().models()
        return {"connected": True, "models": models, "model_available": self.config.get("model") in models, "provider": "ollama"}
    def score_candidates(self, profile: dict, candidates: list[dict]) -> list[dict]:
        questions = {item["key"]: {"type": "reflex", "task": "rate taste relevance, discovery angle and recommendation value"} for item in candidates}
        answers = RoyalReflex(self._client()).evaluate({"taste_profile": profile, "candidates": candidates}, questions)
        result = []
        for candidate in candidates:
            answer = answers.get(candidate["key"])
            if not answer: continue
            score, choice, noul = answer["score"], answer["choice"], answer["noul"]
            # Deterministic ranking blends validated taste score and the model's
            # bounded recommendation value; the model never selects titles.
            result.append({"key": candidate["key"], "score": round(score["normalized"] * 0.8 + noul["noul"] * 20), "angle": choice["choice"], "confidence": score["confidence"], "noul": noul["noul"]})
        if not result: raise ReflexError("Royal Reflex hat keine Kandidaten bewertet.")
        return result


class RoyalIntelligenceService:
    """Only scores supplied metadata; no downloader, queue or filesystem dependency."""
    def __init__(self, config: Mapping[str, Any]): self._lock, self._config, self._cache, self.diagnostics = threading.RLock(), dict(config), {}, {}
    def configure(self, config: Mapping[str, Any]) -> None:
        with self._lock: self._config, self._cache = dict(config), {}
    def config(self) -> dict:
        with self._lock: return dict(self._config)
    def configuration_state(self) -> tuple[bool, str]:
        cfg = self.config()
        if not cfg.get("enabled"): return False, "Royal Intelligence ist im Module Manager deaktiviert"
        return (True, "Royal Reflex mit Ollama konfiguriert") if cfg.get("url") and cfg.get("model") else (False, "Ollama-Konfiguration fehlt")
    def _provider(self, cfg): return OllamaReflexProvider(cfg)
    def test(self, config: Mapping[str, Any] | None = None) -> dict: return self._provider(dict(config or self.config())).test()
    @staticmethod
    def _reason(candidate, profile, angle):
        liked = {item.casefold() for item in profile["preferences"].get("genres", [])}
        overlap = [genre for genre in candidate.get("genres", []) if genre.casefold() in liked]
        if overlap: return f"Passt zu deinen Vorlieben für {', '.join(overlap[:2])}."
        if angle == "surprise": return "Bewusster Ausreißer außerhalb deiner üblichen Auswahl."
        if angle == "adjacent": return "Liegt nahe an deinem Geschmack und erweitert ihn behutsam."
        return "Starker Match mit deinem kompakten Geschmacksprofil."
    @staticmethod
    def _select(scored, candidates, profile):
        by_key, selected, seen_genres = {item["key"]: item for item in candidates}, [], set()
        for item in sorted(scored, key=lambda value: (-value["score"], value["key"])):
            candidate = by_key.get(item["key"])
            if not candidate or any(entry["key"] == item["key"] for entry in selected): continue
            genres = {str(genre).casefold() for genre in candidate.get("genres", [])}
            if len(selected) >= 4 and genres and genres <= seen_genres: continue
            selected.append({**item, "reason": RoyalIntelligenceService._reason(candidate, profile, item["angle"])})
            seen_genres.update(genres)
            if len(selected) == 8: break
        return selected
    def recommend(self, candidates: list[dict], profile: Mapping[str, Any]) -> list[dict]:
        cfg, compact, summary = self.config(), compact_candidates(candidates), profile_summary(profile)
        if not cfg.get("enabled"): return []
        fingerprint = hashlib.sha256(json.dumps({"reflex": RoyalReflex.VERSION, "model": cfg.get("model"), "profile": summary, "candidates": compact}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            cached = self._cache.get(fingerprint)
            if cached and time.time() - cached[0] < 21600:
                self.diagnostics = {"backend": "ollama", "candidate_count": len(compact), "selected_count": len(cached[1]), "cache": "hit"}
                return list(cached[1])
        shortlisted = pre_rank(compact, summary)
        started, fallback = time.monotonic(), False
        try:
            result = self._select(self._provider(cfg).score_candidates(summary, shortlisted), compact, summary)
        except (OllamaError, ReflexError):
            fallback = True
            # The rail remains useful if the optional local model is offline.
            result = self._select([{"key": item["key"], "score": round(min(100, float(item.get("rating") or 0) * 10)), "angle": "taste", "confidence": 0, "noul": 0} for item in shortlisted], compact, summary)
        if not result: raise ReflexError("Keine Empfehlungen verfügbar.")
        with self._lock: self._cache[fingerprint] = (time.time(), result)
        self.diagnostics = {"backend": "ollama", "candidate_count": len(compact), "shortlisted_count": len(shortlisted), "request_count": 0 if fallback else 1, "selected_count": len(result), "cache": "miss", "fallback": fallback, "duration_ms": round((time.monotonic()-started)*1000)}
        return result
