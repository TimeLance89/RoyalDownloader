"""Regression fixtures for the three adapters added after KinoKing/FlixiTV."""

import base64
from types import SimpleNamespace

from bs4 import BeautifulSoup

from media.hoster_contracts import hoster_key, runtime_contract
from media.extractor import extract_vinovo_url
from providers.models import FilmpalastMovie, FilmpalastSeries, HosterInfo, SeriesEpisode
from providers.movie2k import Movie2kScraper
from providers.hdfilme_family import HDFilmeFamilyScraper
from providers.kellerkino import KellerKinoScraper


def soup(value):
    return BeautifulSoup(value, "lxml")


def episode_table(season, episode, url):
    encoded = base64.b64encode(f"tt123-s{season}e{episode}-".encode()).decode().rstrip("=")
    return (f'<table data-episode-id="{encoded}"><div id="tablemoviesindex2">'
            f'<a href="#" onclick="return loadMirror(\'{url}\')">Mirror</a></div></table>')


def test_movie2k_exact_episode_and_all_mirrors(monkeypatch):
    provider = Movie2kScraper()
    path = "/stream/show?type=series"
    page = soup("<h1>Exact Show</h1>" + episode_table(1, 4, "https://firestream.to/e/a")
                + episode_table(1, 5, "https://vinovo.to/e/b"))
    monkeypatch.setattr(provider, "_soup", lambda _path: page)
    series = provider.get_series("movie2k:" + path)
    assert [(x.season, x.episode) for x in series.all_episodes] == [(1, 4), (1, 5)]
    assert provider.get_movie("movie2k:" + path + "-s02e05") is None
    movie = provider.get_movie("movie2k:" + path + "-s01e05")
    assert [(h.name, h.url) for h in movie.hosters] == [("Vinovo", "https://vinovo.to/e/b")]


def test_movie2k_search_deduplicates_series_card(monkeypatch):
    provider = Movie2kScraper()
    page = soup('''<h2><a href="/stream/film">Film</a></h2>
        <h2><a href="/stream/film">Film</a></h2>
        <h2><a href="/stream/show?type=series"><strong>[SERIE]</strong> Show</a></h2>''')
    monkeypatch.setattr(provider, "_soup", lambda _path: page)
    assert [x.title for x in provider.search("a")] == ["Film"]
    assert [x.title for x in provider.search_series("a")] == ["Show"]


def test_hdf_family_exact_episode_and_duplicate_source(monkeypatch):
    provider = HDFilmeFamilyScraper()
    monkeypatch.setattr(provider, "_detail", lambda _value: (soup("<h1>Show</h1>"), "https://hdfilme.ceo/show"))
    payload = {"tv": {"seasons": [{"season_number": 1, "episodes": [
        {"episode_number": 4, "sources": [{"url": "https://doodstream.com/e/a"}]},
        {"episode_number": 5, "sources": [{"url": "https://vinovo.to/e/b"}, {"url": "https://vinovo.to/e/b"}]},
    ]}]}}
    monkeypatch.setattr(provider, "_player", lambda _soup, _kind: payload)
    series = provider.get_series("hdfilme_family:123-Show")
    assert [(x.season, x.episode) for x in series.all_episodes] == [(1, 4), (1, 5)]
    assert provider.get_movie("hdfilme_family:123-Show-s02e05") is None
    movie = provider.get_movie("hdfilme_family:123-Show-s01e05")
    assert [(h.name, h.url) for h in movie.hosters] == [("Vinovo", "https://vinovo.to/e/b")]


def test_hdf_family_uses_one_mirror_unless_it_fails(monkeypatch):
    import providers.hdfilme_family as module
    provider = HDFilmeFamilyScraper()
    urls = []
    html = soup('<a class="movie-title" href="https://streamcloud.download/4852-matrix-stream-deutsch.html" title="Matrix">Matrix</a>')

    def fetch(url):
        urls.append(url)
        if url.startswith(module.MIRRORS[0]):
            raise TimeoutError("mirror down")
        return html

    monkeypatch.setattr(provider, "_soup", fetch)
    result = provider.search("Matrix")
    assert len(result) == 1
    assert len(urls) == 2
    urls.clear()
    provider.search("Matrix")
    assert len(urls) == 1 and urls[0].startswith(module.MIRRORS[1])


def test_hdf_family_empty_search_does_not_query_same_backend_three_times(monkeypatch):
    provider = HDFilmeFamilyScraper()
    calls = []
    monkeypatch.setattr(provider, "_soup", lambda url: calls.append(url) or soup("<title>Site search</title>"))
    assert provider.search("absent") == []
    assert len(calls) == 1


def test_hdf_family_parses_each_mirror_layout():
    layouts = (
        '<a class="movie-title" href="/4852-matrix.html" title="Matrix">Matrix</a>',
        '<div class="item-video"><div class="f_title"><a href="/4852-matrix.html">Matrix</a></div></div>',
        '<div class="movie-preview"><span class="movie-title"><a href="/movie/4852-matrix.html">Matrix</a></span></div>',
    )
    for html in layouts:
        items = HDFilmeFamilyScraper._cards(soup(html), "https://hdfilme.ceo/?story=Matrix")
        assert [(item.title, item.slug) for item in items] == [("Matrix", "hdfilme_family:4852-Matrix")]


def test_hdf_mirror_uses_content_title_instead_of_brand_heading():
    detail = soup('''<meta property="og:title" content="Matrix (1999) - Stream HD Filme">
        <h1>StreamCloud</h1>''')
    assert HDFilmeFamilyScraper._title_year(detail) == ("Matrix", "1999")


def test_kellerkino_movie_metadata_and_hoster_dedupe(monkeypatch):
    provider = KellerKinoScraper()
    page = soup('''<article class="movie-detail"><h1>Matrix</h1></article>
        <div class="info-list"><div><dt>Jahr:</dt><dd>1999</dd></div></div>
        <iframe src="https://vinovo.si/e/abc"></iframe>
        <iframe src="https://vinovo.si/e/abc"></iframe>
        <iframe src="https://streamtape.com/e/def"></iframe>''')
    monkeypatch.setattr(provider, "_soup", lambda _path: page)
    movie = provider.get_movie("kellerkino:/action/matrix/")
    assert movie.year == "1999"
    assert [h.name for h in movie.hosters] == ["Vinovo", "Streamtape"]
    assert not hasattr(provider, "get_series")


def test_vinovo_alias_and_api_resolver(monkeypatch):
    monkeypatch.setattr("media.extractor.ensure_public_http_url", lambda _url: None)
    assert hoster_key("Vinovo", "https://vinovo.si/e/x") == "vinovo"
    assert runtime_contract("Vinovo", "https://vinovo.si/e/x").resolver == "extract_vinovo_url"
    html = b'''<meta name="token" content="secret"><meta name="file_code" content="abc123">
        <video data-base="https://fs-123.vincdn.net"></video>'''

    class Session:
        def get(self, url, **_kwargs):
            return SimpleNamespace(content=html, url="https://vinovo.to/e/abc123", raise_for_status=lambda: None)

        def post(self, url, **kwargs):
            assert url == "https://vinovo.to/api/file/url/abc123"
            assert kwargs["data"] == {"token": "secret"}
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {"status": "ok", "token": "abc123/signed/12345"})

    assert extract_vinovo_url("https://vinovo.si/e/abc123", session=Session()) == (
        "https://fs-123.vincdn.net/stream/abc123/signed/12345", "mp4")


def test_new_hoster_aliases():
    assert hoster_key("Mxdrop", "https://mxdrop.to/e/id") == "mixdrop"
    assert hoster_key("Dr0pstream", "https://dr0pstream.com/e/id") == "dropload"
    assert hoster_key("Lulust", "https://lulust.com/e/id") == "luluvid"
    assert hoster_key("VOE", "https://goofy-banana.com/e/id") == "voe"
    assert HDFilmeFamilyScraper._hosters([
        {"name": "voe.sx", "url": "https://goofy-banana.com/e/id", "rank": 1},
    ])[0].name == "VOE"


def test_movie2k_cross_provider_fallback_keeps_exact_episode(monkeypatch):
    import server

    slug = "movie2k:/stream/show?type=series-s01e05"
    series = FilmpalastSeries("Exact Show", "movie2k:/stream/show?type=series",
        "https://movie2k.cx/stream/show?type=series",
        seasons={1: [SeriesEpisode(1, 5, slug, "https://movie2k.cx/stream/show") ]})
    movie = FilmpalastMovie("Exact Show S01E05", "https://movie2k.cx/stream/show",
        provider="movie2k", content_language="de",
        hosters=[HosterInfo("Vinovo", "https://vinovo.to/e/abc")])
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream", "movie2k"])
    monkeypatch.setattr(server, "_fallback_get_series", lambda provider, *_args, **_kwargs:
        series if provider == "movie2k" else None)
    monkeypatch.setattr(server, "load_movie_for_slug", lambda value: movie if value == slug else None)
    assert server.find_episode_fallbacks("Exact Show", 1, 4,
        source_slug="serienstream:show-s01e04") == []
    assert server.find_episode_fallbacks("Exact Show", 1, 5,
        source_slug="serienstream:show-s01e05") == [movie]
