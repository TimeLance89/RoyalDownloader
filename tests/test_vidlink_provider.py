from types import SimpleNamespace

import pytest

from providers import vidlink


class TMDB:
    def movie_by_id(self, _value):
        return {"title": "Inception", "year": "2010"}

    def series_by_id(self, _value):
        return {"title": "Game of Thrones", "year": "2011", "season_episode_counts": {"2": 10}}

    def search_movies(self, _query, max_results=12):
        return [{"tmdb_id": 27205, "title": "Inception"}]

    def series_summary(self, _query):
        return {"tmdb_id": 1399, "title": "Game of Thrones"}


class Pool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def extract(self, url, **options):
        self.calls.append((url, options))
        return self.result


@pytest.mark.parametrize("slug,page", [
    ("vidlink:27205", "https://vidlink.pro/movie/27205"),
    ("vidlink:1399-s2e3", "https://vidlink.pro/tv/1399/2/3"),
])
def test_vidlink_film_and_exact_episode_are_direct_dash(monkeypatch, slug, page):
    media = "https://flood.sourcerrr.online/sacdn/dash/123_2_3_1080_h265_1/index_web.mpd?sc=signed"
    pool = Pool((media, "dash"))
    monkeypatch.setattr(vidlink, "probe_stream_url", lambda *_args, **_kwargs: (True, "ok"))
    scraper = vidlink.VidLinkScraper(tmdb=TMDB(), pool=pool)
    scraper._get = lambda *_args, **_kwargs: SimpleNamespace(text='<MPD><AdaptationSet lang="en"/></MPD>')
    movie = scraper.get_movie(slug)
    assert movie.hosters[0].url == media
    assert movie.hosters[0].stream_type == "dash"
    assert movie.hosters[0].language == movie.hosters[0].audio_language == "en"
    assert movie.hosters[0].quality == "1080p"
    assert movie.hosters[0].referer == page
    assert pool.calls[0][0] == page
    assert movie.title.endswith("S02E03") == ("s2e3" in slug)


def test_vidlink_cdn_mirror_and_missing_source(monkeypatch):
    bad = "https://noon.mooncase.online/sacdn/dash/123_0_0_720_h265_1/index_web.mpd?sc=signed"
    pool = Pool((bad, "dash"))
    monkeypatch.setattr(vidlink, "probe_stream_url", lambda url, **_kwargs: ("flood.sourcerrr.online" in url, ""))
    scraper = vidlink.VidLinkScraper(tmdb=TMDB(), pool=pool)
    scraper._get = lambda *_args, **_kwargs: SimpleNamespace(text="<MPD/>")
    movie = scraper.get_movie("vidlink:27205")
    assert movie.hosters[0].url.startswith("https://flood.sourcerrr.online/")
    assert scraper.get_movie("vidlink:1399-s0e1") is None
    assert scraper.get_movie("vidlink:1399-s2") is None
    pool.result = None
    assert scraper.get_movie("vidlink:27205") is None
