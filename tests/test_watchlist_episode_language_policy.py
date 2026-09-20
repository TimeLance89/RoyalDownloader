from features.watchlist_policy import WATCH_MODE_ALL, select_missing_episode_slugs
from providers.models import SeriesEpisode


def test_english_only_episodes_are_excluded_from_german_watchlist_downloads():
    german = SeriesEpisode(4, 10, "series-s04e10", "https://example/e10", content_languages=("de",))
    english_only = SeriesEpisode(4, 11, "series-s04e11", "https://example/e11", content_languages=("en",))

    selected = select_missing_episode_slugs(
        [german, english_only],
        WATCH_MODE_ALL,
        enabled_content_languages={"de"},
    )

    assert selected == {german.slug}


def test_episodes_without_language_metadata_remain_eligible_for_existing_providers():
    unknown_language = SeriesEpisode(1, 1, "series-s01e01", "https://example/e01")

    selected = select_missing_episode_slugs(
        [unknown_language],
        WATCH_MODE_ALL,
        enabled_content_languages={"de"},
    )

    assert selected == {unknown_language.slug}
