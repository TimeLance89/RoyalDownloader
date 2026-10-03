"""HDFilme-family mirror and episode regressions."""

from bs4 import BeautifulSoup

import providers.hdfilme_family as family


def soup(html):
    return BeautifulSoup(html, "lxml")


def search_page(href, title="Exact Show"):
    return soup(f'<a class="movie-title" href="{href}" title="{title}">{title}</a>')


def detail_page():
    return soup('<meta property="og:title" content="Exact Show (2024) - Stream"><h1>Exact Show</h1><script>var imdb = "tt123";</script>')


def test_episode_fallback_searches_base_title_and_keeps_exact_episode(monkeypatch):
    monkeypatch.setattr(family, "_PATHS", {})
    provider = family.HDFilmeFamilyScraper()
    calls = []

    def fetch(url):
        calls.append(url)
        if url.startswith(family.MIRRORS[0]):
            raise TimeoutError("first mirror down")
        if "?story=" in url:
            return search_page("/serien/123-exact-show.html")
        assert url == family.MIRRORS[1] + "/serien/123-exact-show.html"
        return detail_page()

    monkeypatch.setattr(provider, "_soup", fetch)
    monkeypatch.setattr(provider, "_player", lambda _page, _kind: {"tv": {"seasons": [
        {"season_number": 1, "episodes": [
            {"episode_number": 4, "sources": [{"url": "https://dood.to/e/wrong"}]},
            {"episode_number": 5, "sources": [{"url": "https://vinovo.to/e/exact"}]},
        ]},
        {"season_number": 2, "episodes": [
            {"episode_number": 5, "sources": [{"url": "https://dood.to/e/wrong-season"}]},
        ]},
    ]}})

    value = "hdfilme_family:123-Exact%20Show-s01e05"
    movie = provider.get_movie(value)
    assert movie.title == "Exact Show S01E05"
    assert [item.url for item in movie.hosters] == ["https://vinovo.to/e/exact"]
    assert [url for url in calls if "?story=" in url] == [
        family.MIRRORS[0] + "/?story=Exact%20Show&do=search&subaction=search",
        family.MIRRORS[1] + "/?story=Exact%20Show&do=search&subaction=search",
    ]
    assert family._PATHS["123"] == family.MIRRORS[1] + "/serien/123-exact-show.html"
    assert provider.get_movie("hdfilme_family:123-Exact%20Show-s01e06") is None


def test_relative_detail_url_uses_search_mirror(monkeypatch):
    monkeypatch.setattr(family, "_PATHS", {})
    provider = family.HDFilmeFamilyScraper()
    provider._preferred = 1
    calls = []

    def fetch(url):
        calls.append(url)
        return search_page("/filme1/123-exact-show.html") if "?story=" in url else detail_page()

    monkeypatch.setattr(provider, "_soup", fetch)
    result = provider.search("Exact Show")
    detail_url = family.MIRRORS[1] + "/filme1/123-exact-show.html"
    assert result[0].url == detail_url
    assert family._PATHS["123"] == detail_url
    assert provider._detail(result[0].slug)[1] == detail_url
    assert calls == [
        family.MIRRORS[1] + "/?story=Exact%20Show&do=search&subaction=search",
        detail_url,
    ]


def test_stale_detail_url_falls_back_and_matches_numeric_id(monkeypatch):
    old_url = family.MIRRORS[0] + "/filme1/123-old.html"
    monkeypatch.setattr(family, "_PATHS", {"123": old_url})
    provider = family.HDFilmeFamilyScraper()
    calls = []

    def fetch(url):
        calls.append(url)
        if url == old_url:
            raise TimeoutError("stale detail")
        if "?story=" in url:
            return soup('''<a class="movie-title" href="/filme1/999-similar.html" title="Exact Show">Exact Show</a>
                <a class="movie-title" href="/filme1/123-exact-show.html" title="Exact Show">Exact Show</a>''')
        assert url == family.MIRRORS[1] + "/filme1/123-exact-show.html"
        return detail_page()

    monkeypatch.setattr(provider, "_soup", fetch)
    detail = provider._detail("hdfilme_family:123-Exact%20Show")
    assert detail[1] == family.MIRRORS[1] + "/filme1/123-exact-show.html"
    assert calls == [
        old_url,
        family.MIRRORS[1] + "/?story=Exact%20Show&do=search&subaction=search",
        family.MIRRORS[1] + "/filme1/123-exact-show.html",
    ]


def test_first_mirror_success_needs_one_search_and_preserves_absolute_url(monkeypatch):
    monkeypatch.setattr(family, "_PATHS", {})
    provider = family.HDFilmeFamilyScraper()
    calls = []
    absolute = family.MIRRORS[0] + "/filme1/123-exact-show.html"
    monkeypatch.setattr(provider, "_soup", lambda url: calls.append(url) or search_page(absolute))
    result = provider.search("Exact Show")
    assert result[0].url == absolute
    assert family._PATHS["123"] == absolute
    assert calls == [family.MIRRORS[0] + "/?story=Exact%20Show&do=search&subaction=search"]
