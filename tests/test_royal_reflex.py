from unittest.mock import Mock

import pytest

from integrations.royal_intelligence import RoyalIntelligenceService, pre_rank
from integrations.royal_reflex import ReflexError, RoyalReflex


def _reflex(lines):
    client = Mock(); client.decide.return_value = lines
    return RoyalReflex(client)


def test_reflex_validates_choice_score_and_noul():
    result = _reflex("movie:1|4|taste|0.9").evaluate({}, {"movie:1": {"type": "reflex"}})["movie:1"]
    assert result["choice"]["choice"] == "taste"
    assert result["score"]["normalized"] == 100
    assert result["noul"]["noul"] == 0.9
    assert result["choice"]["probabilities"] is None


@pytest.mark.parametrize("line", ["movie:1|5|taste|0.5", "movie:1|2|unknown|0.5", "text instead"])
def test_reflex_rejects_unknown_or_unstructured_output(line):
    with pytest.raises(ReflexError): _reflex(line).evaluate({}, {"movie:1": {"type": "reflex"}})


def test_disabled_intelligence_never_calls_local_inference(monkeypatch):
    service = RoyalIntelligenceService({"enabled": False, "url": "http://ollama:11434", "model": "small"})
    called = Mock()
    monkeypatch.setattr("integrations.royal_intelligence.OllamaReflexProvider.score_candidates", called)
    assert service.recommend([{"key": "movie:1", "title": "T", "kind": "movie"}], {}) == []
    called.assert_not_called()


def test_model_change_invalidates_cache(monkeypatch):
    service = RoyalIntelligenceService({"enabled": True, "url": "http://ollama:11434", "model": "small"})
    scored = Mock(return_value=[{"key": "movie:1", "score": 90, "angle": "taste", "confidence": 1, "noul": .9}])
    monkeypatch.setattr("integrations.royal_intelligence.OllamaReflexProvider.score_candidates", scored)
    candidate = {"key": "movie:1", "title": "T", "kind": "movie", "genres": []}
    assert service.recommend([candidate], {})
    service.recommend([candidate], {})
    assert scored.call_count == 1
    service.configure({"enabled": True, "url": "http://ollama:11434", "model": "other"})
    service.recommend([candidate], {})
    assert scored.call_count == 2


def test_pre_ranking_limits_the_ollama_batch_to_ten_candidates():
    profile = {"preferences": {"genres": ["Drama"]}}
    candidates = [{"key": f"movie:{index}", "rating": index % 10, "genres": ["Drama"]} for index in range(24)]
    assert len(pre_rank(candidates, profile)) == 10


def test_ollama_failure_returns_deterministic_fallback(monkeypatch):
    service = RoyalIntelligenceService({"enabled": True, "url": "http://ollama:11434", "model": "small"})
    monkeypatch.setattr("integrations.royal_intelligence.OllamaReflexProvider.score_candidates", Mock(side_effect=ReflexError("offline")))
    candidates = [{"key": "movie:1", "title": "T", "kind": "movie", "rating": 8, "genres": []}]
    assert service.recommend(candidates, {})[0]["key"] == "movie:1"
    assert service.diagnostics["fallback"] is True
