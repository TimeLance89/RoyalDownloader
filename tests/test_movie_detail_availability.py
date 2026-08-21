import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api_discovery_router


def _movie(hosters):
    return SimpleNamespace(hosters=hosters)


def test_movie_detail_distinguishes_unavailable_hoster(monkeypatch):
    monkeypatch.setattr(
        api_discovery_router,
        "state",
        SimpleNamespace(fp_movies={}),
    )
    monkeypatch.setattr(api_discovery_router, "load_movie_for_slug", lambda _slug: None)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(api_discovery_router.api_movie("moflix:42:the-end-of-oak-street"))

    assert raised.value.status_code == 404
    assert raised.value.detail == {
        "code": "movie_hoster_unavailable",
        "message": "Aktuell ist für diesen Film kein Hoster verfügbar.",
    }


def test_movie_detail_uses_tmdb_identity_to_search_all_active_providers(monkeypatch):
    direct = _movie([])
    fallback = _movie([SimpleNamespace(url="https://hoster.test/embed/42")])
    calls = []
    state = SimpleNamespace(fp_movies={})

    def load(slug):
        calls.append(slug)
        return fallback if slug == "tmdb:42" else direct

    monkeypatch.setattr(api_discovery_router, "state", state)
    monkeypatch.setattr(api_discovery_router, "load_movie_for_slug", load)
    monkeypatch.setattr(
        api_discovery_router,
        "movie_detail_to_dict",
        lambda slug, movie: {"slug": slug, "hoster_count": len(movie.hosters)},
    )

    result = asyncio.run(
        api_discovery_router.api_movie(
            "moflix:7:the-end-of-oak-street",
            tmdb_id=42,
        )
    )

    assert calls == ["moflix:7:the-end-of-oak-street", "tmdb:42"]
    assert result == {
        "slug": "moflix:7:the-end-of-oak-street",
        "hoster_count": 1,
    }
    assert state.fp_movies["moflix:7:the-end-of-oak-street"] is fallback
