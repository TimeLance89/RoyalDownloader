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
