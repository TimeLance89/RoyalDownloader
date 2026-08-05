from providers.catalog import provider_for_source, provider_keys
from providers.filmo import FilmoScraper


class _Response:
    def __init__(self, text="", *, data=None, status=200, headers=None, url=""):
        self.text = text
        self._data = data
        self.status_code = status
        self.headers = headers or {}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _Session:
    def __init__(self, detail_html):
        self.detail_html = detail_html
        self.cookies = {"XSRF-TOKEN": "csrf-token"}
        self.posts = []

    def get(self, url, **kwargs):
        if "/n/" in url:
            return _Response(status=302, headers={"Location": "https://voe.sx/e/example"})
        return _Response(self.detail_html, url=url)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _Response(data={"x": "minted-token"})


def test_filmo_result_cards_are_normalized_and_deduplicated():
    from bs4 import BeautifulSoup

    document = BeautifulSoup(
        """
        <html><title>Suche</title><body>
          <a href="https://filmo.to/movies/matrix" class="movie-poster-grid-card">
            <img src="/poster.jpg" alt="Matrix">
            <div class="movie-poster-grid-card__title">Matrix</div>
          </a>
          <a href="/movies/matrix"><h4 class="popular-spotlight-card__title">Matrix</h4></a>
        </body></html>
        """,
        "html.parser",
    )

    results = FilmoScraper._parse_results(document)

    assert len(results) == 1
    assert results[0].slug == "filmo:matrix"
    assert results[0].title == "Matrix  [Filmo]"
    assert results[0].cover_url == "https://filmo.to/poster.jpg"


def test_filmo_movie_resolves_minted_hoster_with_language_and_quality():
    detail_html = """
    <html><title>Film</title><body>
      <div id="movie-detail-page">
        <h1>Der Testfilm</h1>
        <p class="movie-detail-synopsis">Beschreibung</p>
        <span class="ft-meta-label"><a href="/genres/science-fiction">Science Fiction</a></span>
        <span class="ft-meta-label">1 h 42 min</span><span class="ft-meta-label">2024</span>
      </div>
      <img class="movie-poster-modal__img" data-src="/img/poster/test">
      <div class="provider-row">
        <span class="provider-row__lang">Deutsch</span>
        <div data-provider-chip data-p="encrypted">
          <span class="provider-chip__name">VOE</span>
          <span class="provider-chip__metadata-tag">WEB</span>
          <span class="provider-chip__metadata-tag">720p</span>
        </div>
      </div>
    </body></html>
    """
    scraper = FilmoScraper()
    scraper.session = _Session(detail_html)

    movie = scraper.get_movie("filmo:der-testfilm")

    assert movie is not None
    assert movie.title == "Der Testfilm"
    assert movie.year == "2024"
    assert movie.runtime == "102 min"
    assert movie.genres == ["Science Fiction"]
    assert movie.hosters[0].name == "VOE"
    assert movie.hosters[0].language == "Deutsch"
    assert movie.hosters[0].quality == "720p"
    assert movie.hosters[0].url == "https://voe.sx/e/example"
    assert scraper.session.posts[0][1]["headers"]["X-XSRF-TOKEN"] == "csrf-token"


def test_filmo_is_registered_as_german_movie_provider():
    assert "filmo" in provider_keys("movies")
    assert provider_for_source("filmo:matrix") == "filmo"
    assert provider_for_source("https://filmo.to/movies/matrix") == "filmo"
