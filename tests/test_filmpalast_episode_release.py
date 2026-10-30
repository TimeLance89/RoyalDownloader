import pytest
from bs4 import BeautifulSoup
from types import SimpleNamespace

import server
from providers.filmpalast import FilmpalastScraper


def _load_series(monkeypatch, releases):
    scraper = object.__new__(FilmpalastScraper)
    scraper._log = lambda _: None
    document = BeautifulSoup(
        '<h2 class="bgDark">Dexter: Wiedererwachen S02E01</h2>'
        '<ul class="staffelEpisodenList">' + ''.join(
            f'<li><a class="getStaffelStream" href="//filmpalast.to/stream/dexter-wiedererwachen-s02e{number:02d}">'
            f'Dexter: Wiedererwachen S02E{number:02d}<small>{release}</small></a></li>'
            for number, release in enumerate(releases, 1)
        ) + '</ul>', 'html.parser',
    )
    requests = []
    monkeypatch.setattr(scraper, '_get_soup', lambda url: requests.append(url) or document)
    series = scraper.get_series('dexter-wiedererwachen-s02e01')
    assert len(requests) == 1
    return series


def test_filmpalast_dexter_release_overrides_tmdb_without_unlocking_announcements(monkeypatch):
    # The first release is the row returned by the user's server on 2026-10-30.
    series = _load_series(monkeypatch, [
        'Dexter.Wiedererwachen.S02E01.GERMAN.DL.1080P.WEB.H264-WAYNE',
        '',
        'Demnächst',
    ])
    monkeypatch.setattr(server, '_unreleased_episode_keys', lambda _id, keys: set(keys))

    assert series.all_episodes[0].content_languages == ('de',)
    assert server._unreleased_episode_slugs(series, 123) == {
        'dexter-wiedererwachen-s02e02', 'dexter-wiedererwachen-s02e03',
    }
    monkeypatch.setattr(server.state, 'watchlist', [])
    monkeypatch.setattr(server, 'compute_downloaded_episodes', lambda _: set())
    monkeypatch.setattr(server, 'get_tmdb_series', lambda *_args, **_kwargs: {'tmdb_id': 123})
    monkeypatch.setattr(server, 'get_jellyfin_client', lambda: SimpleNamespace(configured=False))
    payload = server.series_to_dict(series)
    assert [episode['unreleased'] for episode in payload['seasons'][0]['episodes']] == [False, True, True]


@pytest.mark.parametrize(('release', 'expected'), [
    ('Example.S02E01.ENGLISH.720p.HDTV-GROUP', ('en',)),
    ('Example.S02E01.GERMAN.ENGLISH.1080p.WEB-GROUP', ('de', 'en')),
    ('Example.S02E01.GERMAN.DL.1080p.WEB-GROUP', ('de',)),
    ('Example.S02E01.DL.1080p.WEB-GROUP', ()),
    ('German.Crime.S02E01.1080p.WEB-GROUP', ()),
    ('Example.S02E01.GERMAN.SUBBED.1080p.WEB-GROUP', ()),
    ('Example.S02E01.ENGLISH.SUBS.1080p.WEB-GROUP', ()),
    ('Example.S02E01.GERMAN.Demnächst', ()),
    ('Example.S02E010.GERMAN.1080p.WEB-GROUP', ()),
    ('Example.S01E01.GERMAN.1080p.WEB-GROUP', ()),
    ('', ()),
])
def test_only_matching_episode_releases_supply_explicit_audio(release, expected):
    assert FilmpalastScraper._episode_release_languages(release, 2, 1) == expected


def test_explicit_provider_schedule_stays_locked_even_with_release_evidence(monkeypatch):
    series = _load_series(monkeypatch, ['Example.S02E01.GERMAN.1080p.WEB-GROUP'])
    series.all_episodes[0].release_label = 'Demnächst'
    monkeypatch.setattr(server, '_unreleased_episode_keys', lambda *_: set())
    assert server._unreleased_episode_slugs(series, 123) == {'dexter-wiedererwachen-s02e01'}
