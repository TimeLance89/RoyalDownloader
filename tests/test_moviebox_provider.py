import base64
import json
from urllib.parse import urlsplit

import pytest

from providers.moviebox import MovieBoxScraper, _policy_manifest


class TMDB:
    def movie_by_id(self, value):
        return {"title": "Inception", "original_title": "Inception", "year": "2010"}

    def series_by_id(self, value):
        return {"title": "Game of Thrones", "original_title": "Game of Thrones", "year": "2011",
                "season_episode_counts": {"1": 10, "2": 10}}


def cookie(path):
    payload = {"Statement": [{"Resource": "https://example.com/dash/" + path + "/*"}]}
    return "CloudFront-Policy=" + base64.b64encode(json.dumps(payload).encode()).decode() + "; CloudFront-Signature=test"


class StubMovieBox(MovieBoxScraper):
    def __init__(self, title, year, media_type):
        super().__init__(tmdb=TMDB())
        self.title, self.year, self.media_type = title, year, media_type
        self.calls = []

    def _call(self, method, path, body=None, extra=None, token_request=False):
        self.calls.append((method, path, body))
        if path.endswith("/search/v2"):
            return {"results": [{"subjects": [
                {"subjectId": "wrong", "title": "Inception", "subjectType": 1, "releaseDate": "1999"},
                {"subjectId": "42", "title": self.title, "subjectType": self.media_type, "releaseDate": self.year + "-01-01"},
            ]}]}
        if "/get?" in path:
            return {"language": "English", "dubs": [{"subjectId": "42", "lanName": "English"}]}
        if "/play-info?" in path:
            return {"streams": [
                {"format": "MP4", "url": "https://example.com/placeholder.mp4", "signCookie": cookie("english"), "resolutions": "1080,720"},
                {"format": "HLS", "url": "https://example.com/other.m3u8", "resolutions": "720"},
            ]}
        return None


@pytest.mark.parametrize("slug,title,year,kind,expected", [
    ("moviebox:27205", "Inception", "2010", 1, "se=0&ep=0"),
    ("moviebox:1399-s2e3", "Game of Thrones S1", "2011", 2, "se=2&ep=3"),
])
def test_moviebox_movie_and_exact_episode(slug, title, year, kind, expected):
    scraper = StubMovieBox(title, year, kind)
    movie = scraper.get_movie(slug)
    dash = next(hoster for hoster in movie.hosters if hoster.stream_type == "dash")
    assert dash.url == "https://example.com/dash/english/index.mpd"
    assert dash.language == "en"
    assert "CloudFront-Policy" in dash.headers["Cookie"]
    assert {hoster.quality for hoster in movie.hosters} == {"1080,720", "720"}
    assert any(expected in path for _method, path, _body in scraper.calls)


def test_moviebox_rejects_wrong_year_and_missing_episode():
    scraper = StubMovieBox("Inception", "1999", 1)
    assert scraper.get_movie("moviebox:27205") is None
    assert scraper.get_movie("moviebox:1399-s0e1") is None
    assert scraper.get_movie("moviebox:1399-s1") is None


def test_moviebox_policy_and_signing_headers():
    assert _policy_manifest(cookie("film")) == "https://example.com/dash/film/index.mpd"
    scraper = StubMovieBox("Inception", "2010", 1)
    headers = scraper._headers("GET", "https://api6.aoneroom.com/path?a=1", "")
    assert headers["x-tr-signature"].count("|") == 2
    assert headers["x-client-token"].count(",") == 1
    assert scraper.get_series("moviebox:1399").seasons[2][2].slug == "moviebox:1399-s2e3"


def test_moviebox_api_host_failover_on_rate_limit():
    class Response:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {"code": 0, "data": {"found": True}}

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((url, kwargs["headers"]))
            return Response(429 if urlsplit(url).hostname == "api6.aoneroom.com" else 200)

    session = Session()
    scraper = MovieBoxScraper(tmdb=TMDB(), session=session)
    scraper._anonymous_token = lambda: "temporary"
    result = scraper._call("GET", "/example")
    assert result == {"found": True}
    assert urlsplit(session.calls[0][0]).hostname == "api6.aoneroom.com"
    assert urlsplit(session.calls[1][0]).hostname == "api5.aoneroom.com"
    assert session.calls[1][1]["Authorization"] == "Bearer temporary"
