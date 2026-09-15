from providers.serienstream import SerienstreamScraper
from features.series_episode_filter import available_episode_numbers, episode_listings


def test_serienstream_english_only_flags_disable_german_episode_selection():
    from bs4 import BeautifulSoup

    page = """
    <tr class="episode-row" onclick="window.location='/serie/9-1-1/staffel-9/episode-15'">
      <td><svg class="watch-language svg-flag-german"></svg>
          <svg class="watch-language svg-flag-english"></svg></td>
    </tr>
    <tr class="episode-row" onclick="window.location='/serie/9-1-1/staffel-9/episode-17'">
      <td><svg class="watch-language svg-flag-english"></svg></td>
    </tr>
    """
    listings = episode_listings(page, "9-1-1", 9)
    episodes = SerienstreamScraper._episodes_from_soup(
        BeautifulSoup(page, "lxml"), "9-1-1", 9,
    )

    assert [item.content_languages for item in listings] == [("de", "en"), ("en",)]
    assert [item.content_languages for item in episodes] == [("de", "en"), ("en",)]


UPCOMING_PAGE = """
<table>
  <tr class="episode-row" onclick="window.location='/serie/lucky/staffel-1/episode-5'">
    <th>5</th><td>Sind wir böse Menschen?</td>
  </tr>
  <tr class="episode-row upcoming" onclick="window.location='/serie/lucky/staffel-1/episode-6'">
    <th>6</th><td><span class="badge badge-upcoming">DEMΝÄCHST</span>
    <span class="badge badge-release">Mittwoch, 12.08.2099 ~00:00&nbsp;Uhr</span></td>
  </tr>
</table>
"""


def test_upcoming_episode_keeps_release_metadata_but_is_not_available():
    listings = episode_listings(UPCOMING_PAGE, "lucky", 1)

    assert [item.episode for item in listings] == [5, 6]
    assert listings[1].release_at == "2099-08-12T00:00:00+02:00"
    assert listings[1].release_label == "12.08.2099 · 00:00"
    assert listings[1].is_released is False
    assert available_episode_numbers(UPCOMING_PAGE, "lucky", 1) == [5]


def test_serienstream_keeps_scheduled_episode_for_the_ui():
    from bs4 import BeautifulSoup

    episodes = SerienstreamScraper._episodes_from_soup(
        BeautifulSoup(UPCOMING_PAGE, "lxml"), "lucky", 1,
    )

    assert [episode.episode for episode in episodes] == [5, 6]
    assert episodes[1].slug == "serienstream:lucky-s01e06"
    assert episodes[1].release_label == "12.08.2099 · 00:00"
    assert episodes[1].is_released is False
