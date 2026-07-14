import unittest

from series_episode_filter import available_episode_numbers


class SeriesEpisodeFilterTests(unittest.TestCase):
    def test_skips_upcoming_rows_from_serienstream(self):
        page = """
        <tr class="episode-row" onclick="window.location='/serie/house-of-the-dragon/staffel-3/episode-4'">
          <td>Folge 4</td><td><img class="watch-link" title="VOE"></td>
        </tr>
        <tr class="episode-row upcoming" onclick="window.location='/serie/house-of-the-dragon/staffel-3/episode-5'">
          <td><span class="badge badge-upcoming">DEMNÄCHST</span></td><td>— TBA —</td>
        </tr>
        <tr class="episode-row upcoming" onclick="window.location='/serie/house-of-the-dragon/staffel-3/episode-6'">
          <td><span class="badge badge-release">Sonntag, 26.07.2026</span></td><td>— TBA —</td>
        </tr>
        """
        self.assertEqual(available_episode_numbers(page, "house-of-the-dragon", 3), [4])

    def test_keeps_episode_links_outside_rows_for_older_layouts(self):
        page = """
        <a href="/serie/test-serie/staffel-2/episode-1">1</a>
        <a href="/serie/test-serie/staffel-2/episode-2">2</a>
        """
        self.assertEqual(available_episode_numbers(page, "test-serie", 2), [1, 2])

    def test_does_not_mix_seasons_or_similar_slugs(self):
        page = """
        <a href="/serie/test/staffel-1/episode-1">S1</a>
        <a href="/serie/test/staffel-2/episode-2">S2</a>
        <a href="/serie/test-extra/staffel-2/episode-3">andere Serie</a>
        """
        self.assertEqual(available_episode_numbers(page, "test", 2), [2])


if __name__ == "__main__":
    unittest.main()
