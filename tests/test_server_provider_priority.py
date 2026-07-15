import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server


class _MovieProvider:
    def __init__(self, name):
        self.name = name

    def search(self, _query):
        return [self.name]


_MOVIE_PREFIXES = {
    "filmpalast": "",
    "moflix": "moflix:",
    "einschalten": "einschalten:",
    "kinox": "kinox:",
    "kinoger": "kinoger:",
}


def _movie(provider, name, year="2024"):
    slug = f"{_MOVIE_PREFIXES[provider]}{name.casefold().replace(' ', '-')}"
    suffix = "" if provider == "filmpalast" else f" [{server.PROVIDER_LABELS[provider]}]"
    return server.FilmpalastSearchResult(
        title=f"{name}{suffix}",
        slug=slug,
        url=f"https://{provider}.example/{slug}",
        year=year,
    )


class ProviderPriorityTests(unittest.TestCase):
    def setUp(self):
        self.priority = server.state.provider_priorities
        self.fallback_override = server.SERIES_FALLBACK_PROVIDERS
        self.movie_list_cache = dict(server.state.movie_list_cache)
        with server.state.movie_list_cache_lock:
            server.state.movie_list_cache.clear()
        server.SERIES_FALLBACK_PROVIDERS = None

    def tearDown(self):
        server.state.provider_priorities = self.priority
        server.SERIES_FALLBACK_PROVIDERS = self.fallback_override
        with server.state.movie_list_cache_lock:
            server.state.movie_list_cache.clear()
            server.state.movie_list_cache.update(self.movie_list_cache)

    def test_movie_search_uses_configured_provider_order(self):
        server.state.provider_priorities = {
            "movies": ["kinox", "kinoger", "moflix", "einschalten", "filmpalast"],
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        fp = _MovieProvider("filmpalast")
        with (
            patch("server.get_fp_scraper", return_value=fp),
            patch("server.MoflixScraper", return_value=_MovieProvider("moflix")),
            patch("server.EinschaltenScraper", return_value=_MovieProvider("einschalten")),
            patch("server.KinoxScraper", return_value=_MovieProvider("kinox")),
            patch("server.KinogerScraper", return_value=_MovieProvider("kinoger")),
        ):
            results = server.search_movie_candidates("Dune")

        self.assertEqual(results, ["kinox", "kinoger", "moflix", "einschalten", "filmpalast"])

    def test_movie_catalog_uses_consistent_global_pages_and_carries_all_sources_forward(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        pages = {
            (provider, 1): [
                _movie(provider, f"{provider} eins"),
                _movie(provider, f"{provider} zwei"),
            ]
            for provider in server.appconfig.MOVIE_PROVIDER_DEFAULTS
        }
        calls = []

        def fetch(provider, _mode, _genre, source_page):
            calls.append((provider, source_page))
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 3),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            first = server.movie_catalog_page("new", 1)
            second = server.movie_catalog_page("new", 2)

        self.assertEqual(len(first["results"]), 3)
        self.assertEqual(len(second["results"]), 3)
        self.assertEqual(
            [result.slug for result in second["results"]],
            ["kinox:kinox-eins", "kinoger:kinoger-eins", "filmpalast-zwei"],
        )
        self.assertEqual(
            [source["key"] for source in second["sources"]],
            ["filmpalast", "kinox", "kinoger"],
        )
        self.assertFalse(any(page > 1 for provider, page in calls if provider not in server.MOVIE_PAGINATED_PROVIDERS))

    def test_movie_catalog_loads_real_followup_sources_without_repeating_static_sources(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        pages = {
            ("filmpalast", 1): [_movie("filmpalast", "FP eins"), _movie("filmpalast", "FP zwei")],
            ("kinoger", 1): [_movie("kinoger", "KG eins"), _movie("kinoger", "KG zwei")],
            ("filmpalast", 2): [_movie("filmpalast", "FP drei")],
            ("kinoger", 2): [_movie("kinoger", "KG drei"), _movie("kinoger", "KG vier")],
        }
        calls = []

        def fetch(provider, _mode, _genre, source_page):
            calls.append((provider, source_page))
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 3),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            catalog = server.movie_catalog_page("new", 2)

        self.assertEqual(
            [result.slug for result in catalog["results"]],
            ["kinoger:kg-zwei", "fp-drei", "kinoger:kg-drei"],
        )
        self.assertTrue(catalog["has_more"])
        self.assertIn(("filmpalast", 2), calls)
        self.assertIn(("kinoger", 2), calls)
        for provider in ("moflix", "einschalten", "kinox"):
            self.assertNotIn((provider, 2), calls)

    def test_movie_catalog_keeps_page_boundaries_stable_for_uneven_sources(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        pages = {
            ("filmpalast", 1): [_movie("filmpalast", f"F{index}") for index in range(1, 5)],
            ("kinoger", 1): [_movie("kinoger", "K1")],
            ("kinoger", 2): [_movie("kinoger", f"K{index}") for index in range(2, 5)],
        }

        def fetch(provider, _mode, _genre, source_page):
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 4),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            first = server.movie_catalog_page("new", 1)
            second = server.movie_catalog_page("new", 2)

        first_slugs = [result.slug for result in first["results"]]
        second_slugs = [result.slug for result in second["results"]]
        self.assertEqual(first_slugs, ["f1", "kinoger:k1", "f2", "f3"])
        self.assertEqual(second_slugs, ["f4", "kinoger:k2", "kinoger:k3", "kinoger:k4"])
        self.assertTrue(set(first_slugs).isdisjoint(second_slugs))

    def test_movie_catalog_deduplicates_by_priority_but_keeps_remakes(self):
        server.state.provider_priorities = {
            "movies": ["moflix", "filmpalast", "einschalten", "kinox", "kinoger"],
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        pages = {
            ("moflix", 1): [_movie("moflix", "Dune", "2021")],
            ("filmpalast", 1): [
                _movie("filmpalast", "Dune", "2021"),
                _movie("filmpalast", "King Kong", "1933"),
                _movie("filmpalast", "King Kong", "2005"),
            ],
            ("einschalten", 1): [_movie("einschalten", "Dune", "")],
        }

        def fetch(provider, _mode, _genre, source_page):
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 10),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            catalog = server.movie_catalog_page("new", 1)

        dune = [result for result in catalog["results"] if server._norm_title(result.title) == "dune"]
        king_kong = [result for result in catalog["results"] if server._norm_title(result.title) == "kingkong"]
        self.assertEqual([result.slug for result in dune], ["moflix:dune"])
        self.assertEqual({result.year for result in king_kong}, {"1933", "2005"})

    def test_genre_catalog_paginates_filmpalast_and_kinoger_together(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": list(server.appconfig.SERIES_PROVIDER_DEFAULTS),
        }
        pages = {
            ("filmpalast", 1): [_movie("filmpalast", "Action FP eins")],
            ("kinoger", 1): [_movie("kinoger", "Action KG eins")],
            ("filmpalast", 2): [_movie("filmpalast", "Action FP zwei")],
            ("kinoger", 2): [
                _movie("kinoger", "Action KG zwei"),
                _movie("kinoger", "Action KG drei"),
            ],
        }
        calls = []

        def fetch(provider, mode, genre, source_page):
            calls.append((provider, mode, genre, source_page))
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 2),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            catalog = server.movie_catalog_page("genre", 2, "Action")

        self.assertEqual(
            [result.slug for result in catalog["results"]],
            ["action-fp-zwei", "kinoger:action-kg-zwei"],
        )
        self.assertTrue(catalog["has_more"])
        self.assertIn(("filmpalast", "genre", "Action", 2), calls)
        self.assertIn(("kinoger", "genre", "Action", 2), calls)

    def test_movie_api_exposes_source_mix_and_exact_next_page_state(self):
        result = _movie("kinoger", "API Film")
        catalog = {
            "results": [result],
            "page": 2,
            "has_more": True,
            "sources": [{"key": "kinoger", "label": "KinoGer", "count": 1}],
        }
        with (
            patch("server.movie_catalog_page", return_value=catalog),
            patch("server.get_jellyfin_library", return_value=None),
        ):
            response = asyncio.run(server.api_movies(mode="new", page=2))

        self.assertTrue(response["has_more"])
        self.assertTrue(response["last_page_full"])
        self.assertEqual(response["sources"], catalog["sources"])
        self.assertEqual(response["results"][0]["slug"], "kinoger:api-film")

    def test_movie_api_rejects_unbounded_page_requests(self):
        with patch("server.movie_catalog_page") as catalog:
            with self.assertRaises(server.HTTPException) as raised:
                asyncio.run(server.api_movies(mode="new", page=server.MOVIE_MAX_GLOBAL_PAGE + 1))

        self.assertEqual(raised.exception.status_code, 400)
        catalog.assert_not_called()

    def test_last_allowed_movie_page_never_offers_an_invalid_next_page(self):
        pages = {
            ("filmpalast", 1): [
                _movie("filmpalast", "Limit eins"),
                _movie("filmpalast", "Limit zwei"),
                _movie("filmpalast", "Limit drei"),
            ],
        }

        def fetch(provider, _mode, _genre, source_page):
            return pages.get((provider, source_page), [])

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 1),
            patch("server.MOVIE_MAX_GLOBAL_PAGE", 2),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            catalog = server.movie_catalog_page("new", 2)

        self.assertFalse(catalog["has_more"])

    def test_cold_catalog_jump_stops_before_loading_many_source_waves(self):
        calls = []

        def fetch(provider, _mode, _genre, source_page):
            calls.append((provider, source_page))
            if provider == "kinoger":
                return [_movie("kinoger", f"Kalt {source_page}")]
            return []

        with (
            patch("server.MOVIE_BROWSE_PAGE_SIZE", 1),
            patch("server.MOVIE_MAX_COLD_WAVES_PER_REQUEST", 1),
            patch("server._fetch_movie_provider_page", side_effect=fetch),
        ):
            with self.assertRaises(server.MovieCatalogColdLoadLimit):
                server.movie_catalog_page("new", 3)

        self.assertFalse(any(source_page > 1 for _provider, source_page in calls))

    def test_movie_api_reports_cold_page_jump_as_conflict(self):
        error = server.MovieCatalogColdLoadLimit("Seite noch nicht vorbereitet")
        with patch("server.movie_catalog_page", side_effect=error):
            with self.assertRaises(server.HTTPException) as raised:
                asyncio.run(server.api_movies(mode="new", page=3))

        self.assertEqual(raised.exception.status_code, 409)

    def test_moflix_does_not_repeat_its_first_listing_on_followup_pages(self):
        scraper = server.MoflixScraper(progress_cb=lambda *_args: None)
        with patch.object(scraper, "_bootstrap") as bootstrap:
            results = scraper.list_movies("new", 2)

        self.assertEqual(results, [])
        bootstrap.assert_not_called()

    def test_series_search_uses_configured_provider_order(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": ["moflix", "kinoger", "filmpalast", "serienstream"],
        }

        def search(provider, _query):
            return [provider]

        with patch("server._search_series_for_provider", side_effect=search):
            results = server.search_series_candidates("Dark")

        self.assertEqual(results, ["moflix", "kinoger", "filmpalast", "serienstream"])

    def test_episode_fallback_skips_primary_source_and_keeps_priority(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": ["moflix", "serienstream", "kinoger", "filmpalast"],
        }
        calls = []

        def lookup(provider, title):
            calls.append((provider, title))
            return None

        with patch("server._fallback_get_series", side_effect=lookup):
            server.find_episode_fallbacks(
                "Dark", 1, 1, source_slug="moflix:42:dark-s01e01",
            )

        self.assertEqual(calls, [
            ("serienstream", "Dark"),
            ("kinoger", "Dark"),
            ("filmpalast", "Dark"),
        ])

    def test_episode_sources_are_reordered_for_existing_watchlist_slugs(self):
        server.state.provider_priorities = {
            "movies": list(server.appconfig.MOVIE_PROVIDER_DEFAULTS),
            "series": ["filmpalast", "moflix", "kinoger", "serienstream"],
        }
        sto = SimpleNamespace(url="https://serienstream.to/serie/dark/staffel-1/episode-1")
        fp = SimpleNamespace(url="https://filmpalast.to/stream/dark-s01e01")
        moflix = SimpleNamespace(url="https://moflix-stream.xyz/titles/42/dark/season/1/episode/1")

        ordered = server._ordered_episode_sources([sto, moflix, fp])

        self.assertEqual(ordered, [fp, moflix, sto])

    def test_kinoger_values_are_recognized_as_provider(self):
        self.assertEqual(server.provider_for_value("kinoger:42-dark"), "kinoger")
        self.assertEqual(
            server.provider_for_value("https://kinoger.com/stream/42-dark.html"),
            "kinoger",
        )

    def test_kinoger_mirrors_use_the_matching_extractor_branch(self):
        self.assertEqual(
            server._canonical_hoster_name("FSST", "https://fsst.online/embed/42/"),
            "kinoger",
        )
        self.assertEqual(
            server._canonical_hoster_name("Vidara", "https://kinoger.pw/e/42"),
            "vidara",
        )
        self.assertEqual(
            server._canonical_hoster_name("VOE", "https://kinoger.ru/e/42"),
            "voe",
        )

    def test_telegram_movie_ties_keep_provider_search_order(self):
        first = SimpleNamespace(title="Titanic [Moflix]")
        second = SimpleNamespace(title="Titanic")
        ranked = server._telegram_best_result("Titanic", [first, second])
        self.assertEqual(ranked, [first, second])

    def test_telegram_series_uses_first_provider_for_same_title(self):
        first = SimpleNamespace(
            title="Dark [Moflix]", base_slug="moflix:42:dark", sample_slug="moflix:42:dark",
        )
        second = SimpleNamespace(
            title="Dark [S.to]", base_slug="serienstream:dark", sample_slug="serienstream:dark",
        )
        ranked = server._rank_telegram_series_results("Dark", [first, second])
        self.assertEqual(ranked, [first])


if __name__ == "__main__":
    unittest.main()
