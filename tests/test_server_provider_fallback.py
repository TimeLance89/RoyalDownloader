import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import server
from filmpalast_scraper import (
    FilmpalastMovie,
    FilmpalastSeries,
    HosterInfo,
    SeriesEpisode,
)


class _FakeQueue:
    def __init__(self):
        self.jobs = []

    def active_jobs(self):
        return []

    def active_count(self):
        return 0

    def pending_count(self):
        return len(self.jobs)

    def add(self, job):
        self.jobs.append(job)

    def start(self):
        return None


def _episode_movie(slug: str) -> FilmpalastMovie:
    return FilmpalastMovie(
        "Liebe macht blind S01E10",
        f"https://serienstream.to/serie/{slug}",
        hosters=[HosterInfo("VOE", "https://embed.example/video")],
    )


class AutomaticFallbackForwardingTests(unittest.TestCase):
    def setUp(self):
        self.slug = "serienstream:liebe-macht-blind-s01e10"
        self.movie = _episode_movie(self.slug)
        self.snapshot = {
            "picked": server.state.picked,
            "counted": server.state.counted_queue_slugs,
            "done_slugs": server.state.done_slugs,
            "done_jobs": server.state.done_jobs,
            "total_jobs": server.state.total_jobs,
            "content_keys": server.state.queue_content_keys,
            "dl_queue": server.state.dl_queue,
            "fp_movies": server.state.fp_movies,
            "gated_retry_pending": server.state.gated_retry_pending,
            "sto_scraper": server.state.sto_scraper,
            "fallback_series_cache": server.state.fallback_series_cache,
        }
        server.state.picked = {self.slug}
        server.state.counted_queue_slugs = set()
        server.state.done_slugs = set()
        server.state.done_jobs = 0
        server.state.total_jobs = 0
        server.state.queue_content_keys = {}
        server.state.dl_queue = _FakeQueue()
        server.state.fp_movies = {self.slug: self.movie}
        server.state.gated_retry_pending = False
        server.state.sto_scraper = None
        server.state.fallback_series_cache = {}
        self.patches = [
            patch("server.appconfig.save_queue", return_value=True),
            patch("server.broadcast"),
            patch("server.log"),
            patch("server.queue_content_key", return_value="episode:tmdb:42:1:10"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        server.state.picked = self.snapshot["picked"]
        server.state.counted_queue_slugs = self.snapshot["counted"]
        server.state.done_slugs = self.snapshot["done_slugs"]
        server.state.done_jobs = self.snapshot["done_jobs"]
        server.state.total_jobs = self.snapshot["total_jobs"]
        server.state.queue_content_keys = self.snapshot["content_keys"]
        server.state.dl_queue = self.snapshot["dl_queue"]
        server.state.fp_movies = self.snapshot["fp_movies"]
        server.state.gated_retry_pending = self.snapshot["gated_retry_pending"]
        server.state.sto_scraper = self.snapshot["sto_scraper"]
        server.state.fallback_series_cache = self.snapshot["fallback_series_cache"]

    def test_missing_fallback_map_stays_unknown_for_preparation_job(self):
        accepted = server._enqueue_automatic_downloads([self.slug])

        self.assertEqual(accepted, {self.slug})
        self.assertEqual(len(server.state.dl_queue.jobs), 1)
        preparation = server.state.dl_queue.jobs[0]
        self.assertNotIn(self.slug, preparation.movie_fallbacks)

    def test_explicit_empty_fallback_list_is_forwarded_as_already_searched(self):
        accepted = server._enqueue_automatic_downloads(
            [self.slug], movie_fallbacks={self.slug: []},
        )

        self.assertEqual(accepted, {self.slug})
        self.assertEqual(len(server.state.dl_queue.jobs), 1)
        preparation = server.state.dl_queue.jobs[0]
        self.assertIn(self.slug, preparation.movie_fallbacks)
        self.assertEqual(preparation.movie_fallbacks[self.slug], [])

    def test_blocked_episode_page_without_hosters_still_gets_prepared(self):
        self.movie.hosters = []

        accepted = server._enqueue_automatic_downloads([self.slug])

        self.assertEqual(accepted, {self.slug})
        self.assertEqual(len(server.state.dl_queue.jobs), 1)


class EpisodeFallbackLookupTests(unittest.TestCase):
    def setUp(self):
        self.fallback_cache = server.state.fallback_series_cache
        server.state.fallback_series_cache = {}

    def tearDown(self):
        server.state.fallback_series_cache = self.fallback_cache

    def test_localized_title_falls_back_to_original_title_alias(self):
        episode_slug = "moflix:42:love-is-blind-s01e10"
        series = FilmpalastSeries(
            title="Love Is Blind",
            base_slug="moflix:42:love-is-blind",
            url="https://moflix.example/titles/42/love-is-blind",
            seasons={
                1: [SeriesEpisode(1, 10, episode_slug, "https://moflix.example/episode/10")],
            },
        )
        movie = FilmpalastMovie(
            "Love Is Blind S01E10",
            "https://moflix.example/episode/10",
            hosters=[HosterInfo("VEEV", "https://veev.example/video")],
        )

        def lookup(provider, title):
            if provider == "moflix" and title == "Love Is Blind":
                return series
            return None

        with (
            patch("server.SERIES_FALLBACK_PROVIDERS", ("filmpalast", "moflix")),
            patch("server._fallback_get_series", side_effect=lookup) as get_series,
            patch("server.load_movie_for_slug", return_value=movie) as load_movie,
            patch("server.log"),
        ):
            found = server.find_episode_fallbacks(
                "Liebe macht blind",
                1,
                10,
                aliases=("Love Is Blind",),
            )

        self.assertEqual(found, [movie])
        self.assertEqual(
            get_series.call_args_list,
            [
                call("filmpalast", "Liebe macht blind"),
                call("filmpalast", "Love Is Blind"),
                call("moflix", "Liebe macht blind"),
                call("moflix", "Love Is Blind"),
            ],
        )
        load_movie.assert_called_once_with(episode_slug)

    def test_transient_provider_error_is_not_negative_cached(self):
        title = "Love Is Blind"
        series = FilmpalastSeries(
            title=title,
            base_slug="love-is-blind",
            url="https://filmpalast.example/stream/love-is-blind-s01e01",
            seasons={
                1: [
                    SeriesEpisode(
                        1,
                        1,
                        "love-is-blind-s01e01",
                        "https://filmpalast.example/stream/love-is-blind-s01e01",
                    ),
                ],
            },
        )

        class TransientScraper:
            def __init__(self):
                self.search_calls = 0

            def search_series(self, query):
                self.search_calls += 1
                if self.search_calls == 1:
                    raise ConnectionError("temporarily blocked")
                return [SimpleNamespace(title=title, sample_slug="love-is-blind-s01e01")]

            def get_series(self, _slug):
                return series

        scraper = TransientScraper()
        cache_key = f"filmpalast:{server._norm_title(title)}"
        with patch("server.get_fp_scraper", return_value=scraper), patch("server.log"):
            first = server._fallback_get_series("filmpalast", title)
            self.assertIsNone(first)
            self.assertNotIn(cache_key, server.state.fallback_series_cache)

            second = server._fallback_get_series("filmpalast", title)

        self.assertIs(second, series)
        self.assertEqual(scraper.search_calls, 2)
        self.assertIs(server.state.fallback_series_cache[cache_key], series)


if __name__ == "__main__":
    unittest.main()
