"""Provider-neutral, presentation-only ranking for existing catalog entries."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Mapping, Protocol

from integrations.jev_client import JevClient, JevError
from integrations.ollama_client import OllamaClient, OllamaError


ANGLES = ("taste", "adjacent", "surprise")


class IntelligenceProvider(Protocol):
    def test(self) -> dict: ...
    def score_candidates(self, profile: dict, candidates: list[dict]) -> list[dict]: ...


def profile_summary(profile: Mapping[str, Any]) -> dict:
    dimensions = profile.get("dimensions") or {}
    preferences = {}
    for name in ("genres", "tags", "directors", "actors", "media_types", "decades"):
        values = dimensions.get(name) or {}
        preferences[name] = [str(key)[:80] for key, _ in sorted(
            values.items(), key=lambda item: abs(float(item[1])), reverse=True,
        )[:8]]
    return {"preferences": preferences, "interactions": int(profile.get("interactions") or 0), "confidence": round(float(profile.get("confidence") or 0), 2)}


def compact_candidates(candidates: list[dict]) -> list[dict]:
    return [{"key": str(item["key"]), "title": str(item["title"])[:160], "kind": str(item["kind"]), "year": item.get("year"), "rating": item.get("rating"), "genres": [str(value)[:60] for value in item.get("genres", [])[:10]], "description": str(item.get("description") or "")[:180]} for item in candidates[:24]]


class JevProvider:
    def __init__(self, config: Mapping[str, Any]): self.config = dict(config)

    def _client(self) -> JevClient:
        return JevClient(self.config.get("jev_api_key", ""), self.config.get("jev_endpoint", ""), self.config.get("jev_model", "jev-latest"), self.config.get("timeout_seconds", 20))

    def test(self) -> dict:
        # A minimal typed decision verifies credentials without user data.
        self._client().evaluate({"probe": "connection"}, {"probe": {"type": "noul", "instructions": "Return whether this connection probe is valid."}})
        return {"connected": True, "provider": "jev"}

    def score_candidates(self, profile: dict, candidates: list[dict]) -> list[dict]:
        questions: dict[str, dict] = {}
        for index, candidate in enumerate(candidates):
            questions[f"score_{index}"] = {"type": "score", "instructions": f"Rate the relevance of candidate {index} for this compact taste profile.", "criteria": ["No meaningful fit", "Weak fit", "Moderate fit", "Strong fit", "Excellent fit"]}
            questions[f"angle_{index}"] = {"type": "choice", "instructions": f"Classify candidate {index} as a direct fit, nearby discovery, or intentional surprise.", "options": {"taste": "Direct fit to established preferences", "adjacent": "Related discovery close to preferences", "surprise": "Deliberate relevant outlier"}}
        result = self._client().evaluate({"taste_profile": profile, "candidates": candidates}, questions)
        answers = result.get("answers", result.get("results", result))
        if not isinstance(answers, dict): raise JevError("JEV-Antwort enthält keine Entscheidungen.")
        ranked = []
        for index, candidate in enumerate(candidates):
            score_answer, angle_answer = answers.get(f"score_{index}"), answers.get(f"angle_{index}")
            if not isinstance(score_answer, dict): continue
            try: score = round(max(0, min(4, float(score_answer.get("score")))) / 4 * 100)
            except (TypeError, ValueError): continue
            angle = str(angle_answer.get("choice") if isinstance(angle_answer, dict) else "taste").lower()
            ranked.append({"key": candidate["key"], "score": score, "angle": angle if angle in ANGLES else "taste"})
        if not ranked: raise JevError("JEV lieferte keine verwertbaren Bewertungen.")
        return ranked


class OllamaProvider:
    def __init__(self, config: Mapping[str, Any]): self.config = dict(config)
    def _client(self): return OllamaClient(self.config["url"], self.config.get("model", ""), self.config.get("timeout_seconds", 180))
    def test(self) -> dict:
        models = self._client().models()
        return {"connected": True, "models": models, "model_available": self.config.get("model") in models, "provider": "ollama"}
    def score_candidates(self, profile: dict, candidates: list[dict]) -> list[dict]:
        raw = self._client().recommend(json.dumps({"task": "Wähle bis zu 8 interessante Titel, vielfältig über Typ und Genre.", "taste_profile": profile, "candidates": candidates}, ensure_ascii=False))
        allowed, result = {item["key"] for item in candidates}, []
        for item in raw.get("recommendations", []) if isinstance(raw.get("recommendations", []), list) else []:
            if not isinstance(item, dict) or str(item.get("key")) not in allowed: continue
            try: score = round(max(0, min(100, float(item.get("score")))))
            except (TypeError, ValueError): continue
            angle = str(item.get("angle") or "taste").lower()
            result.append({"key": str(item["key"]), "score": score, "angle": angle if angle in ANGLES else "taste", "reason": str(item.get("reason") or "")[:180]})
        if not result: raise OllamaError("Ollama hat keine gültigen Kandidaten ausgewählt.")
        return result


class RoyalIntelligenceService:
    """Only scores supplied metadata; it has no downloader or queue dependency."""
    def __init__(self, config: Mapping[str, Any]):
        self._lock, self._config, self._cache = threading.RLock(), dict(config), {}
        self.diagnostics: dict = {}
    def configure(self, config: Mapping[str, Any]) -> None:
        with self._lock: self._config, self._cache = dict(config), {}
    def config(self) -> dict:
        with self._lock: return dict(self._config)
    def configuration_state(self) -> tuple[bool, str]:
        cfg = self.config()
        if not cfg.get("enabled"): return False, "Royal Intelligence ist in den Einstellungen deaktiviert"
        if cfg.get("provider") == "jev" and not cfg.get("jev_api_key"): return False, "JEV API-Key fehlt"
        if cfg.get("provider") == "ollama" and not (cfg.get("url") and cfg.get("model")): return False, "Ollama-Konfiguration fehlt"
        return True, "Royal Intelligence konfiguriert"
    def _provider(self, cfg): return JevProvider(cfg) if cfg.get("provider") == "jev" else OllamaProvider(cfg)
    def test(self, config: Mapping[str, Any] | None = None) -> dict: return self._provider(dict(config or self.config())).test()
    @staticmethod
    def _reason(candidate: dict, profile: dict, angle: str) -> str:
        liked = {item.casefold() for item in profile["preferences"].get("genres", [])}
        overlap = [genre for genre in candidate.get("genres", []) if genre.casefold() in liked]
        if overlap: return f"Passt zu deinen Vorlieben für {', '.join(overlap[:2])}."
        if angle == "surprise": return "Liegt sinnvoll außerhalb deiner üblichen Auswahl."
        if angle == "adjacent": return "Erweitert deine bisherigen Vorlieben behutsam."
        return "Starker Match mit deinem kompakten Geschmacksprofil."
    @staticmethod
    def _select(scored: list[dict], candidates: list[dict], profile: dict) -> list[dict]:
        by_key, selected, seen_genres = {item["key"]: item for item in candidates}, [], set()
        for item in sorted(scored, key=lambda value: (-value["score"], value["key"])):
            candidate = by_key.get(item["key"])
            if not candidate or item["key"] in {entry["key"] for entry in selected}: continue
            genres = {str(genre).casefold() for genre in candidate.get("genres", [])}
            if len(selected) >= 4 and genres and genres <= seen_genres and len(selected) < 8: continue
            selected.append({**item, "reason": item.get("reason") or RoyalIntelligenceService._reason(candidate, profile, item["angle"])})
            seen_genres.update(genres)
            if len(selected) == 8: break
        return selected
    def recommend(self, candidates: list[dict], profile: Mapping[str, Any]) -> list[dict]:
        cfg, compact, summary = self.config(), compact_candidates(candidates), profile_summary(profile)
        if not cfg.get("enabled"): return []
        fingerprint = hashlib.sha256(json.dumps({"provider": cfg.get("provider"), "model": cfg.get("jev_model") if cfg.get("provider") == "jev" else cfg.get("model"), "profile": summary, "candidates": compact}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            cached = self._cache.get(fingerprint)
            if cached and time.time() - cached[0] < 21600:
                self.diagnostics = {"provider": cfg.get("provider"), "candidate_count": len(compact), "selected_count": len(cached[1]), "cache": "hit"}
                return list(cached[1])
        started = time.monotonic()
        result = self._select(self._provider(cfg).score_candidates(summary, compact), compact, summary)
        if not result: raise JevError("Keine Empfehlungen verfügbar.")
        with self._lock: self._cache[fingerprint] = (time.time(), result)
        self.diagnostics = {"provider": cfg.get("provider"), "candidate_count": len(compact), "selected_count": len(result), "cache": "miss", "duration_ms": round((time.monotonic()-started)*1000)}
        return result
