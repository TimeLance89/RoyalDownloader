import asyncio
import json
from types import SimpleNamespace

import pytest

import api_discovery_router
from home_layout import HOME_RAIL_IDS, HomeLayoutStore


def test_home_layout_defaults_keep_existing_rails_and_offer_more(tmp_path):
    store = HomeLayoutStore(tmp_path / "home_layout.json")

    layout = store.public_layout()

    assert layout["hero_visible"] is True
    assert layout["rail_order"] == list(HOME_RAIL_IDS)
    assert layout["hidden_rails"] == [
        "new_movies", "new_series", "high_rated", "movies", "library",
    ]


def test_home_layout_is_normalized_and_persisted_atomically(tmp_path):
    path = tmp_path / "home_layout.json"
    store = HomeLayoutStore(path)

    saved = store.update({
        "hero_visible": False,
        "rail_order": ["library", "top", "library", "unknown"],
        "hidden_rails": ["genre", "unknown"],
    })

    assert saved["rail_order"][:2] == ["library", "top"]
    assert len(saved["rail_order"]) == len(HOME_RAIL_IDS)
    assert saved["hidden_rails"] == ["genre"]
    assert HomeLayoutStore(path).public_layout() == saved
    assert json.loads(path.read_text(encoding="utf-8")) == saved


def test_home_layout_rejects_an_empty_start_page(tmp_path):
    store = HomeLayoutStore(tmp_path / "home_layout.json")

    with pytest.raises(ValueError, match="Mindestens eine"):
        store.update({"hidden_rails": list(HOME_RAIL_IDS)})


def test_home_layout_api_uses_shared_server_store(monkeypatch, tmp_path):
    store = HomeLayoutStore(tmp_path / "home_layout.json")
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(home_layout=store))
    body = api_discovery_router.HomeLayoutBody(
        hero_visible=False,
        rail_order=["movies", "personal"],
        hidden_rails=["top"],
    )

    saved = asyncio.run(api_discovery_router.api_home_layout_put(body))
    loaded = asyncio.run(api_discovery_router.api_home_layout_get())

    assert loaded == saved
    assert loaded["hero_visible"] is False
    assert loaded["rail_order"][0] == "movies"
    assert loaded["hidden_rails"] == ["top"]
