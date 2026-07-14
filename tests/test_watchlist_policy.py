import unittest
from dataclasses import dataclass

from watchlist_policy import (
    WATCH_MODE_ALL,
    WATCH_MODE_LATEST_SEASON,
    WATCH_MODE_NEXT_SEASON,
    select_missing_episode_slugs,
)


@dataclass
class Episode:
    season: int
    episode: int
    slug: str


class WatchlistPolicyTests(unittest.TestCase):
    def setUp(self):
        self.episodes = [
            Episode(season, episode, f"s{season}e{episode}")
            for season in range(1, 4)
            for episode in range(1, 4)
        ]
        self.season_counts = {1: 3, 2: 3, 3: 3}

    def test_all_selects_every_missing_episode(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_ALL,
            downloaded_slugs={"s1e1"},
            jellyfin_existing={(1, 2), (1, 3)},
        )
        self.assertEqual(selected, {f"s{s}e{e}" for s in (2, 3) for e in range(1, 4)})

    def test_latest_selects_complete_latest_season(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_LATEST_SEASON,
            jellyfin_existing={(3, 1)},
        )
        self.assertEqual(selected, {"s3e2", "s3e3"})

    def test_next_selects_season_after_fully_watched_season(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_existing={(1, 1), (1, 2), (1, 3)},
            jellyfin_watched={(1, 1), (1, 2), (1, 3)},
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, {"s2e1", "s2e2", "s2e3"})

    def test_next_starts_with_first_season_when_user_watched_nothing(self):
        selected = select_missing_episode_slugs(
            self.episodes, WATCH_MODE_NEXT_SEASON, jellyfin_watched=set(),
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, {"s1e1", "s1e2", "s1e3"})

    def test_next_waits_without_jellyfin_user_status(self):
        selected = select_missing_episode_slugs(
            self.episodes, WATCH_MODE_NEXT_SEASON,
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, set())

    def test_next_does_not_start_with_specials(self):
        episodes = [Episode(0, 1, "s0e1"), Episode(1, 1, "s1e1")]
        selected = select_missing_episode_slugs(
            episodes, WATCH_MODE_NEXT_SEASON, jellyfin_watched=set(),
            season_episode_counts={1: 1},
        )
        self.assertEqual(selected, {"s1e1"})

    def test_present_but_unwatched_season_does_not_unlock_next_one(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_existing={(s, e) for s in (1, 2) for e in range(1, 4)},
            jellyfin_watched={(1, 1), (1, 2), (1, 3)},
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, set())

    def test_watching_downloaded_season_unlocks_following_season(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_existing={(s, e) for s in (1, 2) for e in range(1, 4)},
            jellyfin_watched={(s, e) for s in (1, 2) for e in range(1, 4)},
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, {"s3e1", "s3e2", "s3e3"})

    def test_watched_seasons_must_be_contiguous(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_existing={
                (1, 1), (1, 2), (1, 3),
                (2, 1), (2, 2),
                (3, 1), (3, 2), (3, 3),
            },
            jellyfin_watched={
                (1, 1), (1, 2), (1, 3),
                (2, 1), (2, 2),
                (3, 1), (3, 2), (3, 3),
            },
            season_episode_counts=self.season_counts,
        )
        self.assertEqual(selected, {"s2e3"})

    def test_next_waits_when_season_size_is_unknown(self):
        selected = select_missing_episode_slugs(
            self.episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_watched={(1, 1), (1, 2), (1, 3)},
        )
        self.assertEqual(selected, set())

    def test_next_does_not_accept_gap_with_same_episode_count(self):
        episodes = [
            Episode(1, 1, "s1e1"), Episode(1, 2, "s1e2"), Episode(1, 4, "s1e4"),
            Episode(2, 1, "s2e1"),
        ]
        selected = select_missing_episode_slugs(
            episodes,
            WATCH_MODE_NEXT_SEASON,
            jellyfin_existing={(1, 1), (1, 2), (1, 4)},
            jellyfin_watched={(1, 1), (1, 2), (1, 4)},
            season_episode_counts={1: 3, 2: 1},
        )
        self.assertEqual(selected, set())


if __name__ == "__main__":
    unittest.main()
