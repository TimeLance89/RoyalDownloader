import json
import asyncio
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jellyfin_client
import api_discovery_router
from jellyfin_client import JellyfinClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_movie_identity_index_omits_heavy_media_fields(monkeypatch):
    queries = []

    def fake_urlopen(request, timeout):
        queries.append(parse_qs(urlparse(request.full_url).query))
        return _Response({
            "Items": [{
                "Id": "movie-1", "Name": "Dune", "ProductionYear": 2021,
                "ProviderIds": {"Tmdb": "438631"},
            }],
            "TotalRecordCount": 1,
        })

    monkeypatch.setattr(jellyfin_client.urllib.request, "urlopen", fake_urlopen)

    items = JellyfinClient("http://jellyfin", "key").list_movie_identities()

    assert items == [{
        "id": "movie-1", "name": "Dune", "original_title": "",
        "sort_name": "", "year": 2021, "tmdb_id": "438631",
    }]
    fields = queries[0]["Fields"][0].split(",")
    assert "ProviderIds" in fields
    assert "MediaSources" not in fields
    assert "Path" not in fields


def test_movie_identity_index_matches_by_tmdb_id(monkeypatch):
    monkeypatch.setattr(
        JellyfinClient,
        "_list_items",
        lambda *_args, **_kwargs: [{
            "Id": "movie-1", "Name": "Falscher lokaler Titel",
            "ProductionYear": 2021, "ProviderIds": {"Tmdb": "438631"},
        }],
    )
    client = JellyfinClient("http://jellyfin", "key")

    identities = client.list_movie_identities()

    assert client.match("Dune", "2021", items=identities, tmdb_id="438631")


def test_catalog_jellyfin_status_matches_movies_series_and_anime(monkeypatch):
    class FakeClient:
        configured = True

        def match(self, title, *_args, **_kwargs):
            return title == "Dune"

        def series_ids_for(self, title, **_kwargs):
            return {"series-1"} if title in {"Lucky", "Frieren"} else set()

    monkeypatch.setattr(api_discovery_router, "get_jellyfin_client", lambda: FakeClient())
    monkeypatch.setattr(api_discovery_router, "clean_movie_title", lambda title: title)
    monkeypatch.setattr(api_discovery_router, "get_jellyfin_movie_identities", lambda: [{}])
    monkeypatch.setattr(api_discovery_router, "get_jellyfin_series", lambda: [{}])
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(
        jellyfin_cache_lock=threading.RLock(),
        jellyfin_movie_identities_available=True,
        jellyfin_series_available=True,
    ))
    body = api_discovery_router.MovieMetadataBody(items=[
        {"slug": "movie:dune", "title": "Dune", "media_type": "movie"},
        {"slug": "series:lucky", "title": "Lucky", "media_type": "series"},
        {"slug": "anime:frieren", "title": "Frieren", "media_type": "series"},
        {"slug": "series:missing", "title": "Missing", "media_type": "series"},
    ])

    result = asyncio.run(api_discovery_router.api_jellyfin_matches(body))

    assert result["available"] is True
    assert result["statuses"] == {
        "movie:dune": "owned",
        "series:lucky": "owned",
        "anime:frieren": "owned",
        "series:missing": "missing",
    }


def test_yearless_catalog_movies_use_provider_detail_to_separate_same_titles(monkeypatch):
    class FakeTmdb:
        configured = True

        @staticmethod
        def now_playing_ids():
            return set()

        @staticmethod
        def search_movies(_title, max_results=20):
            assert max_results == 20
            return [
                {"tmdb_id": 354287, "title": "War Machine", "original_title": "War Machine", "year": "2017"},
                {"tmdb_id": 1265609, "title": "War Machine", "original_title": "War Machine", "year": "2026"},
            ]

        @staticmethod
        def movie_summary(*_args):
            raise AssertionError("Mehrdeutige jahrlose Titel dürfen nicht geraten werden")

    movies = {
        "war-machine": SimpleNamespace(title="War Machine", year="2017"),
        "war-machine-2026": SimpleNamespace(title="War Machine *2026*", year=""),
    }
    monkeypatch.setattr(api_discovery_router, "get_tmdb_client", lambda: FakeTmdb())
    monkeypatch.setattr(api_discovery_router, "load_movie_for_slug", lambda slug: movies[slug])
    monkeypatch.setattr(api_discovery_router, "clean_movie_title", lambda title: title)
    monkeypatch.setattr(api_discovery_router, "_norm_title", lambda title: "".join(str(title).casefold().split()))
    monkeypatch.setattr(
        api_discovery_router,
        "_resolved_movie_year",
        lambda title, year="": str(year or "") or ("2026" if "2026" in str(title) else ""),
    )
    monkeypatch.setattr(api_discovery_router, "TMDB_MOVIE_BATCH_MAX_WORKERS", 2)
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(fp_movies={}))
    body = api_discovery_router.MovieMetadataBody(items=[
        {"slug": "war-machine", "title": "War Machine", "year": ""},
        {"slug": "war-machine-2026", "title": "War Machine", "year": ""},
    ])

    result = asyncio.run(api_discovery_router.api_tmdb_movies(body))["movies"]

    assert result["war-machine"]["tmdb_id"] == 354287
    assert result["war-machine-2026"]["tmdb_id"] == 1265609
    assert result["war-machine"]["catalog_identity_version"] == 2


def test_tmdb_batch_prefers_known_id_for_reliable_posters(monkeypatch):
    calls = []

    class FakeTmdb:
        configured = True

        @staticmethod
        def now_playing_ids():
            return set()

        @staticmethod
        def movie_summary_by_id(tmdb_id, title):
            calls.append((tmdb_id, title))
            return {
                "tmdb_id": tmdb_id,
                "title": title,
                "cover_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
                "backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            }

        @staticmethod
        def movie_summary(*_args):
            raise AssertionError("Eine bekannte TMDB-ID darf nicht über den Titel geraten werden")

    monkeypatch.setattr(api_discovery_router, "get_tmdb_client", lambda: FakeTmdb())
    monkeypatch.setattr(api_discovery_router, "clean_movie_title", lambda title: title)
    monkeypatch.setattr(api_discovery_router, "TMDB_MOVIE_BATCH_MAX_WORKERS", 2)
    body = api_discovery_router.MovieMetadataBody(items=[{
        "slug": "known-movie",
        "title": "Known Movie",
        "year": "2026",
        "tmdb_id": 12345,
    }])

    result = asyncio.run(api_discovery_router.api_tmdb_movies(body))["movies"]

    assert calls == [(12345, "Known Movie")]
    assert result["known-movie"]["cover_url"].endswith("/poster.jpg")


def test_tmdb_batch_returns_fast_posters_without_waiting_for_slow_ambiguity(monkeypatch):
    release = threading.Event()

    class FakeTmdb:
        configured = True

        @staticmethod
        def cached_now_playing_ids():
            return set()

        @staticmethod
        def now_playing_ids():
            raise AssertionError("Kinostatus darf Poster nicht blockieren")

        @staticmethod
        def movie_summary(title, _year):
            return {
                "tmdb_id": 1,
                "title": title,
                "cover_url": "https://image.tmdb.org/t/p/w500/fast.jpg",
            }

        @staticmethod
        def search_movies(_title, max_results=20):
            assert max_results == 20
            return [
                {"tmdb_id": 2, "title": "Slow", "original_title": "Slow", "year": "2025"},
                {"tmdb_id": 3, "title": "Slow", "original_title": "Slow", "year": "2026"},
            ]

    def slow_provider_detail(_slug):
        assert release.wait(timeout=1)
        return SimpleNamespace(title="Slow", year="2026")

    monkeypatch.setattr(api_discovery_router, "get_tmdb_client", lambda: FakeTmdb())
    monkeypatch.setattr(api_discovery_router, "load_movie_for_slug", slow_provider_detail)
    monkeypatch.setattr(api_discovery_router, "clean_movie_title", lambda title: title)
    monkeypatch.setattr(api_discovery_router, "_norm_title", lambda title: str(title).casefold())
    monkeypatch.setattr(api_discovery_router, "TMDB_METADATA_BATCH_BUDGET_SECONDS", 0.05)
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(fp_movies={}))
    body = api_discovery_router.MovieMetadataBody(items=[
        {"slug": "slow", "title": "Slow", "year": ""},
        {"slug": "fast", "title": "Fast", "year": "2026"},
    ])

    started = time.monotonic()
    try:
        result = asyncio.run(api_discovery_router.api_tmdb_movies(body))["movies"]
        elapsed = time.monotonic() - started
    finally:
        release.set()
        deadline = time.monotonic() + 1
        while api_discovery_router._TMDB_METADATA_INFLIGHT and time.monotonic() < deadline:
            time.sleep(0.01)

    assert elapsed < 0.3
    assert result["fast"]["cover_url"].endswith("/fast.jpg")
    assert "slow" not in result
