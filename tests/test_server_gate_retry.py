import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
from filmpalast_scraper import FilmpalastMovie, HosterInfo


class _FakeQueue:
    def __init__(self):
        self.jobs = []

    def active_count(self):
        return 0

    def pending_count(self):
        return len(self.jobs)

    def active_jobs(self):
        return []

    def add(self, job):
        self.jobs.append(job)

    def add_front(self, job):
        self.jobs.insert(0, job)

    def start(self):
        raise AssertionError("Der Test darf keine Queue-Threads starten")


def _episode_movie(slug: str) -> FilmpalastMovie:
    return FilmpalastMovie(
        title="Liebe macht blind S01E10",
        url=f"https://serienstream.to/serie/{slug}",
        hosters=[
            HosterInfo(
                "VOE",
                "https://serienstream.to/r?t=episode-token",
            ),
        ],
    )


def _gated_result() -> server._HosterResult:
    result = server._HosterResult()
    result.gated = True
    return result


class PreparationGateRetryTests(unittest.TestCase):
    def setUp(self):
        self.slug = "serienstream:liebe-macht-blind-s01e10"
        self.movie = _episode_movie(self.slug)

    def test_single_gated_episode_is_deferred_without_terminal_callback(self):
        fallback_map = {self.slug: []}
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            with (
                patch("server._queue_slug_claimed", return_value=True),
                patch("server._existing_valid_episode_path", return_value=None),
                patch("server._extract_from_movie", return_value=_gated_result()),
                patch("server._defer_gated_episode", return_value=True) as defer,
                patch("server.on_job_done") as terminal,
                patch("server.log"),
            ):
                accepted = server.run_download_queue(
                    [(self.movie, self.slug)],
                    out_root,
                    wave=1,
                    movie_fallbacks=fallback_map,
                    start_queue=False,
                )

        self.assertEqual(accepted, {self.slug})
        defer.assert_called_once_with(
            self.movie,
            self.slug,
            out_root,
            1,
            fallback_map,
        )
        terminal.assert_not_called()

    def test_last_gate_wave_finishes_exactly_once(self):
        fallback_map = {self.slug: []}
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            with (
                patch("server._queue_slug_claimed", return_value=True),
                patch("server._existing_valid_episode_path", return_value=None),
                patch("server._extract_from_movie", return_value=_gated_result()),
                patch(
                    "server._defer_gated_episode",
                    wraps=server._defer_gated_episode,
                ) as defer,
                patch("server.on_job_done") as terminal,
                patch("server._ensure_gated_retry_worker") as start_worker,
                patch("server.log"),
            ):
                accepted = server.run_download_queue(
                    [(self.movie, self.slug)],
                    out_root,
                    wave=server.SERIES_MAX_WAVES,
                    movie_fallbacks=fallback_map,
                    start_queue=False,
                )

        self.assertEqual(accepted, set())
        defer.assert_called_once_with(
            self.movie,
            self.slug,
            out_root,
            server.SERIES_MAX_WAVES,
            fallback_map,
        )
        terminal.assert_called_once_with(
            False,
            "serienstream-Captcha blieb trotz aller Wiederholungen aktiv",
            self.movie.title,
            Path(""),
            slug=self.slug,
        )
        start_worker.assert_not_called()


class EpisodeFallbackAliasTests(unittest.TestCase):
    def test_series_slug_supplies_original_title_without_external_metadata(self):
        with (
            patch("server.watchlist_lookup", return_value=None),
            patch("server.get_tmdb_series", return_value=None),
        ):
            aliases = server._episode_fallback_aliases(
                "serienstream:love-is-blind-s01e10",
                "Liebe macht blind",
            )

        self.assertIn("love is blind", aliases)


class GateRetryCoordinatorTests(unittest.TestCase):
    def test_multiple_episodes_share_one_cooldown_worker(self):
        slugs = {
            "serienstream:love-is-blind-s01e10",
            "serienstream:love-is-blind-s01e11",
        }
        snapshot = (
            server.state.picked,
            server.state.counted_queue_slugs,
            server.state.gated_retry_jobs,
            server.state.gated_retry_slugs,
            server.state.gated_retry_pending,
            server.state.gated_retry_worker_running,
        )
        server.state.picked = set(slugs)
        server.state.counted_queue_slugs = set(slugs)
        server.state.gated_retry_jobs = {}
        server.state.gated_retry_slugs = set()
        server.state.gated_retry_pending = False
        server.state.gated_retry_worker_running = False
        try:
            with patch("server.threading.Thread") as thread:
                for slug in slugs:
                    self.assertTrue(
                        server._defer_gated_episode(
                            _episode_movie(slug), slug, Path("downloads"), wave=1,
                        )
                    )

            self.assertEqual(thread.call_count, 1)
            thread.return_value.start.assert_called_once_with()
            self.assertEqual(set(server.state.gated_retry_jobs), slugs)
            self.assertEqual(server.state.gated_retry_slugs, slugs)
            self.assertTrue(server.state.gated_retry_pending)
        finally:
            (
                server.state.picked,
                server.state.counted_queue_slugs,
                server.state.gated_retry_jobs,
                server.state.gated_retry_slugs,
                server.state.gated_retry_pending,
                server.state.gated_retry_worker_running,
            ) = snapshot


class RuntimeGateRetryTests(unittest.TestCase):
    def test_download_failure_that_reaches_gate_is_deferred(self):
        slug = "serienstream:liebe-macht-blind-s01e10"
        movie = _episode_movie(slug)
        initial = server._HosterResult()
        initial.stream_info = ("https://cdn.example/episode.mp4", "web")
        initial.hoster_used = "VOE"
        initial.hoster_url_used = "https://voe.example/e/episode"
        initial.source_hoster_url = "https://serienstream.to/r?t=episode-token"

        fake_queue = _FakeQueue()
        old_queue = server.state.dl_queue
        old_picked = server.state.picked
        server.state.dl_queue = fake_queue
        server.state.picked = {slug}
        try:
            gate_retry = Mock(return_value=True)
            gate_seen = [False]
            with (
                patch("server._queue_slug_claimed", return_value=True),
                patch("server._extract_from_movie", return_value=_gated_result()) as extract,
                patch("server.on_job_done") as terminal,
                patch("server.on_job_progress"),
                patch("server.log"),
                patch.object(server.state.hoster_intel, "record_download"),
            ):
                enqueued = server._enqueue_hoster_attempt(
                    movie=movie,
                    movie_slug=slug,
                    out_path=Path("episode.mp4"),
                    result=initial,
                    unsupported_domains=set(),
                    failed_hoster_urls=set(),
                    attempt_errors=[],
                    source_movies=[movie],
                    source_index=0,
                    source_fallbacks_loaded=[True],
                    refreshed_hoster_urls=set(),
                    gate_seen=gate_seen,
                    gate_retry=gate_retry,
                )

                self.assertTrue(enqueued)
                self.assertEqual(len(fake_queue.jobs), 1)
                fake_queue.jobs[0].on_done(False, "HTTP 403")

            self.assertTrue(gate_seen[0])
            self.assertEqual(extract.call_count, 2)
            gate_retry.assert_called_once_with()
            terminal.assert_not_called()
        finally:
            server.state.dl_queue = old_queue
            server.state.picked = old_picked


if __name__ == "__main__":
    unittest.main()
