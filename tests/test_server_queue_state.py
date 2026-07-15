import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from filmpalast_scraper import (
    FilmpalastMovie,
    FilmpalastSeries,
    HosterInfo,
    SeriesEpisode,
)


class _FakeQueue:
    def __init__(self, active=None):
        self.jobs = []
        self._active = list(active or [])

    def active_jobs(self):
        return list(self._active)

    def active_count(self):
        return len(self._active)

    def pending_count(self):
        return len(self.jobs)

    def add(self, job):
        self.jobs.append(job)

    def start(self):
        return None


class ServerQueueStateTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "picked": set(server.state.picked),
            "counted": set(server.state.counted_queue_slugs),
            "done_slugs": set(server.state.done_slugs),
            "done_jobs": server.state.done_jobs,
            "total_jobs": server.state.total_jobs,
            "watchlist": server.state.watchlist,
            "watchlist_new": server.state.watchlist_new_slugs,
            "telegram_jobs": server.state.telegram_jobs,
            "queue_content_keys": dict(server.state.queue_content_keys),
            "dl_queue": server.state.dl_queue,
            "fp_movies": server.state.fp_movies,
            "gated_retry_pending": server.state.gated_retry_pending,
            "gated_retry_slugs": set(server.state.gated_retry_slugs),
            "sto_scraper": server.state.sto_scraper,
            "fallback_series_cache": server.state.fallback_series_cache,
        }
        server.state.picked = set()
        server.state.counted_queue_slugs = set()
        server.state.done_slugs = set()
        server.state.done_jobs = 0
        server.state.total_jobs = 0
        server.state.watchlist = []
        server.state.watchlist_new_slugs = {}
        server.state.telegram_jobs = {}
        server.state.queue_content_keys = {}
        server.state.dl_queue = _FakeQueue()
        server.state.fp_movies = {}
        server.state.gated_retry_pending = False
        server.state.gated_retry_slugs = set()
        server.state.sto_scraper = None
        server.state.fallback_series_cache = {}
        self.patches = [
            patch("server.appconfig.save_queue", return_value=True),
            patch("server.log"),
            patch("server.broadcast"),
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
        server.state.watchlist = self.snapshot["watchlist"]
        server.state.watchlist_new_slugs = self.snapshot["watchlist_new"]
        server.state.telegram_jobs = self.snapshot["telegram_jobs"]
        server.state.queue_content_keys = self.snapshot["queue_content_keys"]
        server.state.dl_queue = self.snapshot["dl_queue"]
        server.state.fp_movies = self.snapshot["fp_movies"]
        server.state.gated_retry_pending = self.snapshot["gated_retry_pending"]
        server.state.gated_retry_slugs = self.snapshot["gated_retry_slugs"]
        server.state.sto_scraper = self.snapshot["sto_scraper"]
        server.state.fallback_series_cache = self.snapshot["fallback_series_cache"]

    def test_terminal_callback_consumes_counter_only_once(self):
        slug = "show-s01e01"
        server.state.picked = {slug}
        server.state.counted_queue_slugs = {slug}
        server.state.total_jobs = 1

        first = server.on_job_done(True, "ok", "Episode", Path("episode.mp4"), slug=slug)
        second = server.on_job_done(True, "late", "Episode", Path("episode.mp4"), slug=slug)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(server.state.done_jobs, 1)
        self.assertEqual(server.state.done_slugs, {slug})
        self.assertEqual(server.state.counted_queue_slugs, set())

    def test_cross_provider_episode_keys_use_tmdb_identity(self):
        first = FilmpalastMovie("The Office S01E01", "https://one")
        second = FilmpalastMovie("Das Büro S01E01", "https://two")
        with patch("server.get_tmdb_series", return_value={"tmdb_id": 2316}):
            first_key = server.queue_content_key("one:the-office-s01e01", first)
            second_key = server.queue_content_key("two:das-buero-s01e01", second)
        self.assertEqual(first_key, second_key)

    def test_duplicate_tmdb_subscription_is_rejected(self):
        server.state.watchlist = [{
            "base_slug": "one:the-office",
            "title": "The Office",
            "tmdb_id": 2316,
            "aliases": [],
        }]
        body = server.WatchlistAddBody(
            base_slug="two:the-office",
            title="The Office US",
            sample_url="two:the-office",
            known_slugs=[],
            tmdb_id=2316,
        )

        with self.assertRaises(server.HTTPException) as raised:
            asyncio.run(server.api_watchlist_add(body))

        self.assertEqual(raised.exception.status_code, 409)

    def test_localized_legacy_subscription_is_migrated_and_rejected(self):
        old = {
            "base_slug": "one:haus-des-geldes",
            "title": "Haus des Geldes",
            "tmdb_id": None,
            "aliases": [],
        }
        server.state.watchlist = [old]
        body = server.WatchlistAddBody(
            base_slug="two:money-heist",
            title="Money Heist",
            sample_url="two:money-heist",
            known_slugs=[],
            tmdb_id=71446,
        )
        tmdb = {
            "tmdb_id": 71446,
            "title": "Haus des Geldes",
            "original_title": "La casa de papel",
            "season_episode_counts": {"1": 15},
            "season_counts_checked_at": 123.0,
        }

        with (
            patch("server.get_tmdb_series", return_value=tmdb),
            patch("server.appconfig.save_watchlist", return_value=True),
            self.assertRaises(server.HTTPException) as raised,
        ):
            asyncio.run(server.api_watchlist_add(body))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(old["tmdb_id"], 71446)
        self.assertIn("Money Heist", old["aliases"])

    def test_same_title_legacy_subscription_is_not_blindly_relabelled(self):
        old = {
            "base_slug": "one:the-office-uk",
            "title": "The Office",
            "tmdb_id": None,
            "aliases": [],
        }
        server.state.watchlist = [old]
        body = server.WatchlistAddBody(
            base_slug="two:the-office-us",
            title="The Office",
            sample_url="two:the-office-us",
            known_slugs=[],
            tmdb_id=2316,
        )

        with (
            patch("server.get_tmdb_series", return_value={
                "tmdb_id": 2316,
                "title": "The Office",
                "original_title": "The Office",
            }),
            self.assertRaises(server.HTTPException),
        ):
            asyncio.run(server.api_watchlist_add(body))

        self.assertIsNone(old["tmdb_id"])

    def test_watchlist_recheck_cancels_slugs_no_longer_missing(self):
        slug = "show-s01e01"
        entry = {
            "base_slug": "show",
            "title": "Show",
            "sample_url": "show-s01e01",
            "download_mode": "all",
            "known_slugs": [slug],
            "aliases": [],
            "failed_downloads": {},
            "check_generation": 0,
        }
        series = FilmpalastSeries(
            "Show",
            "show",
            "https://show",
            seasons={1: [SeriesEpisode(1, 1, slug, "https://show/1")]},
        )
        server.state.watchlist = [entry]
        server.state.watchlist_new_slugs = {"show": {slug}}
        previous_cfg = server.state.jellyfin_cfg
        server.state.jellyfin_cfg = {}
        try:
            with (
                patch("server.get_series_for_value", return_value=series),
                patch("server.get_tmdb_series", return_value=None),
                patch("server.compute_downloaded_episodes", return_value={slug}),
                patch("server.appconfig.save_watchlist", return_value=True),
                patch("server._cancel_queue_slugs") as cancel,
            ):
                checked = server.check_watchlist_entries([entry])
        finally:
            server.state.jellyfin_cfg = previous_cfg

        self.assertEqual(checked, 1)
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0], {slug})

    def test_automatic_watchlist_check_forces_fresh_jellyfin_data(self):
        entry = {"base_slug": "show", "last_error": ""}
        server.state.watchlist = [entry]

        with (
            patch("server.check_watchlist_entries", return_value=1) as check,
            patch("server._auto_download_new_episodes") as auto_download,
        ):
            checked, total = server._watchlist_auto_check_once()

        self.assertEqual((checked, total), (1, 1))
        check.assert_called_once_with([entry], refresh_jellyfin=True)
        auto_download.assert_called_once_with()

    def test_automatic_watchlist_check_retries_jellyfin_failure_quickly(self):
        server.state.watchlist = [{
            "base_slug": "show",
            "last_error": "Jellyfin nicht erreichbar – Auto-Download pausiert",
        }]

        delay = server._watchlist_auto_check_delay(0, 1, 30)

        self.assertEqual(delay, server.WATCHLIST_JELLYFIN_RETRY_SECONDS)

    def test_automatic_watchlist_check_keeps_interval_for_provider_failure(self):
        server.state.watchlist = [{
            "base_slug": "show",
            "last_error": "Serie beim Anbieter nicht abrufbar",
        }]

        delay = server._watchlist_auto_check_delay(0, 1, 30)

        self.assertEqual(delay, 30 * 60)

    def test_updater_installs_only_the_freshly_verified_revision(self):
        target = "a" * 40
        body = server.UpdateInstallBody(target_sha=target)
        with (
            patch("server.UPDATE_CHECKER.check", return_value={
                "latest_sha": target,
                "update_available": True,
            }) as check,
            patch("server.UPDATE_INSTALLER.start", return_value={"state": "downloading"}) as start,
        ):
            response = asyncio.run(server.api_updater_install(body))

        check.assert_called_once_with(True)
        start.assert_called_once_with(target)
        self.assertEqual(response["installer"]["state"], "downloading")

    def test_updater_rejects_install_while_download_is_active(self):
        server.state.dl_queue = _FakeQueue(active=[object()])
        body = server.UpdateInstallBody(target_sha="b" * 40)

        with self.assertRaises(server.HTTPException) as raised:
            asyncio.run(server.api_updater_install(body))

        self.assertEqual(raised.exception.status_code, 409)

    def test_withdrawn_cancel_preserves_slug_required_by_newer_check(self):
        slug = "show-s01e01"
        server.state.watchlist_new_slugs = {"show": {slug}}

        with patch("server._cancel_queue_slugs") as cancel:
            cancelled = server._cancel_withdrawn_watchlist_slugs(
                {slug}, "old result",
            )

        self.assertEqual(cancelled, set())
        cancel.assert_not_called()

    def test_cross_provider_rejection_is_removed_before_queue_started_snapshot(self):
        first = "provider-a:movie"
        duplicate = "provider-b:movie"
        hoster = HosterInfo("VOE", "https://embed.example/video")
        server.state.fp_movies = {
            first: FilmpalastMovie("Same Movie", "https://provider-a/movie", "2026", hosters=[hoster]),
            duplicate: FilmpalastMovie("Same Movie", "https://provider-b/movie", "2026", hosters=[hoster]),
        }
        server.state.picked = {first, duplicate}

        with patch("server.queue_content_key", return_value="movie:tmdb:42"):
            accepted = server._enqueue_automatic_downloads([first, duplicate])

        self.assertEqual(accepted, {first})
        self.assertEqual(server.state.picked, {first})
        self.assertEqual(server.state.counted_queue_slugs, {first})
        self.assertEqual(len(server.state.dl_queue.jobs), 1)
        queue_started = next(
            call.args[0]
            for call in server.broadcast.call_args_list
            if call.args[0].get("type") == "queue_started"
        )
        self.assertEqual(queue_started["queue"]["count"], 1)

    def test_rejected_cleanup_preserves_counted_and_active_claims(self):
        counted = "provider-a:counted"
        active = "provider-a:active"
        duplicate = "provider-b:duplicate"
        active_job = type("ActiveJob", (), {"queue_slug": active, "queue_slugs": {active}})()
        server.state.dl_queue = _FakeQueue(active=[active_job])
        hoster = HosterInfo("VOE", "https://embed.example/video")
        server.state.fp_movies = {
            slug: FilmpalastMovie(slug, f"https://example/{slug}", hosters=[hoster])
            for slug in (counted, active, duplicate)
        }
        server.state.picked = {counted, active, duplicate}
        server.state.counted_queue_slugs = {counted}
        server.state.total_jobs = 1
        server.state.queue_content_keys = {
            counted: "movie:tmdb:42",
            active: "movie:tmdb:99",
        }
        content_keys = {
            counted: "movie:tmdb:42",
            active: "movie:tmdb:99",
            duplicate: "movie:tmdb:42",
        }

        with patch("server.queue_content_key", side_effect=lambda slug, _movie=None: content_keys[slug]):
            accepted = server._enqueue_automatic_downloads([counted, active, duplicate])

        self.assertEqual(accepted, set())
        self.assertEqual(server.state.picked, {counted, active})
        self.assertEqual(server.state.counted_queue_slugs, {counted})
        self.assertEqual(server.state.total_jobs, 1)
        self.assertEqual(server.state.dl_queue.jobs, [])

    def test_removed_job_ignores_late_terminal_callback(self):
        slug = "show-s01e01"
        server.state.picked = {slug}
        server.state.counted_queue_slugs = {slug}
        server.state.total_jobs = 1

        server._release_removed_queue_slugs({slug})
        accepted = server.on_job_done(
            False, "Abgebrochen", "Episode", Path(""), slug=slug,
        )

        self.assertFalse(accepted)
        self.assertEqual(server.state.done_jobs, 0)
        self.assertEqual(server.state.total_jobs, 0)
        self.assertEqual(server.state.counted_queue_slugs, set())


if __name__ == "__main__":
    unittest.main()
