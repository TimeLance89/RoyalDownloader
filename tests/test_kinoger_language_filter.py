from bs4 import BeautifulSoup

import server
from application_services import movie_catalog
from providers.kinoger import KinogerScraper
from providers.models import FilmpalastMovie, HosterInfo


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_kinoger_catalog_marks_explicit_english_release():
    document = _soup("""
      <div id="dle-content"><div class="short">
        <div class="titlecontrol"><div class="title">
          <a href="/stream/10-mutiny.html">Mutiny *ENGLISH* Film</a>
        </div></div>
        <div class="general_box"><div class="content_text"><img src="/mutiny.jpg"></div></div>
      </div></div>
    """)

    result = KinogerScraper._movie_result(KinogerScraper._parse_cards(
        object.__new__(KinogerScraper), document
    )[0])

    assert result.content_language == "en"


def test_normal_title_containing_english_is_not_a_release_marker():
    assert KinogerScraper._title_language_marker("The English Patient") == ""


def test_kinoger_detail_uses_release_language_and_quality(monkeypatch):
    document = _soup("""
      <meta property="og:title" content="Insidious: Out of the Further (2026)">
      <div id="dle-content">
        <div class="images-border">TS/Englisch Beschreibung des Films</div>
        <script>royal.show(1, [["https://voe.sx/e/one"]])</script>
      </div>
    """)
    scraper = object.__new__(KinogerScraper)
    scraper._log = lambda *_args: None
    monkeypatch.setattr(scraper, "_get_soup", lambda _url: document)

    movie = scraper.get_movie("kinoger:10-insidious")

    assert movie.content_language == "en"
    assert movie.hosters[0].language == "English"
    assert movie.hosters[0].quality == "TS"


def test_german_catalog_rejects_explicit_english_release(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    result = KinogerScraper._movie_result(KinogerScraper._parse_cards(
        object.__new__(KinogerScraper),
        _soup("""
          <div id="dle-content"><div class="short">
            <div class="titlecontrol"><div class="title">
              <a href="/stream/10-mutiny.html">Mutiny *ENGLISH* Film</a>
            </div></div>
            <div class="general_box"><div class="content_text"></div></div>
          </div></div>
        """),
    )[0])

    assert server._apply_provider_metadata_many([result], "kinoger") == []


def test_kinoger_catalog_reads_language_from_quality_label(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    cards = KinogerScraper._parse_cards(
        object.__new__(KinogerScraper),
        _soup("""
          <div id="dle-content"><div class="short">
            <div class="titlecontrol"><div class="title">
              <a href="/stream/11-insidious.html">Insidious: Out of the Further Film</a>
            </div></div>
            <div class="general_box"><div class="content_text">
              <span>TS/Englisch</span><img src="/insidious.jpg">
            </div></div>
          </div></div>
        """),
    )

    result = KinogerScraper._movie_result(cards[0])
    assert result.content_language == "en"
    assert server._apply_provider_metadata_many([result], "kinoger") == []


def test_direct_kinoger_load_rejects_english_detail_for_german_lane(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    english = FilmpalastMovie(
        title="Insidious: Out of the Further",
        url="https://kinoger.com/stream/10-insidious.html",
        content_language="en",
        hosters=[HosterInfo("VOE", "https://voe.sx/e/one", "English", "TS")],
    )
    fake = type("FakeKinoger", (), {"get_movie": lambda self, _slug: english})()
    monkeypatch.setattr(movie_catalog, "KinogerScraper", lambda progress_cb=None: fake)

    assert movie_catalog.load_movie_for_slug("kinoger:10-insidious") is None
