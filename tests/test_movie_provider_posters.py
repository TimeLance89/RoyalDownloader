import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from providers import (
    einschalten,
    filmfrei24,
    filmpalast,
    filmo,
    flixitv,
    huhu,
    kinoking,
    movie2k,
    hdfilme_family,
    kellerkino,
    kinoger,
    kinox,
    megakino,
    moflix,
    ridomovies,
    sflix,
    xcine,
)
from providers.catalog import provider_keys


def _without_init(scraper_class):
    return object.__new__(scraper_class)


def test_every_movie_provider_forwards_listing_poster_to_catalog_card():
    filmpalast_document = BeautifulSoup(
        """
        <article class="liste">
          <h2><a href="/stream/testfilm">Testfilm</a></h2>
          <img src="/files/movies/testfilm.jpg">
        </article>
        """,
        "html.parser",
    )
    filmo_document = BeautifulSoup(
        """
        <a href="/movies/testfilm" class="movie-poster-grid-card">
          <img src="/poster/testfilm.jpg" alt="Testfilm">
          <span class="movie-poster-grid-card__title">Testfilm</span>
        </a>
        """,
        "html.parser",
    )

    posters = {
        "filmfrei24": _without_init(filmfrei24.FilmFrei24Scraper)._result_from_film({
            "id": 1, "title": "Testfilm", "year": 2026, "thumbnail": "/poster.jpg",
        }).cover_url,
        "filmpalast": _without_init(filmpalast.FilmpalastScraper)
            ._parse_listing_soup(filmpalast_document)[0].cover_url,
        "megakino": _without_init(megakino.MegaKinoScraper)._movie_result({
            "_id": "1", "title": "Testfilm", "year": 2026, "poster_path": "/poster.jpg",
        }).cover_url,
        "moflix": _without_init(moflix.MoflixScraper)._result_from_title({
            "id": 1, "name": "Testfilm", "year": 2026, "poster": "/poster.jpg",
        }).cover_url,
        "huhu": _without_init(huhu.HuhuScraper)._movie_result({
            "type": "movie", "ids": {"tmdb_id": 1}, "name": "Testfilm",
            "images": {"poster": "https://image.test/huhu.jpg"},
        }).cover_url,
        "filmo": filmo.FilmoScraper._parse_results(filmo_document)[0].cover_url,
        "einschalten": _without_init(einschalten.EinschaltenScraper)._result_from_title({
            "id": 1, "title": "Testfilm", "releaseDate": "2026-01-01",
            "posterPath": "/poster.jpg",
        }).cover_url,
        "kinoger": kinoger.KinogerScraper._movie_result(kinoger._Card(
            "Testfilm", "2026", "1-testfilm", "https://kinoger.test/test",
            "https://image.test/kinoger.jpg", False,
        )).cover_url,
        "xcine": _without_init(xcine.XcineScraper)._movie_result({
            "_id": "1", "title": "Testfilm", "year": "2026", "poster_path": "/poster.jpg",
        }).cover_url,
        "sflix": _without_init(sflix.SflixScraper)._movie_result(sflix._Card(
            "Testfilm", "testfilm", "https://sflix.test/testfilm", "2026",
            "https://image.test/sflix.jpg", True,
        )).cover_url,
        "flixitv": flixitv.FlixiTVScraper._cards(BeautifulSoup(
            '<a class="card-link" href="/serie?v=ABCDEFGHIJK"><img src="/poster.jpg">'
            '<div class="card-info"><h5>Testfilm (2026)</h5><p>Film</p></div></a>',
            "html.parser",
        ))[0].cover_url,
        "kinoking": kinoking.KinoKingScraper._cards(BeautifulSoup(
            '<div class="fav-data-source" data-id="1" data-type="movie" '
            'data-title="Testfilm" data-img="https://image.test/kinoking.jpg"></div>',
            "html.parser",
        ))[0].cover_url,
        "movie2k": movie2k.Movie2kScraper._cards(BeautifulSoup(
            '<table><tr><td><img src="/poster.jpg"></td><td>'
            '<h2><a href="/stream/testfilm">Testfilm</a></h2></td></tr></table>',
            "html.parser",
        ))[0].cover_url,
        "hdfilme_family": hdfilme_family.HDFilmeFamilyScraper._cards(BeautifulSoup(
            '<div class="item"><img src="/poster.jpg">'
            '<a class="movie-title" href="https://hdfilme.ceo/filme1/1-testfilm-stream.html">Testfilm</a></div>',
            "html.parser",
        ), "https://hdfilme.ceo/")[0].cover_url,
        "kellerkino": kellerkino.KellerKinoScraper._cards(BeautifulSoup(
            '<article class="movie-card"><a class="movie-thumb" href="https://www.kellerkino.com/action/testfilm/">'
            '<img src="/poster.jpg"></a><h2><a href="https://www.kellerkino.com/action/testfilm/">Testfilm</a></h2></article>',
            "html.parser",
        ))[0].cover_url,
        "ridomovies": _without_init(ridomovies.RidomoviesScraper)._movie_result(
            ridomovies._Card(
                "Testfilm", "testfilm", "https://rido.test/testfilm", "2026",
                "https://image.test/rido.jpg", True,
            )
        ).cover_url,
    }

    kinox_scraper = _without_init(kinox.KinoxScraper)
    rss_item = ET.fromstring(
        "<item><description><![CDATA[<img src='/poster.jpg'>]]></description></item>"
    )
    posters["kinox"] = kinox_scraper._rss_cover_url(rss_item)

    assert set(posters) == set(provider_keys("movies"))
    assert all(posters.values()), posters
