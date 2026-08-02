import json
from urllib.parse import parse_qs, urlparse

import jellyfin_client
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
