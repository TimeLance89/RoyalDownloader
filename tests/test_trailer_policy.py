from __future__ import annotations

import server
from application_services import trailer_policy


class FakeTMDBClient:
    configured = True
    language = "de-DE"

    def __init__(self, videos):
        self.videos = list(videos)
        self.requests = []
        self.movie_payload = {
            "tmdb_id": 10,
            "title": "Film",
            "trailer": {"site": "YouTube", "key": "wrong-language"},
        }
        self.series_payload = {
            "tmdb_id": 20,
            "title": "Serie",
            "trailer": {"site": "YouTube", "key": "wrong-language"},
        }

    def _request(self, path, params=None):
        self.requests.append((path, dict(params or {})))
        return {"results": list(self.videos)}

    def movie_by_id(self, *_args, **_kwargs):
        return self.movie_payload

    def movie(self, *_args, **_kwargs):
        return self.movie_payload

    def series_by_id(self, *_args, **_kwargs):
        return self.series_payload

    def series(self, *_args, **_kwargs):
        return self.series_payload


def _video(key, language, *, official=True, kind="Trailer", size=1080):
    return {
        "site": "YouTube",
        "key": key,
        "name": key,
        "iso_639_1": language,
        "official": official,
        "type": kind,
        "size": size,
        "published_at": "2026-01-01T00:00:00Z",
    }


def test_mixed_german_english_prefers_english():
    assert trailer_policy._preferred_trailer_language({"de", "en"}) == "en"
    assert trailer_policy._preferred_trailer_language({"de"}) == "de"
    assert trailer_policy._preferred_trailer_language({"en"}) == "en"


def test_strict_selector_never_falls_back_to_other_language():
    videos = [
        _video("english", "en"),
        _video("german", "de", official=False),
    ]
    assert trailer_policy._strict_youtube_trailer(videos, "de")["key"] == "german"
    assert trailer_policy._strict_youtube_trailer(videos, "en")["key"] == "english"
    assert trailer_policy._strict_youtube_trailer([videos[0]], "de") is None


def test_german_only_removes_english_movie_trailer(monkeypatch):
    client = FakeTMDBClient([_video("english", "en")])
    proxy = trailer_policy._TrailerAwareTMDBClient(client)
    monkeypatch.setattr(server.state, "content_languages", {"de"})

    result = proxy.movie_by_id(10)

    assert result["trailer"] is None
    assert client.movie_payload["trailer"]["key"] == "wrong-language"
    assert client.requests == [
        ("/movie/10/videos", {"language": "de-DE"}),
    ]


def test_mixed_languages_select_english_for_movies_and_series(monkeypatch):
    client = FakeTMDBClient([
        _video("de-trailer", "de"),
        _video("en-trailer", "en"),
    ])
    proxy = trailer_policy._TrailerAwareTMDBClient(client)
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})

    movie = proxy.movie_by_id(10)
    series = proxy.series_by_id(20)

    assert movie["trailer"]["key"] == "en-trailer"
    assert movie["trailer"]["language"] == "en"
    assert series["trailer"]["key"] == "en-trailer"
    assert series["trailer"]["language"] == "en"
    assert client.requests == [
        ("/movie/10/videos", {"language": "en-US"}),
        ("/tv/20/videos", {"language": "en-US"}),
    ]


def test_trailer_lookup_is_cached_per_media_language(monkeypatch):
    client = FakeTMDBClient([_video("de-trailer", "de")])
    proxy = trailer_policy._TrailerAwareTMDBClient(client)
    monkeypatch.setattr(server.state, "content_languages", {"de"})

    assert proxy.movie_by_id(10)["trailer"]["key"] == "de-trailer"
    assert proxy.movie_by_id(10)["trailer"]["key"] == "de-trailer"

    assert client.requests == [
        ("/movie/10/videos", {"language": "de-DE"}),
    ]
