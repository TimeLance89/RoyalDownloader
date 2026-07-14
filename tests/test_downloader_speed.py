import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import downloader
from downloader import DownloadJob, _ByteGrowthWatchdog, _LowSpeedWatchdog


class _FinishedProcess:
    """Minimaler erfolgreicher Popen-Ersatz ohne Netzwerkzugriff."""

    def __init__(self, *args, **kwargs):
        self.stdout = iter(())
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


class DownloaderSpeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_speed_parser_supports_binary_kib_and_mib(self):
        kib = DownloadJob._parse_speed_bps(
            "[download] 12.3% of 1.00GiB at 384.50KiB/s ETA 44:12"
        )
        mib = DownloadJob._parse_speed_bps(
            "[download] 52.0% of 1.00GiB at 2.25MiB/s ETA 03:38"
        )

        self.assertAlmostEqual(kib, 384.5 * 1024)
        self.assertAlmostEqual(mib, 2.25 * 1024 * 1024)

    def test_low_speed_watchdog_honors_grace_window_and_recovery(self):
        watchdog = _LowSpeedWatchdog(
            minimum_bps=100,
            grace_seconds=10,
            window_seconds=20,
            started_at=0,
        )

        self.assertFalse(watchdog.observe(50, now=9))
        self.assertIsNone(watchdog.low_since)
        self.assertFalse(watchdog.observe(50, now=10))
        self.assertFalse(watchdog.observe(50, now=29.9))

        # Eine Erholung setzt das bereits fast abgelaufene Langsam-Fenster zurück.
        self.assertFalse(watchdog.observe(150, now=30))
        self.assertIsNone(watchdog.low_since)
        self.assertFalse(watchdog.observe(50, now=31))
        self.assertFalse(watchdog.observe(50, now=50.9))
        self.assertTrue(watchdog.observe(50, now=51))

    def test_byte_growth_watchdog_uses_independent_rate_windows(self):
        watchdog = _ByteGrowthWatchdog(
            minimum_bps=100,
            grace_seconds=10,
            window_seconds=20,
            started_at=0,
        )

        self.assertFalse(watchdog.observe(1000, now=9))
        self.assertFalse(watchdog.observe(4000, now=29))
        self.assertAlmostEqual(watchdog.last_rate_bps, 150)

        self.assertTrue(watchdog.observe(5000, now=49))
        self.assertAlmostEqual(watchdog.last_rate_bps, 50)

    @patch("downloader.subprocess.Popen", side_effect=_FinishedProcess)
    def test_ytdlp_command_enables_hls_fragments_and_mp4_http_chunks(self, popen):
        hls_job = DownloadJob(
            "https://cdn.example/movie.m3u8", "hls", self.root / "hls.mp4"
        )
        mp4_job = DownloadJob(
            "https://cdn.example/movie.mp4", "mp4", self.root / "direct.mp4"
        )

        with patch.object(hls_job, "_prepare_staging", return_value=(True, "")):
            self.assertTrue(hls_job._download_ytdlp()[0])
        with patch.object(mp4_job, "_prepare_staging", return_value=(True, "")):
            self.assertTrue(mp4_job._download_ytdlp()[0])

        hls_cmd = popen.call_args_list[0].args[0]
        mp4_cmd = popen.call_args_list[1].args[0]
        self.assertEqual(
            hls_cmd[hls_cmd.index("--concurrent-fragments") + 1],
            str(downloader.HLS_CONCURRENT_FRAGMENTS),
        )
        self.assertNotIn("--http-chunk-size", hls_cmd)
        self.assertEqual(
            mp4_cmd[mp4_cmd.index("--http-chunk-size") + 1],
            downloader.MP4_HTTP_CHUNK_SIZE,
        )

    def test_slow_ytdlp_failure_skips_direct_fallback(self):
        done = Mock()
        job = DownloadJob(
            "https://cdn.example/movie.mp4",
            "mp4",
            self.root / "movie.mp4",
            on_done=done,
        )

        def fail_slowly():
            job.failure_kind = "slow"
            return False, "Stream dauerhaft zu langsam (100 KiB/s)"

        with patch.object(job, "_download_ytdlp", side_effect=fail_slowly), \
                patch.object(job, "_download_direct") as direct, \
                patch.object(job, "_cleanup_staging"):
            job._run()

        direct.assert_not_called()
        done.assert_called_once_with(
            False, "Stream dauerhaft zu langsam (100 KiB/s)"
        )


if __name__ == "__main__":
    unittest.main()
