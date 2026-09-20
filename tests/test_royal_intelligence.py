from unittest.mock import Mock

import pytest

from integrations.jev_client import JevAuthenticationError, JevClient, JevRateLimitError
from integrations.royal_intelligence import JevProvider, RoyalIntelligenceService, compact_candidates, profile_summary


def _candidate(number=1):
    return {"key": f"movie:{number}", "title": f"Titel {number}", "kind": "movie", "year": 2025, "rating": 7.5, "genres": ["Drama"], "description": "Kurz"}


def test_jev_payload_uses_official_system_one_primitives(monkeypatch):
    called = Mock(return_value={"answers": {"score_0": {"score": 4}, "angle_0": {"choice": "taste"}}})
    monkeypatch.setattr(JevClient, "evaluate", called)
    result = JevProvider({"jev_api_key": "secret"}).score_candidates({"preferences": {}}, [_candidate()])
    assert result == [{"key": "movie:1", "score": 100, "angle": "taste"}]
    _, questions = called.call_args.args
    assert questions["score_0"]["type"] == "score"
    assert questions["angle_0"]["type"] == "choice"


def test_compact_state_contains_no_credentials():
    state = {"dimensions": {"genres": {"Drama": 5}}, "interactions": 2}
    serialized = str({"profile": profile_summary(state), "candidates": compact_candidates([_candidate()])})
    assert "secret" not in serialized
    assert "movie:1" in serialized


def test_disabled_service_never_invokes_provider(monkeypatch):
    service = RoyalIntelligenceService({"enabled": False, "provider": "jev"})
    monkeypatch.setattr(JevProvider, "score_candidates", Mock())
    assert service.recommend([_candidate()], {}) == []


def test_provider_changes_invalidate_cache(monkeypatch):
    service = RoyalIntelligenceService({"enabled": True, "provider": "jev", "jev_api_key": "secret"})
    mocked = Mock(return_value=[{"key": "movie:1", "score": 90, "angle": "taste"}])
    monkeypatch.setattr(JevProvider, "score_candidates", mocked)
    assert service.recommend([_candidate()], {})
    assert service.recommend([_candidate()], {})
    assert mocked.call_count == 1
    service.configure({"enabled": True, "provider": "jev", "jev_api_key": "changed", "jev_model": "jev-latest"})
    service.recommend([_candidate()], {})
    assert mocked.call_count == 2


@pytest.mark.parametrize("status,error", [(401, JevAuthenticationError), (429, JevRateLimitError)])
def test_jev_maps_sensitive_http_failures(monkeypatch, status, error):
    response = Mock(status_code=status)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: response)
    with pytest.raises(error):
        JevClient("secret").evaluate({}, {})
