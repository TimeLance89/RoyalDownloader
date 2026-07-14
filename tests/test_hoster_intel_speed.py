import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filmpalast_scraper import HosterInfo
from hoster_intel import HosterIntel


class HosterIntelSpeedTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "hoster_intel.json"
        self.intel = HosterIntel(path=self.state_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_name_stats_affect_ranking_for_serienstream_redirects(self):
        slower = HosterInfo(
            "Mirror Beta",
            "https://serienstream.to/r?t=beta-token",
        )
        faster = HosterInfo(
            "Mirror Alpha",
            "https://serienstream.to/r?t=alpha-token",
        )

        self.intel.record_download(
            "https://fast-cdn.example/embed/alpha",
            True,
            hoster_name=faster.name,
            speed_bps=8 * 1024 * 1024,
        )
        self.intel.record_download(
            "https://slow-cdn.example/embed/beta",
            True,
            hoster_name=slower.name,
            speed_bps=128 * 1024,
        )

        ranked = self.intel.rank([slower, faster])

        self.assertEqual(ranked, [faster, slower])
        self.assertGreater(self.intel.score(faster), self.intel.score(slower))

    def test_recent_slow_cooldown_lowers_score(self):
        now = 1_800_000_000.0
        hoster = HosterInfo("VOE", "https://voe.sx/e/example")
        with patch("hoster_intel.time.time", return_value=now):
            self.intel.record_download(
                hoster.url,
                False,
                hoster_name=hoster.name,
                speed_bps=128 * 1024,
                failure_kind="slow",
            )

        with patch("hoster_intel.time.time", return_value=now + 5 * 60):
            cooldown_score = self.intel.score(hoster)
        with patch("hoster_intel.time.time", return_value=now + 25 * 60 * 60):
            expired_score = self.intel.score(hoster)

        self.assertLess(cooldown_score, expired_score)
        self.assertEqual(expired_score - cooldown_score, 35)

    def test_faster_ewma_hoster_ranks_before_slower_hoster(self):
        slower = HosterInfo("Mirror Slow", "https://slow.example/embed/1")
        faster = HosterInfo("Mirror Fast", "https://fast.example/embed/1")
        for _ in range(2):
            self.intel.record_download(
                slower.url,
                True,
                hoster_name=slower.name,
                speed_bps=192 * 1024,
            )
            self.intel.record_download(
                faster.url,
                True,
                hoster_name=faster.name,
                speed_bps=6 * 1024 * 1024,
            )

        ranked = self.intel.rank([slower, faster])

        self.assertEqual(ranked, [faster, slower])
        self.assertGreater(
            self.intel.stats["fast.example"]["speed_bps_ewma"],
            self.intel.stats["slow.example"]["speed_bps_ewma"],
        )

    def test_record_download_persists_speed_and_slow_for_domain_and_name(self):
        now = 1_800_000_000.0
        speed_bps = 160 * 1024
        with patch("hoster_intel.time.time", return_value=now):
            self.intel.record_download(
                "https://vide0.net/e/example",
                False,
                hoster_name="Doodstream",
                speed_bps=speed_bps,
                failure_kind="slow",
            )

        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        reloaded = HosterIntel(path=self.state_path)
        for key in ("vide0.net", "@name:doodstream"):
            with self.subTest(key=key):
                entry = persisted[key]
                self.assertEqual(entry["download_fail"], 1)
                self.assertEqual(entry["speed_bps_ewma"], speed_bps)
                self.assertEqual(entry["speed_samples"], 1)
                self.assertEqual(entry["slow"], 1)
                self.assertEqual(entry["last_slow"], now)
                self.assertEqual(reloaded.stats[key], entry)


if __name__ == "__main__":
    unittest.main()
