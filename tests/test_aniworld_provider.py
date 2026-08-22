from pathlib import Path

import config
from providers.aniworld import (
    AniWorldAnime,
    AniWorldEpisode,
    AniWorldScraper,
    aniworld_episode_page,
)
from providers.catalog import provider_for_source, provider_keys


class _Response:
    def __init__(self, body=b"", status_code=200, headers=None, json_body=None):
        self.content = body
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._json_body


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}

    def get(self, url, **_kwargs):
        return self.pages[url]

    def post(self, _url, **_kwargs):
        return _Response(json_body=[])


def _detail_html():
    return b"""
    <h1 itemprop="name"><span>Test Anime</span></h1>
    <span itemprop="startDate">2024</span>
    <div itemprop="description">Eine ausreichend lange Testbeschreibung.</div>
    <div class="seriesCoverBox"><img data-src="/cover.jpg"></div>
    <a href="/anime/stream/test-anime/staffel-1">1</a>
    <table class="seasonEpisodesList"><tbody><tr>
      <td><a href="/anime/stream/test-anime/staffel-1/episode-2">Folge 2</a></td>
      <td class="seasonEpisodeTitle">Der Anfang</td>
      <td class="editFunctions">
        <img class="flag" src="/public/img/german.svg">
        <img class="flag" src="/public/img/japanese-german.svg">
      </td>
    </tr></tbody></table>
    """


def test_aniworld_is_registered_as_german_anime_provider():
    assert "aniworld" in provider_keys("anime")
    assert provider_for_source("aniworld:test-anime|dub-s01e002") == "aniworld"
    assert (
        provider_for_source("https://aniworld.to/anime/stream/test-anime") == "aniworld"
    )


def test_existing_installation_enables_aniworld_once(monkeypatch):
    writes = []
    monkeypatch.setattr(
        config, "_update_all", lambda values: writes.append(values) or True
    )
    old = {
        "provider_catalog_revision": "4",
        "anime_provider_priority": "mkissa",
        "anime_provider_enabled": "mkissa",
        "content_languages": "de",
    }

    migrated = config._migrate_provider_catalog(old)

    assert migrated["anime_provider_priority"] == "aniworld,mkissa"
    assert migrated["anime_provider_enabled"] == "mkissa,aniworld"
    assert writes == [
        {
            "provider_catalog_revision": "5",
            "anime_provider_priority": "aniworld,mkissa",
            "anime_provider_enabled": "mkissa,aniworld",
        }
    ]

    migrated["anime_provider_enabled"] = "mkissa"
    assert (
        config._migrate_provider_catalog(migrated)["anime_provider_enabled"] == "mkissa"
    )
    assert len(writes) == 1


def test_german_aniworld_settings_remain_visible_without_english():
    core = (Path(__file__).parents[1] / "web" / "core.js").read_text(encoding="utf-8")

    assert 'querySelectorAll(".anime-tab-button")' in core
    assert 'querySelectorAll(".provider-source-lane.is-anime")' in core
    assert 'state.providers.contentLanguages.has(providerLanguage(provider))' in core


def test_detail_and_episode_hosters_preserve_track_and_season():
    base = "https://aniworld.to/anime/stream/test-anime"
    episode_url = f"{base}/staffel-1/episode-2"
    episode_html = b"""
    <li data-lang-key="1" data-link-target="/redirect/123"><h4>VOE</h4></li>
    <li data-lang-key="3" data-link-target="/redirect/456"><h4>Filemoon</h4></li>
    """
    scraper = AniWorldScraper(
        session=_Session(
            {
                base: _Response(_detail_html()),
                episode_url: _Response(episode_html),
            }
        )
    )
    anime = scraper.get_anime("test-anime")
    assert anime.title == "Test Anime"
    assert anime.translations == {"dub": 1, "sub": 1}
    page = aniworld_episode_page(anime, "dub")
    assert page["episodes"][0]["slug"] == "aniworld:test-anime|dub-s01e002"

    movie = scraper.get_episode(page["episodes"][0]["slug"])
    assert movie.title == "Test Anime S01E02"
    assert movie.provider == "aniworld"
    assert [hoster.name for hoster in movie.hosters] == ["VOE"]
    assert movie.hosters[0].language == "Deutsch Dub"


def test_episode_page_filters_the_selected_language_track():
    anime = AniWorldAnime(
        id="test-anime",
        title="Test",
        episodes=[
            AniWorldEpisode(1, 1, tracks=("dub",)),
            AniWorldEpisode(1, 2, tracks=("sub",)),
            AniWorldEpisode(2, 1, tracks=("dub", "sub")),
        ],
        translations={"dub": 2, "sub": 2},
    )
    page = aniworld_episode_page(anime, "dub")
    assert [(item["season"], item["number"]) for item in page["episodes"]] == [
        (1, 1),
        (2, 1),
    ]


def test_catalog_deduplicates_titles_and_exposes_letter_and_genre_facets():
    catalog_html = b"""
    <div id="seriesContainer">
      <div class="genre"><div class="seriesGenreList"><h3>Action</h3></div><ul>
        <li><a href="/anime/stream/black-torch" data-alternative-title="Black Torch, Burakku Tochi">BLACK TORCH</a></li>
        <li><a href="/anime/stream/86-eighty-six">86: Eighty Six</a></li>
      </ul></div>
      <div class="genre"><div class="seriesGenreList"><h3>Drama</h3></div><ul>
        <li><a href="/anime/stream/black-torch">BLACK TORCH</a></li>
      </ul></div>
    </div>
    """
    scraper = AniWorldScraper(
        session=_Session({"https://aniworld.to/animes": _Response(catalog_html)})
    )

    payload = scraper.browse(mode="catalog", letter="B", page=1, limit=24)

    assert payload["total"] == 1
    assert payload["results"][0]["genres"] == ["Action", "Drama"]
    assert payload["results"][0]["alternative_titles"] == [
        "Black Torch",
        "Burakku Tochi",
    ]
    assert payload["facets"]["letters"] == {"#": 1, "B": 1}
    assert payload["facets"]["genres"] == {"Action": 2, "Drama": 1}


def test_detail_exposes_complete_title_metadata():
    rich_html = b"""
    <section class="SeriesSection"><div class="backdrop" style="background-image:url('/banner.jpg')"></div></section>
    <h1 itemprop="name" data-alternativetitles="Alternativ Eins, Alternativ Zwei"><span>Test Anime</span></h1>
    <span itemprop="startDate">2024</span><span itemprop="endDate">Heute</span>
    <div class="fsk" data-fsk="16"></div><a class="imdb-link" data-imdb="tt123"></a>
    <p data-full-description="Die vollstaendige Beschreibung."></p>
    <div class="seriesCoverBox"><img data-src="/cover.jpg"></div>
    <li itemprop="director"><span itemprop="name">Regie Name</span></li>
    <li itemprop="actor"><span itemprop="name">Stimme Name</span></li>
    <li itemprop="creator"><span itemprop="name">Studio Name</span></li>
    <li itemprop="countryOfOrigin"><span itemprop="name">Japan</span></li>
    <a href="/genre/action" itemprop="genre">Action</a>
    <span itemprop="ratingValue" content="4.5"></span>
    <span itemprop="ratingCount" content="1.234"></span>
    <a href="/anime/stream/test-anime/staffel-1">1</a>
    <table class="seasonEpisodesList"><tbody><tr>
      <td><a href="/anime/stream/test-anime/staffel-1/episode-1">Folge 1</a></td>
      <td class="seasonEpisodeTitle"><strong>Deutscher Titel</strong><span>Original Title</span></td>
      <td><i class="icon VOE" title="VOE"></i></td>
      <td><img class="flag" src="/public/img/german.svg"></td>
    </tr></tbody></table>
    """
    scraper = AniWorldScraper(
        session=_Session(
            {"https://aniworld.to/anime/stream/test-anime": _Response(rich_html)}
        )
    )

    anime = scraper.get_anime("test-anime")

    assert anime.banner_url == "https://aniworld.to/banner.jpg"
    assert anime.description == "Die vollstaendige Beschreibung."
    assert anime.alternative_titles == ["Alternativ Eins", "Alternativ Zwei"]
    assert anime.status == "Laufend"
    assert anime.fsk == "16"
    assert anime.imdb_id == "tt123"
    assert anime.rating == 4.5
    assert anime.rating_count == 1234
    assert anime.country == "Japan"
    assert anime.directors == ["Regie Name"]
    assert anime.cast == ["Stimme Name"]
    assert anime.producers == ["Studio Name"]
    assert anime.episodes[0].original_title == "Original Title"
    assert anime.episodes[0].hosters == ("VOE",)


def test_companion_movies_are_included_as_season_zero_and_resolve():
    base = "https://aniworld.to/anime/stream/test-anime"
    detail_html = _detail_html().replace(
        b"<table",
        b'<a href="/anime/stream/test-anime/filme">Filme</a><table',
        1,
    )
    movie_html = b"""
    <table class="seasonEpisodesList" data-season-id="0"><tbody><tr>
      <td><a href="/anime/stream/test-anime/filme/film-1">Film 1</a></td>
      <td class="seasonEpisodeTitle"><strong>Der Film</strong><span>The Movie</span></td>
      <td><i class="icon VOE" title="VOE"></i></td>
      <td><img class="flag" src="/public/img/german.svg"></td>
    </tr></tbody></table>
    """
    movie_episode_html = b"""
    <li data-lang-key="1" data-link-target="/redirect/movie"><h4>VOE</h4></li>
    """
    scraper = AniWorldScraper(
        session=_Session(
            {
                base: _Response(detail_html),
                f"{base}/filme": _Response(movie_html),
                f"{base}/filme/film-1": _Response(movie_episode_html),
            }
        )
    )

    anime = scraper.get_anime("test-anime")
    page = aniworld_episode_page(anime, "dub", season=0)

    assert page["seasons"][0] == {"season": 0, "label": "Filme", "count": 1}
    assert page["episodes"][0]["kind"] == "movie"
    assert page["episodes"][0]["slug"] == "aniworld:test-anime|dub-s00e001"
    movie = scraper.get_episode(page["episodes"][0]["slug"])
    assert movie.title == "Test Anime S00E001"
    assert movie.url == f"{base}/filme/film-1"
    assert [hoster.name for hoster in movie.hosters] == ["VOE"]


def test_dedicated_aniworld_ui_contains_complete_catalog_and_episode_controls():
    root = Path(__file__).parents[1]
    screen = (root / "web" / "screens" / "aniworld.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles" / "aniworld.css").read_text(encoding="utf-8")

    for expected in (
        'id="aniworld-updates-btn"',
        'id="aniworld-catalog-btn"',
        'id="aniworld-letter-filter"',
        'id="aniworld-genre-filter"',
        'id="aniworld-season-options"',
        'id="aniworld-episode-search"',
        'id="aniworld-episode-status"',
        'id="aniworld-select-season"',
    ):
        assert expected in screen
    assert 'episode.kind === "movie"' in screen
    assert "aniworldSelectableEpisodes" in screen
    assert ".aniworld-detail-panel" in styles
    assert "prefers-reduced-motion" in styles
