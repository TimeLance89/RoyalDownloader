from __future__ import annotations

from unittest.mock import Mock

import pytest

from integrations.ai_discovery import AiDiscoveryService
from integrations.ollama_client import OllamaClient, OllamaError, normalize_ollama_url


def _candidate(key: str = "movie:1") -> dict:
    return {
        "key": key,
        "title": "Testfilm",
        "kind": "movie",
        "year": 2025,
        "rating": 7.5,
        "genres": ["Drama"],
        "description": "Eine Beschreibung.",
    }


def test_ollama_is_disabled_by_default_path_without_network(monkeypatch):
    service = AiDiscoveryService({
        "enabled": False,
        "url": "http://127.0.0.1:11434",
        "model": "local",
        "timeout_seconds": 20,
    })
    called = Mock()
    monkeypatch.setattr(OllamaClient, "recommend", called)
    assert service.recommend([_candidate()], {}) == []
    called.assert_not_called()


def test_recommendations_accept_only_supplied_keys_and_clamp_scores(monkeypatch):
    service = AiDiscoveryService({
        "enabled": True,
        "url": "http://ollama:11434",
        "model": "local",
        "timeout_seconds": 20,
    })
    monkeypatch.setattr(OllamaClient, "decide", lambda *_args: "invented|4|taste|1\nmovie:1|4|taste|1")
    result = service.recommend([_candidate()], {"dimensions": {}})
    assert result == [{
        "key": "movie:1", "score": 100, "angle": "taste",
        "confidence": 1.0, "noul": 1.0,
        "reason": "Starker Match mit deinem kompakten Geschmacksprofil.",
    }]


def test_invalid_or_empty_ai_result_is_non_authoritative(monkeypatch):
    service = AiDiscoveryService({
        "enabled": True,
        "url": "http://ollama:11434",
        "model": "local",
        "timeout_seconds": 20,
    })
    monkeypatch.setattr(OllamaClient, "decide", lambda *_args: "ungültige Antwort")
    result = service.recommend([_candidate()], {})
    assert result[0]["key"] == "movie:1"
    assert service.diagnostics["fallback"] is True


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://user:pw@host:11434", "ftp://host",
    "http://ollama:11434\npoison=true",
])
def test_ollama_url_rejects_non_http_and_embedded_credentials(url):
    with pytest.raises(ValueError):
        normalize_ollama_url(url)
