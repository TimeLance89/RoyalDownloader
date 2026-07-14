import unittest
from unittest.mock import patch

from tmdb_client import TMDBClient


class TMDBClientTests(unittest.TestCase):
    def test_movie_by_id_uses_exact_tmdb_id(self):
        client = TMDBClient("key")
        details = {
            "id": 550,
            "title": "Fight Club",
            "original_title": "Fight Club",
            "release_date": "1999-10-15",
            "runtime": 139,
            "genres": [{"name": "Drama"}],
        }

        with patch.object(client, "_request", return_value=details) as request:
            result = client.movie_by_id(550)

        self.assertEqual(result["tmdb_id"], 550)
        self.assertEqual(result["title"], "Fight Club")
        self.assertEqual(result["year"], "1999")
        self.assertEqual(request.call_args.args[0], "/movie/550")

    def test_failed_movie_id_lookup_is_not_cached_forever(self):
        client = TMDBClient("key")
        details = {
            "id": 550,
            "title": "Fight Club",
            "original_title": "Fight Club",
            "release_date": "1999-10-15",
            "overview": "Mock",
        }

        with patch.object(client, "_request", side_effect=[None, details]) as request:
            first = client.movie_by_id(550)
            second = client.movie_by_id(550)

        self.assertIsNone(first)
        self.assertEqual(second["tmdb_id"], 550)
        self.assertEqual(request.call_count, 2)

    def test_series_by_id_returns_fresh_season_counts(self):
        client = TMDBClient("key")
        details = {
            "id": 2316,
            "name": "The Office",
            "original_name": "The Office",
            "first_air_date": "2005-03-24",
            "seasons": [
                {"season_number": 1, "episode_count": 6},
                {"season_number": 2, "episode_count": 22},
            ],
        }

        with patch.object(client, "_request", return_value=details) as request:
            result = client.series_by_id(2316, "The Office")

        self.assertEqual(result["tmdb_id"], 2316)
        self.assertEqual(result["season_episode_counts"], {"1": 6, "2": 22})
        self.assertGreater(result["season_counts_checked_at"], 0)
        self.assertEqual(request.call_args.args[0], "/tv/2316")

    def test_series_match_requires_exact_tmdb_id_and_year(self):
        client = TMDBClient("key")
        search = {
            "results": [
                {
                    "id": 2316,
                    "name": "The Office",
                    "original_name": "The Office",
                    "first_air_date": "2005-03-24",
                },
                {
                    "id": 2996,
                    "name": "The Office",
                    "original_name": "The Office",
                    "first_air_date": "2001-07-09",
                },
            ],
        }

        with patch.object(client, "_request", return_value=search):
            self.assertTrue(client.series_matches_id("The Office", 2316, "2005"))
            self.assertFalse(client.series_matches_id("The Office", 2316, "2001"))
            self.assertFalse(client.series_matches_id("The Office", 9999, "2005"))

    def test_failed_details_never_claim_fresh_season_counts(self):
        client = TMDBClient("key")
        search = {
            "results": [{"id": 2316, "name": "The Office", "first_air_date": "2005-03-24"}],
        }

        with patch.object(client, "_request", side_effect=[search, None]):
            result = client.series("The Office")

        self.assertEqual(result["tmdb_id"], 2316)
        self.assertEqual(result["season_counts_checked_at"], 0)

    def test_failed_id_lookup_is_retried_after_short_negative_ttl(self):
        client = TMDBClient("key")
        details = {
            "id": 2316,
            "name": "The Office",
            "overview": "Mock",
            "seasons": [{"season_number": 1, "episode_count": 6}],
        }

        with patch("tmdb_client.time.time", side_effect=[1000.0, 1061.0]), patch.object(
            client, "_request", side_effect=[None, details],
        ) as request:
            first = client.series_by_id(2316, "The Office")
            second = client.series_by_id(2316, "The Office")

        self.assertIsNone(first)
        self.assertEqual(second["season_episode_counts"], {"1": 6})
        self.assertEqual(request.call_count, 2)

    def test_incomplete_title_result_is_retried_after_short_negative_ttl(self):
        client = TMDBClient("key")
        search = {
            "results": [{"id": 2316, "name": "The Office", "first_air_date": "2005-03-24"}],
        }
        details = {
            "id": 2316,
            "name": "The Office",
            "overview": "Mock",
            "seasons": [{"season_number": 1, "episode_count": 6}],
        }

        with patch(
            "tmdb_client.time.time", side_effect=[1000.0, 1000.0, 1061.0, 1061.0],
        ), patch.object(
            client, "_request", side_effect=[search, None, search, details],
        ) as request:
            first = client.series("The Office")
            second = client.series("The Office")

        self.assertEqual(first["season_counts_checked_at"], 0)
        self.assertEqual(second["season_episode_counts"], {"1": 6})
        self.assertEqual(request.call_count, 4)


if __name__ == "__main__":
    unittest.main()
