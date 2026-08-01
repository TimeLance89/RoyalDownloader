import server
from jellyfin_client import JellyfinClient
from providers.models import FilmpalastSeries, SeriesEpisode


def _series(base_slug="moflix:house-of-the-dragon"):
    return FilmpalastSeries(
        title="House of the Dragon",
        base_slug=base_slug,
        url=base_slug,
        genres=["Drama"],
        seasons={
            1: [
                SeriesEpisode(1, 1, f"{base_slug}-s01e01", "https://example.test/1"),
                SeriesEpisode(1, 2, f"{base_slug}-s01e02", "https://example.test/2"),
            ],
        },
    )


def test_watchlist_matches_same_series_across_provider_slugs(monkeypatch):
    stored = {
        "base_slug": "serienstream:house-of-the-dragon",
        "title": "House of the Dragon",
        "tmdb_id": 94997,
        "aliases": ["La Maison du Dragon"],
        "download_mode": "latest_season",
    }
    monkeypatch.setattr(server.state, "watchlist", [stored])

    assert server.watchlist_match_series(
        "moflix:house-of-the-dragon", "House of the Dragon",
    ) is stored
    assert server.watchlist_match_series(
        "huhu:94997:tmdb", "Unbekannter Provider-Titel", tmdb_id=94997,
    ) is stored


def test_deferred_series_detail_is_already_marked_subscribed(monkeypatch):
    stored = {
        "base_slug": "serienstream:house-of-the-dragon",
        "title": "House of the Dragon",
        "tmdb_id": 94997,
        "aliases": [],
        "download_mode": "latest_season",
        "cleanup_mode": "keep",
    }
    monkeypatch.setattr(server.state, "watchlist", [stored])

    payload = server.series_to_dict(_series(), defer_checks=True)

    assert payload["watchlisted"] is True
    assert payload["watch_mode"] == "latest_season"
    assert payload["tmdb_id"] == 94997


def test_ambiguous_title_without_stable_id_does_not_guess(monkeypatch):
    monkeypatch.setattr(server.state, "watchlist", [
        {"base_slug": "one", "title": "The Office", "tmdb_id": 2316},
        {"base_slug": "two", "title": "The Office", "tmdb_id": 2996},
    ])
    assert server.watchlist_match_series("other", "The Office") is None
    assert server.watchlist_match_series("other", "The Office", tmdb_id=2316)["base_slug"] == "one"


def test_targeted_jellyfin_status_never_loads_complete_episode_index(monkeypatch):
    class FakeClient:
        configured = True

        def series_ids_for(self, *_args, **_kwargs):
            return {"jf-house"}

        def episodes_for_series(self, _title, items=None, **_kwargs):
            return {(item["season"], item["episode"]) for item in (items or [])}

    monkeypatch.setattr(server, "get_jellyfin_client", lambda: FakeClient())
    monkeypatch.setattr(server, "get_jellyfin_series", lambda force=False: [{"id": "jf-house"}])
    monkeypatch.setattr(server.state, "jellyfin_series_available", True)
    monkeypatch.setattr(
        server, "get_jellyfin_targeted_episodes",
        lambda _ids, force=False: ([
            {"series_id": "jf-house", "season": 1, "episode": 1},
        ], True, False, 123.0),
    )
    monkeypatch.setattr(
        server, "get_jellyfin_episodes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full index used")),
    )
    episodes = [
        {"slug": "house-s01e01", "season": 1, "episode": 1},
        {"slug": "house-s01e02", "season": 1, "episode": 2},
    ]

    status = server._series_jellyfin_status("House of the Dragon", episodes=episodes)

    assert status == {
        "configured": True,
        "available": True,
        "stale": False,
        "checked_at": 123.0,
        "episodes": {"house-s01e01": True, "house-s01e02": False},
        "count": 1,
    }


def test_targeted_episode_cache_avoids_repeated_jellyfin_calls(monkeypatch):
    calls = []

    class FakeClient:
        configured = True

        def list_episodes_for_series(self, series_id):
            calls.append(series_id)
            return [{"series_id": series_id, "season": 1, "episode": 1}]

    monkeypatch.setattr(server, "get_jellyfin_client", lambda: FakeClient())
    monkeypatch.setattr(server.state, "jellyfin_targeted_episodes", {})
    first = server.get_jellyfin_targeted_episodes({"jf-house"})
    second = server.get_jellyfin_targeted_episodes({"jf-house"})

    assert first[1:3] == (True, False)
    assert second[1:3] == (True, False)
    assert calls == ["jf-house"]


def test_jellyfin_client_uses_parent_id_for_targeted_episode_query(monkeypatch):
    client = JellyfinClient("http://jellyfin", "key")
    captured = {}

    def fake_list(params, page_size, label):
        captured.update({"params": params, "page_size": page_size, "label": label})
        return [{
            "Id": "episode-1", "SeriesId": "series-1", "SeriesName": "House",
            "ParentIndexNumber": 1, "IndexNumber": 1,
        }]

    monkeypatch.setattr(client, "_list_items", fake_list)
    result = client.list_episodes_for_series("series-1")

    assert captured["params"]["ParentId"] == "series-1"
    assert captured["params"]["Recursive"] == "true"
    assert result[0]["series_id"] == "series-1"


def test_fast_jellyfin_status_route_has_web_and_v1_aliases():
    routes = {
        (method, route.path)
        for route in server.app.routes
        for method in (getattr(route, "methods", None) or [])
    }
    assert ("POST", "/api/series/jellyfin-status") in routes
    assert ("POST", "/api/v1/series/jellyfin-status") in routes
