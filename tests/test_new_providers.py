"""Provider contracts: typed search, exact episode identity, and cooldown."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from media.provider_health import ProviderHealth
from providers.flixitv import FlixiTVScraper
from providers.kinoking import KinoKingScraper


def soup(html):
    return BeautifulSoup(html, "lxml")


FLIXI_SEARCH = '''<a class="card-link" href="/serie?v=ABCDEFGHIJK"><div class="card-info">
<h5>Exact Show (2020-2023)</h5><p>21 Folgen · Serie</p></div></a>
<a class="card-link" href="/serie?v=LMNOPQRSTUV"><div class="card-info">
<h5>Exact Film (2021)</h5><p>Film</p></div></a>'''
FLIXI_DETAIL = '''<h2>Exact Show (2020-2023)</h2><li>21 Folgen</li>
<a href="?v=ABCDEFGHIJK&s=1">Staffel 1</a><a href="?v=ABCDEFGHIJK&s=2">Staffel 2</a>'''
FLIXI_SEASON = '''<table><tbody>
<tr><td></td><td><a href="/watch?v=EPI00000001">1</a></td><td>Pilot Teil 1 &amp; 2</td></tr>
<tr><td></td><td><a href="/watch?v=EPI00000003">3</a></td><td>Third</td></tr>
</tbody></table>'''
KINO_SEARCH = '''<div class="fav-data-source" data-id="123" data-type="series"
 data-tmdb="777" data-title="Exact Show" data-img="poster.jpg">Exact Show 2020</div>
<div class="fav-data-source" data-id="124" data-type="series"
 data-tmdb="778" data-title="Exact Show: Feds">Exact Show: Feds</div>
<div class="fav-data-source" data-id="125" data-type="movie"
 data-tmdb="999" data-title="Exact Film">Exact Film 2021</div>'''
KINO_SERIES = '''<title>Exact Show (2020) - Stream</title><script>
const allEpisodesData = [{"id":21,"season_number":2,"episode_number":4,
"name":"Fourth","air_date":"2020-01-01","video_links":"https://voe.sx/e/abc"},
{"id":22,"season_number":2,"episode_number":5,"name":"Fifth",
"air_date":"2020-01-08","video_links":"https://voe.sx/e/def,https://dood.to/e/xyz"}];
</script>'''
KINO_MOVIE = '''<title>Exact Film (2021) - Stream</title><script>
const SERVERS = [{"name":"Server C1 (DE)","mirrors":["https://voe.sx/e/abc"]},
{"name":"Server C1 (EN)","mirrors":["https://dood.to/e/xyz"]}];
</script>'''


def test_flixitv_search_and_explicit_episode_numbers(monkeypatch):
    provider = FlixiTVScraper()
    pages = {
        "/search/": soup(FLIXI_SEARCH),
        "/serie/?v=ABCDEFGHIJK": soup(FLIXI_DETAIL),
        "/serie/?v=ABCDEFGHIJK&s=1": soup(FLIXI_SEASON),
        "/serie/?v=ABCDEFGHIJK&s=2": soup("<table><tbody></tbody></table>"),
    }
    monkeypatch.setattr(provider, "_request", lambda path, **_kwargs: pages[path])
    assert [item.title for item in provider.search("Exact")] == ["Exact Film"]
    assert [item.title for item in provider.search_series("Exact")] == ["Exact Show"]
    series = provider.get_series("flixitv:ABCDEFGHIJK")
    assert [(item.season, item.episode) for item in series.all_episodes] == [(1, 3)]
    assert series.all_episodes[0].release_name == "Third"


def test_kinoking_typed_search_episode_and_languages(monkeypatch):
    provider = KinoKingScraper()
    monkeypatch.setattr(provider, "_request", lambda path: (
        soup(KINO_SEARCH) if "index.php" in path else
        soup(KINO_SERIES) if "series.php" in path else soup(KINO_MOVIE)
    ))
    series_results = provider.search_series("Exact")
    assert [(x.title, x.tmdb_id) for x in series_results] == [
        ("Exact Show", "777"), ("Exact Show: Feds", "778"),
    ]
    assert [(x.title, x.tmdb_id) for x in provider.search("Exact")] == [("Exact Film", "999")]
    series = provider.get_series("kinoking:123")
    assert [(x.season, x.episode) for x in series.all_episodes] == [(2, 4), (2, 5)]
    assert provider.get_movie("kinoking:123-s02e06") is None
    episode = provider.get_movie("kinoking:123-s02e05")
    assert episode.title == "Exact Show S02E05"
    assert [x.name for x in episode.hosters] == ["VOE", "Doodstream"]
    movie = provider.get_movie("kinoking:125")
    assert [(x.name, x.language) for x in movie.hosters] == [
        ("VOE", "Deutsch"), ("Doodstream", "English"),
    ]


def test_provider_cooldown_stops_repeat_request(monkeypatch, tmp_path):
    import providers.kinoking as module
    health = ProviderHealth(Path(tmp_path) / "health.json", initial_cooldown=60)
    provider = KinoKingScraper(health=health)
    monkeypatch.setattr(module, "_BLOCKED_UNTIL", 0)
    monkeypatch.setattr(module, "_LAST_REQUEST", 0)
    monkeypatch.setattr(module, "_CACHE", {})
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(provider.session.session, "get", fail)
    with pytest.raises(TimeoutError):
        provider.search("Exact")
    with pytest.raises(RuntimeError, match="Cooldown"):
        provider.search("Exact")
    assert len(calls) == 1
    assert health.status("kinoking")["state"] == "cooldown"

@pytest.mark.parametrize("name, provider_cls", [("flixitv", FlixiTVScraper), ("kinoking", KinoKingScraper)])
def test_runtime_session_shared_but_sentinel_probe_isolated(name, provider_cls):
    from providers.probe_contracts import create_adapter

    first = provider_cls()
    second = provider_cls()
    probe = create_adapter(name)
    assert first.session.session is second.session.session
    assert probe.session.session is not first.session.session
    probe.session.close()
