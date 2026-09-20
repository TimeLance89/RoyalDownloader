"""Small client for TypeSafe System One / JEV decision primitives.

This client deliberately exposes no chat or completion interface.  Royal
Intelligence sends bounded, typed Score/Choice questions only.
"""

from __future__ import annotations

from typing import Any

import requests


DEFAULT_JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevError(RuntimeError):
    category = "unavailable"


class JevAuthenticationError(JevError):
    category = "authentication"


class JevRateLimitError(JevError):
    category = "rate_limited"


class JevResponseError(JevError):
    category = "invalid_response"


def normalize_jev_endpoint(value: str) -> str:
    endpoint = str(value or DEFAULT_JEV_ENDPOINT).strip().rstrip("/")
    if not endpoint.startswith("https://") or len(endpoint) > 500 or any(ord(c) < 32 for c in endpoint):
        raise ValueError("JEV-Endpunkt muss eine gültige HTTPS-Adresse sein.")
    return endpoint


class JevClient:
    def __init__(self, api_key: str, endpoint: str = DEFAULT_JEV_ENDPOINT, model: str = "jev-latest", timeout_seconds: int = 20):
        self.api_key = str(api_key or "").strip()
        self.endpoint = normalize_jev_endpoint(endpoint)
        self.model = str(model or "jev-latest").strip() or "jev-latest"
        self.timeout_seconds = max(5, min(60, int(timeout_seconds)))

    def evaluate(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not self.api_key:
            raise JevAuthenticationError("JEV API-Key fehlt.")
        try:
            response = requests.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"state": state, "model": self.model, "questions": questions},
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise JevError("JEV-Zeitlimit überschritten.") from exc
        except requests.RequestException as exc:
            raise JevError("JEV ist nicht erreichbar.") from exc
        if response.status_code == 401:
            raise JevAuthenticationError("JEV-Authentifizierung fehlgeschlagen.")
        if response.status_code == 429:
            raise JevRateLimitError("JEV-Anfragelimit erreicht.")
        if response.status_code in {422, 529} or response.status_code >= 500:
            raise JevError("JEV konnte die Anfrage derzeit nicht verarbeiten.")
        try:
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise JevResponseError("JEV-Antwort ist ungültig.") from exc
        if not isinstance(result, dict):
            raise JevResponseError("JEV-Antwort hat ein ungültiges Format.")
        return result
