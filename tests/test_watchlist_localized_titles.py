import asyncio
from types import SimpleNamespace

import server


class _DeferredThread:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        pass


def test_watchlist_metadata_hydration_replaces_provider_title_with_localized_title(monkeypatch):
    previous_watchlist = server.state.watchlist
    server.state.watchlist = [{
        "base_slug": "georgie-and-mandys-first-marriage",
        "title": "Georgie and Mandy's First Marriage",
        "aliases": [],
        "tmdb_id": 219246,
        "cover_url": "/poster.jpg",
        "backdrop_url": "/backdrop.jpg",
    }]
    saved = []
    monkeypatch.setattr(server, "get_tmdb_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(server, "get_tmdb_series", lambda *_args, **_kwargs: {
        "tmdb_id": 219246,
        "title": "Georgie & Mandy",
        "original_title": "Georgie & Mandy's First Marriage",
        "cover_url": "/poster.jpg",
        "backdrop_url": "/backdrop.jpg",
    })
    monkeypatch.setattr(server, "_persist_watchlist_background", lambda: saved.append(True))

    try:
        server.hydrate_watchlist_artwork()

        entry = server.state.watchlist[0]
        assert entry["title"] == "Georgie & Mandy"
        assert "Georgie and Mandy's First Marriage" in entry["aliases"]
        assert entry["original_title"] == "Georgie & Mandy's First Marriage"
        assert entry["metadata_title_hydrated"] is True
        assert saved == [True]
    finally:
        server.state.watchlist = previous_watchlist


def test_new_watchlist_entry_stores_localized_title_and_provider_alias(monkeypatch):
    previous_watchlist = server.state.watchlist
    server.state.watchlist = []
    monkeypatch.setattr(server.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(server.appconfig, "save_watchlist", lambda _items: True)
    monkeypatch.setattr(server, "get_tmdb_series", lambda *_args, **_kwargs: {
        "tmdb_id": 219246,
        "title": "Georgie & Mandy",
        "original_title": "Georgie & Mandy's First Marriage",
    })

    try:
        asyncio.run(server.api_watchlist_add(server.WatchlistAddBody(
            base_slug="georgie-and-mandys-first-marriage",
            title="Georgie and Mandy's First Marriage",
            sample_url="https://example.invalid/series",
            known_slugs=[],
            tmdb_id=219246,
        )))

        entry = server.state.watchlist[0]
        assert entry["title"] == "Georgie & Mandy"
        assert "Georgie and Mandy's First Marriage" in entry["aliases"]
        assert entry["metadata_title_hydrated"] is True
    finally:
        server.state.watchlist = previous_watchlist
