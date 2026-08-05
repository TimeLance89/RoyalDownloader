from bs4 import BeautifulSoup

from providers.models import SeriesEpisode
from providers.serienstream import SerienstreamScraper


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
