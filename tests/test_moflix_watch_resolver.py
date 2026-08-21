from providers.moflix import API_URL, BASE_URL, MoflixScraper


class _Response:
    def __init__(self, payload=None, *, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _scraper(response):
    scraper = object.__new__(MoflixScraper)
    scraper.session = _Session(response)
    scraper._log = lambda _message: None
    return scraper


def test_watch_src_uses_json_api_with_required_browser_headers():
    scraper = _scraper(_Response({"data": {"video": {"src": "https://veev.to/e/test"}}}))

    assert scraper._watch_src(4711) == "https://veev.to/e/test"

    url, request = scraper.session.calls[0]
    assert url == f"{API_URL}/watch/4711"
    assert request["headers"]["Referer"] == f"{BASE_URL}/"
    assert request["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert request["headers"]["Accept"] == "application/json, text/plain, */*"


def test_watch_src_falls_back_to_legacy_bootstrap(monkeypatch):
    scraper = _scraper(_Response(error=RuntimeError("API unavailable")))
    monkeypatch.setattr(
        scraper,
        "_bootstrap",
        lambda _url: {"loaders": {"watchPage": {"video": {"src": "https://rpmplay.test/e/7"}}}},
    )

    assert scraper._watch_src(7) == "https://rpmplay.test/e/7"


def test_movie_resolves_primary_video_id_through_watch_api(monkeypatch):
    scraper = _scraper(_Response({}))
    monkeypatch.setattr(
        scraper,
        "_bootstrap",
        lambda _url: {
            "loaders": {
                "titlePage": {
                    "title": {
                        "id": 42,
                        "model_type": "title",
                        "name": "The End of Oak Street",
                        "primary_video": 99,
                    }
                }
            }
        },
    )
    monkeypatch.setattr(scraper, "_watch_src", lambda video_id: f"https://veev.to/e/{video_id}")

    movie = scraper.get_movie("moflix:42:the-end-of-oak-street")

    assert movie is not None
    assert [(hoster.name, hoster.url) for hoster in movie.hosters] == [
        ("Veev", "https://veev.to/e/99")
    ]


def test_movie_collects_current_video_lists_without_model_type(monkeypatch):
    scraper = _scraper(_Response({}))
    monkeypatch.setattr(
        scraper,
        "_bootstrap",
        lambda _url: {
            "loaders": {
                "titlePage": {
                    "title": {
                        "id": 42,
                        "model_type": "title",
                        "name": "Example",
                        "videos": [
                            {"id": 5, "name": "Deutsch", "quality": "1080p"},
                            {"id": 6, "name": "Deutsch", "quality": "720p"},
                        ],
                    }
                }
            }
        },
    )
    monkeypatch.setattr(scraper, "_watch_src", lambda video_id: f"https://hoster.test/e/{video_id}")

    movie = scraper.get_movie("moflix:42:example")

    assert [hoster.url for hoster in movie.hosters] == [
        "https://hoster.test/e/5",
        "https://hoster.test/e/6",
    ]


def test_episode_resolves_video_ids_without_inline_sources(monkeypatch):
    scraper = _scraper(_Response({}))
    monkeypatch.setattr(
        scraper,
        "_bootstrap",
        lambda _url: {
            "loaders": {
                "episodePage": {
                    "title": {"name": "Example Show"},
                    "episode": {"videos": [{"id": 81, "language": "Deutsch"}]},
                }
            }
        },
    )
    monkeypatch.setattr(scraper, "_watch_src", lambda video_id: f"https://hoster.test/e/{video_id}")

    movie = scraper._get_episode_movie(42, "example-show", 1, 2)

    assert movie is not None
    assert movie.hosters[0].url == "https://hoster.test/e/81"
    assert movie.hosters[0].language == "Deutsch"


def test_watch_src_rejects_non_http_player_values(monkeypatch):
    scraper = _scraper(_Response({"video": {"src": "javascript:alert(1)"}}))
    monkeypatch.setattr(scraper, "_bootstrap", lambda _url: {})

    assert scraper._watch_src(7) == ""
