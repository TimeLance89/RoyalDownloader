import unittest
from pathlib import Path
from unittest.mock import patch

import server
from filmpalast_scraper import FilmpalastMovie, HosterInfo


class _FakeQueue:
    def __init__(self):
        self.jobs = []

    def add(self, job):
        self.jobs.append(job)

    def add_front(self, job):
        self.jobs.insert(0, job)

    def pop_next(self):
        return self.jobs.pop(0)

    def active_count(self):
        return 0

    def pending_count(self):
        return len(self.jobs)


def _movie(name: str, source_url: str) -> FilmpalastMovie:
    return FilmpalastMovie(
        name,
        f"https://catalog.example/{name.casefold().replace(' ', '-')}",
        hosters=[HosterInfo(name, source_url)],
    )


def _hoster_result(name: str, source_url: str, stream_url: str = "") -> server._HosterResult:
    result = server._HosterResult()
    result.hoster_used = name
    result.source_hoster_url = source_url
    result.hoster_url_used = source_url
    if stream_url:
        result.stream_info = (stream_url, "hls")
    return result


class ServerSlowFallbackTests(unittest.TestCase):
    def setUp(self):
        self.slug = "slow-movie"
        self.primary = _movie("Primary", "https://hoster.example/slow")
        self.fallback = _movie("Fallback", "https://backup.example/dead")
        self.out_path = Path("slow-movie.mp4")
        self.snapshot = {
            "picked": server.state.picked,
            "dl_queue": server.state.dl_queue,
        }
        server.state.picked = {self.slug}
        server.state.dl_queue = _FakeQueue()
        self.patches = [
            patch("server.log"),
            patch("server.on_job_progress"),
            patch("server.on_job_done"),
            patch.object(server.state.hoster_intel, "record_download"),
        ]
        self.log, self.progress, self.done, self.record_download = [
            item.start() for item in self.patches
        ]

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        server.state.picked = self.snapshot["picked"]
        server.state.dl_queue = self.snapshot["dl_queue"]

    def _enqueue_initial(self, result, **overrides):
        values = {
            "movie": self.primary,
            "movie_slug": self.slug,
            "out_path": self.out_path,
            "result": result,
            "unsupported_domains": set(),
            "failed_hoster_urls": set(),
            "attempt_errors": [],
            "source_movies": [self.primary],
            "source_index": 0,
            "source_fallbacks_loaded": [True],
            "refreshed_hoster_urls": set(),
            "slow_candidates": [],
        }
        values.update(overrides)
        enqueued = server._enqueue_hoster_attempt(**values)
        self.assertTrue(enqueued)
        return values

    @staticmethod
    def _fail_as_slow(job, speed=128_000):
        job.failure_kind = "slow"
        job.average_speed_bps = speed
        job.on_done(False, "Download dauerhaft zu langsam")

    def test_slow_download_skips_fresh_reextract_and_uses_next_hoster(self):
        slow = _hoster_result(
            "SlowHost", "https://hoster.example/slow", "https://cdn.example/slow.m3u8",
        )
        next_hoster = _hoster_result(
            "FastHost", "https://hoster.example/fast", "https://cdn.example/fast.m3u8",
        )
        exclusions_seen = []

        def extract(_movie, _unsupported, excluded_hoster_urls=None):
            exclusions_seen.append(set(excluded_hoster_urls or set()))
            return next_hoster

        with patch("server._extract_from_movie", side_effect=extract) as extract_mock:
            state = self._enqueue_initial(slow)
            first_job = server.state.dl_queue.pop_next()
            self._fail_as_slow(first_job)

        self.assertEqual(extract_mock.call_count, 1)
        self.assertEqual(exclusions_seen, [{slow.source_hoster_url}])
        self.assertEqual(state["refreshed_hoster_urls"], set())
        self.assertEqual(len(server.state.dl_queue.jobs), 1)
        next_job = server.state.dl_queue.jobs[0]
        self.assertEqual(next_job.stream_url, "https://cdn.example/fast.m3u8")
        self.assertFalse(next_job.allow_slow)
        self.done.assert_not_called()

    def test_exhausted_alternatives_enqueue_slow_candidate_once_as_reserve(self):
        slow = _hoster_result(
            "SlowHost", "https://hoster.example/slow", "https://cdn.example/slow.m3u8",
        )
        no_stream = _hoster_result("DeadHost", "https://backup.example/dead")

        with patch("server._extract_from_movie", side_effect=[no_stream, no_stream]) as extract:
            self._enqueue_initial(
                slow,
                source_movies=[self.primary, self.fallback],
            )
            first_job = server.state.dl_queue.pop_next()
            self._fail_as_slow(first_job, speed=256_000)

        self.assertEqual(extract.call_count, 2)
        self.assertEqual(len(server.state.dl_queue.jobs), 1)
        reserve = server.state.dl_queue.jobs[0]
        self.assertEqual(reserve.stream_url, "https://cdn.example/slow.m3u8")
        self.assertTrue(reserve.allow_slow)
        self.done.assert_not_called()

    def test_slow_reserve_failure_is_terminal_without_requeue_loop(self):
        slow = _hoster_result(
            "SlowHost", "https://hoster.example/slow", "https://cdn.example/slow.m3u8",
        )
        no_stream = _hoster_result("DeadHost", "https://backup.example/dead")

        with patch("server._extract_from_movie", side_effect=[no_stream, no_stream]) as extract:
            self._enqueue_initial(
                slow,
                source_movies=[self.primary, self.fallback],
            )
            first_job = server.state.dl_queue.pop_next()
            self._fail_as_slow(first_job, speed=256_000)
            reserve = server.state.dl_queue.pop_next()
            self.assertTrue(reserve.allow_slow)

            reserve.failure_kind = "slow"
            reserve.average_speed_bps = 64_000
            reserve.on_done(False, "Reserve ebenfalls zu langsam")

        self.assertEqual(extract.call_count, 2)
        self.assertEqual(server.state.dl_queue.jobs, [])
        self.done.assert_called_once()
        ok, message = self.done.call_args.args[:2]
        self.assertFalse(ok)
        self.assertIn("Letzte langsame Reserve", message)


if __name__ == "__main__":
    unittest.main()
