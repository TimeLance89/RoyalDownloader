from bs4 import BeautifulSoup
import pytest

from providers.models import SeriesEpisode
from providers.serienstream import SerienstreamScraper
from media.session_manager import ProviderBlockedError


def _episode(slug: str, season: int, episode: int) -> SeriesEpisode:
    return SeriesEpisode(
        season=season,
        episode=episode,
        slug=f"serienstream:{slug}-s{season:02d}e{episode:02d}",
        url=(
            f"https://serienstream.to/serie/{slug}/staffel-{season}"
            f"/episode-{episode}"
        ),
    )


def test_filme_tab_is_not_exposed_as_season_zero(monkeypatch):
    slug = "house-of-the-dragon"
    soup = BeautifulSoup(
        f"""
        <h1>House of the Dragon</h1>
        <a href="/serie/{slug}/staffel-0">Filme</a>
        <a href="/serie/{slug}/staffel-1">1</a>
        <a href="/serie/{slug}/staffel-2">2</a>
        <a href="/serie/{slug}/staffel-3">3</a>
        """,
        "html.parser",
    )
    scraper = SerienstreamScraper(session=object())
    monkeypatch.setattr(scraper, "_get_soup", lambda *_args, **_kwargs: soup)
    monkeypatch.setattr(
        scraper,
        "_episodes_from_soup",
        lambda _soup, series_slug, season: [
            _episode(series_slug, season, number) for number in range(1, 11)
        ],
    )
    loaded_seasons = []

    def load_season(series_slug, season):
        loaded_seasons.append(season)
        return [_episode(series_slug, season, number) for number in range(1, 9)]

    monkeypatch.setattr(scraper, "_load_season", load_season)

    series = scraper.get_series(f"serienstream:{slug}")

    assert series is not None
    assert series.season_numbers == [1, 2, 3]
    assert len(series.all_episodes) == 26
    assert loaded_seasons == [2, 3]


def test_filme_tab_cannot_be_resolved_as_episode():
    scraper = SerienstreamScraper(session=object())

    assert scraper.get_movie("serienstream:house-of-the-dragon-s00e01") is None
    assert scraper.get_movie(
        "https://serienstream.to/serie/house-of-the-dragon/staffel-0/episode-1"
    ) is None


@pytest.mark.parametrize("metadata", [
    '<span itemprop="startDate">2026</span>',
    '<meta itemprop="startDate" content="2026-02-01">',
    '<span class="series-year">2026–2027</span>',
    '',
])
def test_remake_detail_keeps_start_year(monkeypatch, metadata):
    scraper = SerienstreamScraper(session=object())
    soup = BeautifulSoup(f"<h1>Scrubs</h1>{metadata}", "html.parser")
    monkeypatch.setattr(scraper, "_get_soup", lambda *_args, **_kwargs: soup)
    monkeypatch.setattr(scraper, "_episodes_from_soup", lambda *_args: [_episode("scrubs-2026", 1, 1)])
    assert scraper.get_series("serienstream:scrubs-2026").year == "2026"


def test_remake_card_keeps_year_from_slug():
    scraper = SerienstreamScraper(session=object())
    soup = BeautifulSoup('<a href="/serie/one-piece-2023"><img alt="One Piece"></a>', "html.parser")
    assert scraper._parse_cards(soup)[0].year == "2023"


def test_blocked_season_is_not_silently_treated_as_missing(monkeypatch):
    scraper = SerienstreamScraper(session=object())

    def blocked(*_args, **_kwargs):
        raise ProviderBlockedError("captcha", 403)

    monkeypatch.setattr(scraper, "_get_soup", blocked)

    with pytest.raises(ProviderBlockedError):
        scraper._load_season("house-of-the-dragon", 2)


def test_merged_monster_anthology_loads_hinted_seasons_when_root_has_no_nav(monkeypatch):
    slug = "monster-2022"
    soup = BeautifulSoup("<h1>Monster</h1>", "html.parser")
    scraper = SerienstreamScraper(session=object())
    monkeypatch.setattr(scraper, "_get_soup", lambda *_args, **_kwargs: soup)
    monkeypatch.setattr(scraper, "_episodes_from_soup", lambda *_args, **_kwargs: [])
    loaded_seasons = []

    def load_season(series_slug, season):
        loaded_seasons.append(season)
        return [_episode(series_slug, season, 1)]

    monkeypatch.setattr(scraper, "_load_season", load_season)

    series = scraper.get_series(f"serienstream:{slug}")

    assert series is not None
    assert series.season_numbers == [1, 2, 3, 4]
    assert loaded_seasons == [1, 2, 3, 4]
    assert [episode.slug for episode in series.all_episodes] == [
        f"serienstream:{slug}-s01e01",
        f"serienstream:{slug}-s02e01",
        f"serienstream:{slug}-s03e01",
        f"serienstream:{slug}-s04e01",
    ]


def test_subtitle_language_id_overrides_misleading_german_label():
    from providers.catalog import normalize_content_language
    scraper = SerienstreamScraper(session=object())
    soup = BeautifulSoup('''<button data-play-url="/r?t=sub" data-language-id="3"
        data-language-label="Deutsch" data-provider-name="VOE"></button>
        <button data-play-url="/r?t=dub" data-language-id="1"
        data-language-label="Deutsch" data-provider-name="VOE"></button>''', "html.parser")
    dub, sub = scraper._extract_hosters(soup)
    assert dub.is_de
    assert not sub.is_de
    assert normalize_content_language(sub.language) == ""
@pytest.mark.parametrize("attributes,expected", [
    ('data-language-id="2" data-language-label="Deutsch"', "Englisch"),
    ("", ""),
])
def test_episode_hoster_never_invents_german_audio(attributes, expected):
    scraper = SerienstreamScraper(session=object())
    soup = BeautifulSoup(f'<button data-play-url="/r?t=stream" {attributes}></button>', "html.parser")
    assert scraper._extract_hosters(soup)[0].language == expected
