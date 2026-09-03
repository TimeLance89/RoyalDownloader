from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_discovery_is_optional_and_has_accessible_home_region():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "ai-discovery.js").read_text(encoding="utf-8")
    assert 'id="home-ai-rail"' in index
    assert 'aria-labelledby="home-ai-title"' in index
    assert 'id="home-ai-rail" class="home-rail home-ai-rail" aria-labelledby="home-ai-title" hidden' in index
    assert "if (!state.ai.enabled)" in script
    assert 'rail.hidden = true' in script


def test_ai_ui_reuses_royal_home_cards_and_never_calls_queue_api():
    script = (ROOT / "web" / "ai-discovery.js").read_text(encoding="utf-8")
    assert "createHomeCard(entry" in script
    assert "api.aiRecommendations(candidates)" in script
    assert "queueAdd" not in script
    assert "download" not in script.casefold()
