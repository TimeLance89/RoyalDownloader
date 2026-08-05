import json
import asyncio
import threading
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
