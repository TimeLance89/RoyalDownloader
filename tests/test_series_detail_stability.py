from providers.models import FilmpalastSeries, SeriesEpisode

import server


def _episode(season: int, episode: int) -> SeriesEpisode:
    return SeriesEpisode(
        season=season,
        episode=episode,
        slug=f"serienstream:test-s{season:02d}e{episode:02d}",
        url=f"https://example.test/staffel-{season}/episode-{episode}",
    )


def _series(seasons: dict[int, list[SeriesEpisode]]) -> FilmpalastSeries:
    return FilmpalastSeries(
        title="Testserie",
        base_slug="serienstream:test",
        url="https://example.test/serie/test",
        seasons=seasons,
    )


def test_series_snapshots_keep_seasons_from_both_provider_reads():
    previous = _series({1: [_episode(1, 1)], 2: [_episode(2, 1)]})
    fresh = _series({1: [_episode(1, 1), _episode(1, 2)], 3: [_episode(3, 1)]})

    merged = server.merge_series_snapshots(previous, fresh)

    assert merged is not None
    assert merged.season_numbers == [1, 2, 3]
    assert [episode.episode for episode in merged.seasons[1]] == [1, 2]


def test_tmdb_season_counts_detect_missing_provider_season():
    payload = {
        "season_episode_counts": {"1": 8, "2": 10, "3": 6},
        "seasons": [{"season": 1}, {"season": 3}],
    }

    assert server.series_payload_missing_seasons(payload) == {2}
