import unittest

from bs4 import BeautifulSoup

from extractor import _extract_regex
from kinoger_scraper import KinogerScraper


LISTING_HTML = """
<div id="dle-content">
  <div class="short">
    <div class="titlecontrol"><div class="title"><a href="/stream/99-film.html">Film (2025)</a></div></div>
    <div class="general_box"><div class="content_text"><img src="/film.jpg">WEBRip<br>Text</div></div>
  </div>
  <div class="short">
    <div class="titlecontrol"><div class="title"><a href="/stream/42-serie.html">Serie (2024)</a></div></div>
    <div class="general_box"><div class="content_text"><img src="/serie.jpg">S01-02E01-08<br>Text</div></div>
  </div>
</div>
"""


DETAIL_HTML = """
<html><head><meta property="og:title" content="Testserie (2024)"></head><body>
<div id="dle-content">
  <ul><li class="category"><a href="/stream/">Stream</a> / <a href="/stream/drama/">Drama</a> / <a href="/stream/serie/">Serie</a></li></ul>
  <div class="images-border"><img src="/cover.jpg"><b>S01-02E01-02</b>
    Eine Beschreibung.<br><br>Spielzeit: 48 min<br>Genre: Drama
  </div>
  <script>pw.show(2,[['https://fsst.online/embed/a/',' https://fsst.online/embed/b/'],['https://fsst.online/embed/c/']],0.2);</script>
  <script>fsst.show(2,[['https://kinoger.pw/e/a',' https://kinoger.pw/e/b'],['https://kinoger.pw/e/c']],0.2);</script>
  <script>go.show(2,[['https://kinoger.ru/e/a',' https://kinoger.ru/e/b'],['https://kinoger.ru/e/c']],0.2);</script>
  <script>ollhd.show(2,[['https://kinoger.be/v/a',' https://kinoger.be/v/b'],['https://kinoger.be/v/c']],0.2);</script>
</div>
</body></html>
"""


class _FixtureScraper(KinogerScraper):
    def __init__(self, html):
        self.html = html
        self._log = lambda _message: None

    def _get_soup(self, _url, params=None):
        return BeautifulSoup(self.html, "lxml")


class KinogerScraperTests(unittest.TestCase):
    def test_listing_separates_movies_and_series(self):
        scraper = _FixtureScraper(LISTING_HTML)

        movies = scraper.search("Test")
        series = scraper.search_series("Test")

        self.assertEqual([item.slug for item in movies], ["kinoger:99-film"])
        self.assertEqual([item.base_slug for item in series], ["kinoger:42-serie"])
        self.assertEqual(series[0].cover_url, "https://kinoger.com/serie.jpg")

    def test_series_and_episode_use_embedded_player_arrays(self):
        scraper = _FixtureScraper(DETAIL_HTML)

        series = scraper.get_series("kinoger:42-serie")
        episode = scraper.get_movie("kinoger:42-serie-s01e02")

        self.assertEqual(series.title, "Testserie")
        self.assertEqual(series.season_numbers, [1, 2])
        self.assertEqual([len(series.seasons[number]) for number in (1, 2)], [2, 1])
        self.assertEqual(series.seasons[1][1].slug, "kinoger:42-serie-s01e02")
        self.assertEqual(episode.title, "Testserie S01E02")
        self.assertEqual(
            [hoster.name for hoster in episode.hosters],
            ["FSST", "Vidara", "VOE", "VidHide"],
        )
        self.assertEqual(episode.runtime, "48 min")
        self.assertEqual(episode.genres, ["Drama"])

    def test_quality_playlist_returns_single_best_mp4(self):
        html = '''file:"[360p]https://cdn.test/video_360p.mp4/,
        [720p]https://cdn.test/video_720p.mp4/,
        [1080p]https://cdn.test/video.mp4/"'''

        self.assertEqual(
            _extract_regex(html),
            ("https://cdn.test/video.mp4/", "mp4"),
        )


if __name__ == "__main__":
    unittest.main()
