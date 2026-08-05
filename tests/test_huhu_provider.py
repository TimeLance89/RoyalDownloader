from types import SimpleNamespace

import pytest

import config
import server
from providers.huhu import HuhuScraper
from providers.models import FilmpalastMovie, HosterInfo
from session_manager import ProviderBlockedError


class Response:
    def __init__(self, data, status=200, text=""):
        self._data = data
        self.status_code = status
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def scraper_with(*responses):
    scraper = HuhuScraper()
    pending = iter(responses)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return next(pending)

    scraper.session = SimpleNamespace(post=post)
    return scraper, calls


def test_huhu_search_and_series_use_tmdb_id_and_exact_episode_numbers():
    catalog = Response({"items": [{
        "type": "series",
        "ids": {"tmdb_id": "123"},
        "name": "Exact Show",
        "releaseDate": "2024-01-02",
        "images": {"poster": "https://image.invalid/poster.jpg"},
    }]})
    item = Response({
        "type": "series",
        "ids": {"tmdb_id": "123"},
        "name": "Exact Show",
        "episodes": [
            {"season": 2, "episode": 5, "name": "Five"},
            {"season": 2, "episode": 4, "name": "Four"},
            {"season": 3, "episode": 1, "name": "Next"},
        ],
        "images": {},
    })
    scraper, calls = scraper_with(catalog, item)

    results = scraper.search_series("Exact Show")
    series = scraper.get_series(results[0].sample_slug)

    assert results[0].title == "Exact Show  [Huhu]"
    assert results[0].base_slug == "huhu:123:exact-show"
    assert [(ep.season, ep.episode) for ep in series.seasons[2]] == [(2, 4), (2, 5)]
    assert series.seasons[2][0].slug == "huhu:123:exact-show-s02e04"
    assert calls[0][1]["json"]["catalogId"] == "tmdb.series"
    assert calls[1][1]["json"]["ids"] == {"tmdb_id": "123"}


def test_huhu_movie_search_and_source_use_exact_tmdb_id():
    catalog = Response({"items": [{
        "type": "movie",
        "ids": {"tmdb_id": "550"},
        "name": "Fight Club",
        "releaseDate": "1999-10-15",
        "images": {"poster": "https://image.invalid/fight-club.jpg"},
    }]})
    sources = Response([
        {"type": "url", "url": "https://voe.sx/e/one", "languages": ["de"]},
        {"type": "url", "url": "https://dood.to/d/two", "languages": ["en"]},
    ])
    scraper, calls = scraper_with(catalog, sources)

    results = scraper.search("Fight Club")
    movie = scraper.get_movie(results[0].slug)

    assert results[0].title == "Fight Club  [Huhu]"
    assert results[0].slug == "huhu-movie:550:fight-club"
    assert results[0].year == "1999"
    assert movie.title == "Fight Club"
    assert [hoster.name for hoster in movie.hosters] == ["VOE"]
    assert calls[0][1]["json"]["catalogId"] == "tmdb.movie"
    assert calls[1][1]["json"] == {
        "language": "de",
        "region": "DE",
        "type": "movie",
        "ids": {"tmdb_id": "550"},
        "name": "fight-club",
    }


def test_huhu_episode_sources_keep_only_german_direct_hoster_urls():
    sources = Response([
        {"type": "url", "url": "https://voe.sx/e/one", "languages": ["de"], "tag": "1080p"},
        {"type": "url", "url": "https://dood.to/d/two", "languages": ["de"]},
        {"type": "url", "url": "https://filemoon.to/e/three", "languages": ["en"]},
        {"type": "url", "url": "https://bs.to/serie/x/1/1", "languages": ["de"]},
        {"type": "url", "url": "https://voe.sx/e/one", "languages": ["de"]},
    ])
    scraper, calls = scraper_with(sources)

    movie = scraper.get_movie("huhu:123:exact-show-s02e04")

    assert [hoster.name for hoster in movie.hosters] == ["VOE", "Doodstream"]
    assert [hoster.language for hoster in movie.hosters] == ["de", "de"]
    payload = calls[0][1]["json"]
    assert payload["ids"] == {"tmdb_id": "123"}
    assert payload["episode"] == {"ids": {}, "season": 2, "episode": 4}


@pytest.mark.parametrize("status, text, reason", [
    (429, "too many requests", "rate_limit"),
    (403, "cloudflare turnstile", "cloudflare_gate"),
])
def test_huhu_protection_responses_are_respected(status, text, reason):
    scraper, _calls = scraper_with(Response({}, status=status, text=text))
    with pytest.raises(ProviderBlockedError) as error:
        scraper.search_series("Exact Show")
    assert error.value.reason == reason


def test_existing_installation_enables_huhu_once_and_keeps_it_configurable(monkeypatch):
    writes = []
    monkeypatch.setattr(config, "_update_all", lambda values: writes.append(values) or True)
    old = {
        "series_provider_priority": "serienstream,moflix,megakino,filmpalast",
        "series_provider_enabled": "serienstream,moflix,megakino,filmpalast",
    }

    migrated = config._migrate_provider_catalog(old)

    assert migrated["series_provider_priority"].split(",")[:3] == [
        "serienstream", "huhu", "moflix",
    ]
    assert "huhu" in migrated["series_provider_enabled"].split(",")
    assert len(writes) == 1

    # Nach der Migration darf ein Benutzer Huhu wieder deaktivieren; der
    # Revisionsmarker verhindert eine erneute Zwangsaktivierung.
    migrated["series_provider_enabled"] = "serienstream,moflix"
    assert config._migrate_provider_catalog(migrated)["series_provider_enabled"] == (
        "serienstream,moflix"
    )
    assert len(writes) == 1


def test_movie_provider_migration_puts_filmpalast_then_huhu_and_filmfrei_last(
    monkeypatch,
):
    writes = []
    monkeypatch.setattr(config, "_update_all", lambda values: writes.append(values) or True)
    old = {
        "provider_catalog_revision": "2",
        "movie_provider_priority": (
            "huhu,filmpalast,megakino,moflix,einschalten,kinox,"
            "kinoger,xcine,sflix,ridomovies"
        ),
        "movie_provider_enabled": (
            "filmfrei24,filmpalast,megakino,moflix,einschalten,kinox,"
            "kinoger,xcine,sflix,ridomovies"
        ),
    }

    migrated = config._migrate_provider_catalog(old)
    order = migrated["movie_provider_priority"].split(",")

    assert order[:2] == ["filmpalast", "huhu"]
    assert order[2] == "filmo"
    assert order[-1] == "filmfrei24"
    assert "huhu" in migrated["movie_provider_enabled"].split(",")
    assert "filmo" in migrated["movie_provider_enabled"].split(",")
    assert writes == [{
        "provider_catalog_revision": "4",
        "movie_provider_priority": migrated["movie_provider_priority"],
        "movie_provider_enabled": migrated["movie_provider_enabled"],
    }]


def test_filmo_migration_preserves_revision_three_user_choices(monkeypatch):
    writes = []
    monkeypatch.setattr(config, "_update_all", lambda values: writes.append(values) or True)
    old = {
        "provider_catalog_revision": "3",
        "movie_provider_priority": "megakino,filmpalast,filmfrei24",
        "movie_provider_enabled": "megakino,filmpalast",
    }

    migrated = config._migrate_provider_catalog(old)

    assert migrated["movie_provider_priority"].split(",")[:2] == ["megakino", "filmpalast"]
    assert "filmo" in migrated["movie_provider_priority"].split(",")
    assert "filmo" in migrated["movie_provider_enabled"].split(",")
    assert "huhu" not in migrated["movie_provider_enabled"].split(",")
    assert writes[0]["provider_catalog_revision"] == "4"


def test_new_install_movie_defaults_start_with_filmpalast_then_huhu():
    assert config.MOVIE_PROVIDER_DEFAULTS[:2] == ("filmpalast", "huhu")
    assert config.MOVIE_PROVIDER_DEFAULTS[2] == "filmo"
    assert config.MOVIE_PROVIDER_DEFAULTS[-1] == "filmfrei24"


def test_server_routes_huhu_movie_slug_to_huhu_adapter(monkeypatch):
    movie = FilmpalastMovie(
        title="Fight Club",
        url="https://huhu.to/item?type=movie&id=550",
        hosters=[HosterInfo("VOE", "https://voe.sx/e/one")],
    )
    calls = []
    scraper = SimpleNamespace(
        get_movie=lambda slug: calls.append(slug) or movie,
    )
    monkeypatch.setattr(server, "get_huhu_scraper", lambda: scraper)

    loaded = server.load_movie_for_slug("huhu-movie:550:fight-club")

    assert calls == ["huhu-movie:550:fight-club"]
    assert loaded.provider == "huhu"
    assert loaded.content_language == "de"
