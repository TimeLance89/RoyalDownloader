import asyncio

import pytest
from fastapi import HTTPException

import server
from providers.models import FilmpalastMovie
from taste_profile import TasteProfileStore


def _use_store(monkeypatch, tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    monkeypatch.setattr(server.state, "taste_profile", store)
    return store


def test_taste_api_records_feedback_and_resets(monkeypatch, tmp_path):
    _use_store(monkeypatch, tmp_path)
    event = server.TasteEventBody(
        action="open",
        source="android",
        media_type="movie",
        item_key="movie:1",
        metadata={"genres": ["Action"]},
    )
    response = asyncio.run(server.api_taste_event(event))
    assert response["recorded"] is True
    assert response["profile"]["genres"]["Action"] == 0.8

    feedback = server.TasteFeedbackBody(
        item_key="movie:1",
        action="dislike",
        media_type="movie",
        metadata={"genres": ["Action"]},
    )
    response = asyncio.run(server.api_taste_feedback(feedback))
    assert response["profile"]["blocked_items"] == ["movie:1"]

    response = asyncio.run(server.api_taste_profile_reset())
    assert response["profile"]["interactions"] == 0


def test_taste_api_rejects_unknown_actions(monkeypatch, tmp_path):
    _use_store(monkeypatch, tmp_path)
    body = server.TasteEventBody(action="spy", item_key="movie:1")
    with pytest.raises(HTTPException) as raised:
        asyncio.run(server.api_taste_event(body))
    assert raised.value.status_code == 400


def test_queue_taste_collapses_episodes_and_distinguishes_anime(monkeypatch, tmp_path):
    store = _use_store(monkeypatch, tmp_path)
    series = FilmpalastMovie(title="Eine Serie S01E01", url="", genres=["Drama"])
    anime = FilmpalastMovie(title="Anime S01E001", url="", genres=["Fantasy"])
    server._record_download_taste([
        (series, "eine-serie-s01e01"),
        (series, "eine-serie-s01e02"),
    ], "telegram")
    server._record_download_taste([
        (anime, "mkissa:abcdef|sub-s01e001"),
    ], "anime")
    profile = store.public_profile()
    assert profile["interactions"] == 2
    assert profile["kinds"]["series"] == 3.5
    assert profile["kinds"]["anime"] == 3.5
    assert {event["key"] for event in profile["recent"]} == {
        "series:eine-serie", "anime:abcdef",
    }


def test_all_taste_routes_have_versioned_and_browser_aliases():
    routes = {
        (method, route.path)
        for route in server.app.routes
        for method in (getattr(route, "methods", None) or [])
    }
    for method, suffix in {
        ("GET", "/taste/profile"),
        ("POST", "/taste/events"),
        ("POST", "/taste/feedback"),
        ("POST", "/taste/import"),
        ("POST", "/taste/reset"),
    }:
        assert (method, f"/api{suffix}") in routes
        assert (method, f"/api/v1{suffix}") in routes
