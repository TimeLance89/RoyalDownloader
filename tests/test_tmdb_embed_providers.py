import json
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import pytest
import wasmtime
from curl_cffi import requests

from providers import tmdb_embeds
from providers.tmdb_embeds import VidSrcScraper, VidRiftScraper, VixSrcScraper, VidRockScraper, _hls_tracks


class Response:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestsError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


class TMDB:
    def search_movies(self, query, max_results=12):
        return [{"title": "Inception", "year": "2010", "tmdb_id": 27205}]

    def movie_by_id(self, tmdb_id):
        return {"title": "Inception", "year": "2010"} if str(tmdb_id) == "27205" else None

    def series_summary(self, query):
        return {"title": "Game of Thrones", "year": "2011", "tmdb_id": 1399}

    def series_by_id(self, tmdb_id):
        return {"title": "Game of Thrones", "season_episode_counts": {"1": 10, "2": 10}} if str(tmdb_id) == "1399" else None


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        result = self.routes.get(url, Response("", 404))
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("slug,path", [
    ("vidrift:27205", "/embed/movie/27205"),
    ("vidrift:1399-s2e3", "/embed/tv/1399/2/3"),
])
def test_vidrift_movie_and_exact_episode(slug, path):
    page = "https://embed.vidrift.net" + path
    media = "https://cdn.vidrift.net/test/master.m3u8"
    meta = {"orionStreams": [{"url": media, "type": "hls", "name": "Orion · English", "rungs": [{"height": 1080}]}]}
    session = Session({page: Response("<script>var embedMeta = " + json.dumps(meta) + ";</script>")})
    scraper = VidRiftScraper(tmdb=TMDB(), session=session)
    movie = scraper.get_movie(slug)
    assert movie.hosters[0].url == media
    assert movie.hosters[0].referer == page
    assert movie.hosters[0].quality == "1080p"
    assert movie.hosters[0].language == "en"
    assert movie.title.endswith("S02E03") == ("s2e3" in slug)


@pytest.mark.parametrize("slug,path", [
    ("vixsrc:27205", "/api/movie/27205"),
    ("vixsrc:1399-s2e3", "/api/tv/1399/2/3"),
])
def test_vixsrc_movie_and_exact_episode_with_english_audio(slug, path):
    api = "https://vixsrc.to" + path
    embed = "https://vixsrc.to/embed/42?canPlayFHD=1"
    html = '''<script>window.streams = [{"name":"Server1","url":"https:\\/\\/vixsrc.to\\/playlist\\/42?ub=1"}];
    window.masterPlaylist = {params: {'token': 'signed', 'expires': '99999'}};</script>'''
    playlist = "https://vixsrc.to/playlist/42?ub=1&token=signed&expires=99999&h=1"
    manifest = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,LANGUAGE="ita",NAME="Italian"\n#EXT-X-MEDIA:TYPE=AUDIO,LANGUAGE="eng",NAME="English"\n'
    session = Session({api: Response(json.dumps({"src": embed})), embed: Response(html), playlist: Response(manifest)})
    movie = VixSrcScraper(tmdb=TMDB(), session=session).get_movie(slug)
    assert movie.hosters[0].url == playlist
    assert movie.hosters[0].language == movie.hosters[0].audio_language == "en"
    assert movie.hosters[0].referer == embed
    assert movie.title.endswith("S02E03") == ("s2e3" in slug)


def test_vidrift_mirror_and_missing_episode():
    first = "https://embed.vidrift.net/embed/tv/1399/1/1"
    mirror = "https://embed.vidrift.in/embed/tv/1399/1/1"
    session = Session({first: Response("", 503), mirror: Response('<script>var embedMeta = {"evionUrl":"https://example.com/test.m3u8"};</script>'), "https://example.com/test.m3u8": Response("#EXTM3U")})
    scraper = VidRiftScraper(tmdb=TMDB(), session=session)
    movie = scraper.get_movie("vidrift:1399-s1e1")
    assert movie.hosters[0].referer == mirror
    assert scraper.get_movie("vidrift:1399-s1e0") is None
    assert scraper.get_movie("vidrift:1399-s1") is None


def test_timeout_unavailable_and_non_english_tracks():
    page = "https://vixsrc.to/api/movie/27205"
    session = Session({page: requests.RequestsError("timeout")})
    assert VixSrcScraper(tmdb=TMDB(), session=session).get_movie("vixsrc:27205") is None
    assert _hls_tracks('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,LANGUAGE="ita"') == {"it"}


def test_series_structure_and_search_ids():
    scraper = VidRiftScraper(tmdb=TMDB(), session=Session({}))
    assert scraper.search("Inception")[0].slug == "vidrift:27205"
    assert scraper.search_series("Game of Thrones")[0].base_slug == "vidrift:1399"
    series = scraper.get_series("vidrift:1399")
    assert series.seasons[2][2].slug == "vidrift:1399-s2e3"


@pytest.mark.parametrize("slug,query", [
    ("vidsrc:27205", "type=movie&tmdb=27205&stream_urls"),
    ("vidsrc:1399-s2e3", "type=tv&tmdb=1399&season=2&episode=3&stream_urls"),
])
def test_vidsrc_movie_and_exact_episode_with_host_token(slug, query):
    api = "https://data.vidsrc.sh/api.php?" + query
    raw = "https://example.com/master.m3u8"
    media = raw + "?token=signed"
    session = Session({
        api: Response(json.dumps({"status_code": "200", "data": {"stream_urls": [raw]}})),
        "https://example.com/generate.php": Response("signed"),
        media: Response("#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,LANGUAGE=\"eng\"\n"),
    })
    movie = VidSrcScraper(tmdb=TMDB(), session=session).get_movie(slug)
    assert movie.hosters[0].url == media
    assert movie.hosters[0].stream_type == "hls"
    assert movie.hosters[0].audio_language == "en"
    assert movie.title.endswith("S02E03") == ("s2e3" in slug)


def test_vidsrc_api_mirror_after_timeout():
    query = "type=movie&tmdb=27205&stream_urls"
    session = Session({
        "https://data.vidsrc.sh/api.php?" + query: requests.RequestsError("timeout"),
        "https://data.vidsrcme.ru/api.php?" + query: Response(json.dumps({"status_code": "200", "data": {"stream_urls": ["https://example.com/master.m3u8"]}})),
        "https://example.com/generate.php": Response("signed"),
        "https://example.com/master.m3u8?token=signed": Response("#EXTM3U"),
    })
    movie = VidSrcScraper(tmdb=TMDB(), session=session).get_movie("vidsrc:27205")
    assert movie and movie.hosters
    assert movie.url.startswith("https://data.vidsrcme.ru/")


def test_vidsrc_tv_retries_transient_empty_response(monkeypatch):
    api = "https://data.vidsrc.sh/api.php?type=tv&tmdb=1399&season=2&episode=3&stream_urls"
    raw = "https://example.com/master.m3u8"
    media = raw + "?token=signed"

    class SequenceSession:
        def __init__(self):
            self.calls = []
            self.api_calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls.append((url, headers, timeout))
            if url == api:
                self.api_calls += 1
                if self.api_calls == 1:
                    return Response(json.dumps({"status_code": "200", "data": {"stream_urls": []}}))
                return Response(json.dumps({"status_code": "200", "data": {"stream_urls": [raw]}}))
            if url == "https://example.com/generate.php":
                return Response("signed")
            if url == media:
                return Response("#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,LANGUAGE=\"eng\"\n")
            return Response("", 404)

    sleeps = []
    monkeypatch.setattr(tmdb_embeds.time, "sleep", lambda seconds: sleeps.append(seconds))
    session = SequenceSession()
    movie = VidSrcScraper(tmdb=TMDB(), session=session).get_movie("vidsrc:1399-s2e3")

    assert movie and movie.hosters
    assert session.api_calls == 2
    assert sleeps == [tmdb_embeds._VIDSRC_TV_RETRY_DELAY]
    assert movie.hosters[0].url == media


def test_vidsrc_wasm_fuel_stops_infinite_decrypt(monkeypatch):
    monkeypatch.setattr(tmdb_embeds, "_VIDSRC_WASM_FUEL", 10_000)
    wasm = wasmtime.wat2wasm("""
        (module
          (memory (export "memory") 1)
          (func (export "alloc") (param i32) (result i32)
            i32.const 0)
          (func (export "decrypt") (param i32 i32) (result i32)
            (loop $spin
              br $spin)
            i32.const 0))
    """)
    encoded = base64.b64encode(b"payload").decode()
    assert tmdb_embeds._decode_vidsrc_wasm(bytes(wasm), encoded) == []


def test_vidsrc_wasm_memory_limit_rejects_large_linear_memory():
    wasm = wasmtime.wat2wasm("""
        (module
          (memory (export "memory") 300)
          (func (export "alloc") (param i32) (result i32)
            i32.const 0)
          (func (export "decrypt") (param i32 i32) (result i32)
            i32.const 0))
    """)
    encoded = base64.b64encode(b"payload").decode()
    assert tmdb_embeds._decode_vidsrc_wasm(bytes(wasm), encoded) == []


@pytest.mark.parametrize("slug,path", [
    ("vidrock:27205", "/api/movie/27205"),
    ("vidrock:1399-s2e3", "/api/tv/1399/2/3"),
])
def test_vidrock_movie_and_episode_dynamic_server(slug, path):
    key = bytes(range(32))
    media = "https://example.com/master.m3u8"
    packed = b"0" * 12 + AESGCM(key).encrypt(b"0" * 12, media.encode(), None)
    encrypted = base64.urlsafe_b64encode(packed).decode().rstrip("=")
    session = Session({
        "https://vidrock.net/movie/27205": Response('<script type="module" crossorigin src="/assets/test.js"></script>'),
        "https://vidrock.net/assets/test.js": Response(f'const key="{key.hex()}";'),
        "https://vidrock.net" + path: Response(json.dumps({"AnyServer": {"url": encrypted, "type": "hls", "language": "English"}})),
        media: Response("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\nchunk.m3u8"),
    })
    movie = VidRockScraper(tmdb=TMDB(), session=session).get_movie(slug)
    assert movie.hosters[0].url == media
    assert movie.hosters[0].name == "AnyServer"
    assert movie.hosters[0].origin == "https://vidrock.net"
    assert movie.hosters[0].language == "en"
