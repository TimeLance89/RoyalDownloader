import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def intelligence_source():
    return "\n".join((ROOT / "web/js/features" / file).read_text(encoding="utf-8")
                     for file in ["home/recommendations.js", "settings/intelligence.js"])


def test_ai_discovery_is_optional_and_has_accessible_home_region():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = intelligence_source()
    assert 'id="home-ai-rail"' in index
    assert 'aria-labelledby="home-ai-title"' in index
    assert 'id="home-ai-rail" class="home-rail home-ai-rail" aria-labelledby="home-ai-title" hidden' in index
    assert "if (!getConfig().enabled)" in script
    assert 'rail.hidden = true' in script


def test_ai_ui_reuses_royal_home_cards_and_never_calls_queue_api():
    script = intelligence_source()
    assert "createHomeCard(entry" in script
    assert 'client.post("/api/intelligence/recommendations", { candidates }' in script
    assert "queueAdd" not in script
    assert "download" not in script.casefold()


def test_ai_status_distinguishes_saved_and_unsaved_activation():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = intelligence_source()
    assert "enabled !== config.enabled" in script
    assert "Aktivierung noch speichern." in script
    assert "Aktiviert · ${config.model" in script
    assert 'ai-discovery.js?v=' not in index


def test_enabled_ai_discovery_exposes_loading_and_failure_states():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = intelligence_source()
    assert 'id="home-ai-state"' in index
    assert 'id="home-ai-retry"' in index
    assert 'id="ai-timeout"' in index
    assert re.search(r'setAiDiscoveryState\(\s*"loading"', script)
    assert 'setAiDiscoveryState("error"' in script
    assert 'rail.hidden = !getConfig().enabled' in script


def test_background_refinement_keeps_the_existing_rail_stable():
    script = intelligence_source()
    assert 'const keepVisibleRail = mode === "loading" && data.recommendations.length > 0;' in script
    assert 'panel.hidden = mode === "ready" || keepVisibleRail;' in script


def test_royal_intelligence_exposes_provider_and_module_aware_ui():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = intelligence_source()
    assert 'id="ai-url"' in index
    assert 'Royal Reflex' in index
    assert "getConfig().moduleAvailable" in script
    assert "Cloud-Entscheidungs-API" not in script
