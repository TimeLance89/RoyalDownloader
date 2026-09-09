from __future__ import annotations

from unittest.mock import Mock

import pytest

from ai_discovery import AiDiscoveryService
from ollama_client import OllamaClient, OllamaError, normalize_ollama_url


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
    monkeypatch.setattr(OllamaClient, "recommend", lambda *_args: {
        "recommendations": [
            {"key": "invented", "score": 100, "reason": "Nein"},
            {"key": "movie:1", "score": 140, "reason": "Passt zum Profil", "angle": "taste"},
        ]
    })
    result = service.recommend([_candidate()], {"dimensions": {}})
    assert result == [{
        "key": "movie:1", "score": 100,
        "reason": "Passt zum Profil", "angle": "taste",
    }]


def test_invalid_or_empty_ai_result_is_non_authoritative(monkeypatch):
    service = AiDiscoveryService({
        "enabled": True,
        "url": "http://ollama:11434",
        "model": "local",
        "timeout_seconds": 20,
    })
    monkeypatch.setattr(OllamaClient, "recommend", lambda *_args: {"recommendations": []})
    with pytest.raises(OllamaError):
        service.recommend([_candidate()], {})


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://user:pw@host:11434", "ftp://host",
    "http://ollama:11434\npoison=true",
])
def test_ollama_url_rejects_non_http_and_embedded_credentials(url):
    with pytest.raises(ValueError):
        normalize_ollama_url(url)
