"""The standard monitor confirms anime tracks without downloading media."""

from types import SimpleNamespace

from application_services.provider_probe import ProviderProbe
from application_services.provider_monitor import ProviderMonitor
from media.provider_health import ProviderHealth


def test_standard_anime_probe_checks_both_tracks_and_seeds_video_candidates():
    calls = []
    detail = {"id": "fixture", "title": "Fixture", "episodes": [
        {"season": 1, "number": 1, "tracks": ["eng", "dub"]},
    ]}
    def episode(slug):
        calls.append(slug)
        return {"content_language": "de" if "|dub-" in slug else "en",
                "hosters": [{"name": "VOE", "url": "https://voe.example/e/fixture"}]}
    adapter = SimpleNamespace(session=SimpleNamespace(get=lambda _: True),
        browse=lambda **_: {"results": [detail]}, get_anime=lambda *_, **__: detail,
        get_episode=episode)
    probe = ProviderProbe(lambda _: adapter)
    result = probe.run("aniworld", "standard")
    assert len(calls) == 2
    assert set(result["details"][0]["content_languages"]) == {"de", "en"}
    assert result["hoster_candidates"]
    assert any(step["name"] == "hoster_structure" and step["ok"] for step in result["steps"])


def test_untested_sources_get_a_near_term_first_check(tmp_path):
    now = 2_000_000
    monitor = ProviderMonitor(tmp_path / "monitor.json", ProviderHealth(tmp_path / "health.json"),
                              lambda: ["aniworld"], clock=lambda: now)
    monitor._schedule("aniworld")
    assert now + 30 <= monitor.store.entry("aniworld")["next_check_at"] < now + 60
    monitor.store.update("aniworld", last_check_at=now)
    monitor._schedule("aniworld")
    assert monitor.store.entry("aniworld")["next_check_at"] >= now + 12 * 3600
    monitor.stop()

def test_standard_anime_evidence_confirms_the_german_availability_path(tmp_path, monkeypatch):
    now = 2_000_000
    result = {"steps": [{"name": "episode_detail", "ok": True, "code": "ok", "duration_ms": 0}],
              "details": [{"source": "fixture", "title": "Fixture", "media_type": "anime",
                           "identity": "fixture", "ok": True, "content_languages": ["de"]}],
              "responses": [], "hoster_candidates": [{"name": "VOE", "url": "https://voe.example/e/fixture"}]}
    monitor = ProviderMonitor(tmp_path / 'monitor.json', ProviderHealth(tmp_path / 'health.json'),
                              lambda: ['aniworld'], clock=lambda: now, languages=lambda: {'de'})
    monkeypatch.setattr(monitor.probe, 'run', lambda *_, **__: result)
    monkeypatch.setattr(monitor.hosters, 'diagnostics', lambda: [
        {'hoster': 'voe', 'providers': ['aniworld'], 'diagnosis': 'healthy',
         'last_check_at': now, 'metrics_24h': {'attempts': 0, 'success_rate': None}},
    ])
    monitor.check('aniworld', 'standard')
    assert monitor.diagnostics()['service']['coverage']['anime'] == 'healthy'
    monitor.stop()
