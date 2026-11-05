from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import RLock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import application_services.daily_top as charts
from application_services.chart_history import ALGORITHM, ChartHistory, chart_view
from bs4 import BeautifulSoup
from providers.ridomovies import RidomoviesScraper
from providers.sflix import SflixScraper

DAY = date(2026, 11, 5)


def movie(title, year="2025", tmdb_id=None):
    return {"title": title, "year": year, "tmdb_id": tmdb_id,
            "slug": title.lower().replace(" ", "-"), "cover_url": "/poster.jpg"}


def candidate(title, rank=1, *, provider="megakino", kind="movie", signal="views_rank", year="2025"):
    grouped = {}
    item = movie(title, year)
    if kind == "series":
        item["base_slug"] = item.pop("slug")
    charts._provider_rows(grouped, kind, provider, [None] * (rank - 1) + [item], signal)
    return next(iter(grouped.values()))


def score(item):
    return charts._score_candidate(item)


def snapshot(day, *candidates, observed=("megakino",)):
    return {
        "algorithm_version": ALGORITHM, "period": day.isoformat(), "generated_at": 123,
        "sources": {"movie": {source: {"type": "views_rank", "observed": True} for source in observed}},
        "candidates": [dict(score(item), global_rank=i) for i, item in enumerate(candidates, 1)],
    }


def persist(store, day, *candidates, **options):
    token = store.claim("scope", day)
    assert token
    store.save("scope", day, token, snapshot(day, *candidates, **options))


def by_title(payload):
    return {item["item"]["title"]: item for item in payload["candidates"]}


def test_provider_signal_audit():
    assert charts.MOVIE_SIGNALS == {
        "megakino": "views_rank", "sflix": "trending_rank",
        "kinoking": "editorial_top", "filmpalast": "editorial_top", "ridomovies": "editorial_top",
        "huhu": "popularity_rank", "filmo": "rating_rank", "filmfrei24": "rating_rank", "xcine": "rating_rank",
        "kinoger": "recent_uploads", "kinox": "recent_uploads", "einschalten": "recent_uploads",
    }
    assert charts.SERIES_SIGNALS == {
        "serienstream": "views_rank", "huhu": "popularity_rank",
        "filmpalast": "recent_uploads", "megakino": "recent_uploads",
        "ridomovies": "recent_uploads", "xcine": "recent_uploads",
    }
    assert "moflix" not in charts.MOVIE_SIGNALS


@pytest.mark.parametrize("scraper", [SflixScraper, RidomoviesScraper])
def test_missing_ranked_sections_cannot_turn_arbitrary_cards_into_signals(monkeypatch, scraper):
    provider = object.__new__(scraper)
    monkeypatch.setattr(provider, "_get_soup", lambda _: BeautifulSoup("<main>Catalog</main>", "html.parser"))
    monkeypatch.setattr(provider, "_parse_cards", lambda _: pytest.fail("general catalog parsed"))
    assert provider.list_movies("chart-top") == []


@pytest.mark.parametrize("signal", ["recent_uploads", "unknown", "rating_rank"])
def test_catalog_or_rating_positions_do_not_create_popularity(signal):
    item = score(candidate("Catalog only", signal=signal))
    assert item["components"]["popularity"] == 0
    assert item["availability_providers"] == ["megakino"]
    assert item["provider_signals"]["megakino"]["type"] == signal


def test_score_uses_strongest_signal_without_source_count_bonus_or_rating_double_count():
    leader = candidate("Signal lead")
    reference = score(leader)
    leader["provider_signals"].update({
        f"mirror-{i}": {"rank": 1, "type": "views_rank", "source": "megakino"} for i in range(10)
    })
    assert score(leader)["score"] == reference["score"]
    assert score(leader)["confidence"] == reference["confidence"]
    leader["item"].update(rating=8, vote_count=5000)
    reference = score(leader)
    leader["provider_signals"]["filmfrei24"] = {"type": "rating_rank", "rank": 1, "source": "filmfrei24"}
    assert score(leader)["components"]["quality"] == reference["components"]["quality"]
    assert charts._rating_confidence_score(9.5, 6) < charts._rating_confidence_score(8.1, 25_000)


def test_huhu_and_tmdb_have_one_signal_group():
    item = candidate("Same", provider="huhu", signal="popularity_rank")
    item["tmdb_trend_rank"] = 1
    result = score(item)
    assert result["components"]["popularity"] == 100
    assert result["popularity_observations"] == {"tmdb": {"provider": "tmdb", "rank": 1, "value": 100.0}}


def test_identical_order_is_not_independent_corroboration(monkeypatch):
    providers = ["megakino", "sflix"]
    rows = [movie(f"Film {index}") for index in range(5)]
    backend = {
        "_load_movie_provider_pages": lambda *_args, **_kwargs: {(key, 1): rows for key in providers},
        "state": SimpleNamespace(provider_health=SimpleNamespace(request_allowed=lambda _: True)),
    }
    monkeypatch.setattr(charts, "backend_value", backend.__getitem__)
    grouped = {}
    charts._collect("movie", providers, grouped, None, 1)
    result = score(next(iter(grouped.values())))
    assert len(result["provider_signals"]) == 2
    assert len(result["popularity_observations"]) == 1
    assert result["confidence"] == "medium"


def test_variant_merge_preserves_best_signal_and_keeps_remakes_separate():
    grouped = {}
    for provider, row in [
        ("megakino", movie("Der Film [MegaKino]", tmdb_id=11)),
        ("kinoking", movie("The Film *Subbed*", tmdb_id=11)),
        ("filmpalast", movie("Der Film", "1999", 12)),
        ("sflix", movie("Der Film")),
    ]:
        charts._provider_rows(grouped, "movie", provider, [row], "views_rank")
    merged = charts._merge_candidates(grouped.values())
    assert {entry["identity"] for entry in merged} == {"movie:tmdb:11", "movie:tmdb:12"}
    assert merged[0]["item"]["title"] == "Der Film"
    assert score(merged[0])["provider_ranks"] == {"megakino": 1, "kinoking": 1, "sflix": 1}
    assert charts._normalise_title("東京") != charts._normalise_title("大阪")


def test_tmdb_match_checks_year_explicit_id_and_title_ambiguity():
    original = {"tmdb_id": 11, "title": "Der Film", "original_title": "The Film", "year": "2025"}
    remake = dict(original, tmdb_id=12, year="1999")
    assert charts._match_tmdb(movie("The Film"), [remake, original]) == original
    assert charts._match_tmdb(movie("Der Film", ""), [original]) is None
    assert charts._match_tmdb(movie("Der Film", ""), [original, remake], allow_yearless=True) is None
    assert charts._match_tmdb(movie("Der Film", "1980"), [original]) is None
    assert charts._match_tmdb(movie("Der Film", "2025", 12), [original, remake]) == remake


def test_soft_diversity_is_deterministic_and_requires_three_relevant_titles():
    movies = [score(candidate(f"Movie {index}")) for index in range(12)]
    series = [score(candidate(f"Series {index}", rank=2, kind="series")) for index in range(3)]
    first = charts._apply_diversity(movies + series)
    second = charts._apply_diversity(list(reversed(movies + series)))
    assert first == second
    assert sum(item["kind"] == "series" for item in first[:10]) == 3
    assert all(item["kind"] == "movie" for item in charts._apply_diversity(movies + series[:2])[:10])
    assert [item["global_rank"] for item in first] == list(range(1, len(first) + 1))


def test_durable_history_and_day_by_day_changes(tmp_path):
    path = tmp_path / "charts.sqlite3"
    store = ChartHistory(path)
    persist(store, DAY - timedelta(days=2), candidate("Returning"), candidate("Stable"))
    persist(store, DAY - timedelta(days=1), candidate("Down"), candidate("Stable"), candidate("Riser", 15))
    persist(store, DAY, candidate("Riser"), candidate("Stable"), candidate("Down"),
            candidate("Fresh"), candidate("Returning"))
    reopened = ChartHistory(path)
    data = reopened.read("scope", DAY)
    result = by_title(chart_view(data, DAY, "today", "mixed", ""))
    assert {key: item["movement"]["direction"] for key, item in result.items()} == {
        "Riser": "up", "Stable": "flat", "Down": "down", "Fresh": "new", "Returning": "returning",
    }
    assert result["Riser"]["movement"] == {"direction": "up", "delta": 2, "previous_rank": 3}
    assert result["Riser"]["history"]["days_charted"] == 2
    assert result["Riser"]["history"]["best_rank"] == 1
    assert result["Riser"]["history"]["streak"] == 2
    assert len(result["Riser"]["history"]["last_7"]) == 7
    assert len(result["Riser"]["history"]["last_30"]) == 30
    assert list(by_title(chart_view(data, DAY, "breakouts", "mixed", ""))) == ["Riser"]
    assert list(by_title(chart_view(data, DAY, "new", "mixed", ""))) == ["Fresh"]
    assert list(by_title(chart_view(data, DAY, "week", "mixed", "")))[0] == "Stable"
    assert chart_view(data, DAY, "month", "movie", "")["recorded_days"] == 3
    assert chart_view(data, DAY, "today", "series", "")["candidates"] == []
    assert reopened.claim("scope", DAY) is None
    assert reopened.read("other-scope", DAY) == ([], None, {})


def test_first_snapshot_gap_and_source_outage_do_not_invent_movements(tmp_path):
    store = ChartHistory(tmp_path / "charts.sqlite3")
    old = DAY - timedelta(days=1)
    persist(store, old, candidate("Old", 16))
    first = store.read("scope", old)
    assert chart_view(first, old, "week", "mixed", "")["empty_reason"] == "insufficient_history"
    assert chart_view(first, old, "today", "mixed", "")["candidates"][0]["movement"]["direction"] == "unknown"
    persist(store, DAY, candidate("Old", provider="sflix"), candidate("New", provider="sflix"), observed=("sflix",))
    data = store.read("scope", DAY)
    assert not chart_view(data, DAY, "breakouts", "mixed", "")["candidates"]
    assert not chart_view(data, DAY, "new", "mixed", "")["candidates"]
    assert chart_view(store.read("scope", DAY + timedelta(days=1)), DAY + timedelta(days=1),
                      "today", "mixed", "")["empty_reason"] == "no_snapshot"


def test_history_resolves_confirmed_identity_upgrade(tmp_path):
    store = ChartHistory(tmp_path / "charts.sqlite3")
    first = candidate("Der Film", 16)
    latest = candidate("Der Film")
    latest["identity"] = "movie:tmdb:123"
    persist(store, DAY - timedelta(days=1), first)
    persist(store, DAY, latest)
    result = chart_view(store.read("scope", DAY), DAY, "today", "mixed", "")["candidates"][0]
    assert result["movement"]["direction"] == "flat"
    assert result["history"]["days_charted"] == 2
    assert result["identity"] == "movie:tmdb:123"


def test_retention_preserves_known_returning_identity_for_active_scope(tmp_path):
    store = ChartHistory(tmp_path / "charts.sqlite3")
    persist(store, DAY - timedelta(days=91), candidate("Old"))
    persist(store, DAY - timedelta(days=30), candidate("Bridge"))
    persist(store, DAY - timedelta(days=1), candidate("Current"))
    persist(store, DAY, candidate("Old"), candidate("Fresh"))
    data = store.read("scope", DAY)
    assert len(data[0]) == 3
    result = by_title(chart_view(data, DAY, "today", "mixed", ""))
    assert result["Old"]["movement"]["direction"] == "returning"
    assert result["Fresh"]["movement"]["direction"] == "new"


def test_parallel_database_claims_are_single_writer_and_failed_attempts_back_off(tmp_path):
    path = tmp_path / "charts.sqlite3"
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: ChartHistory(path).claim("scope", DAY), range(12)))
    assert sum(token is not None for token in tokens) == 1
    store = ChartHistory(path)
    store.save("scope", DAY, "wrong-token", snapshot(DAY, candidate("Unclaimed")))
    assert store.read("scope", DAY)[0] == []
    assert store.claim("scope", DAY) is None


def test_api_builds_once_per_day_and_configuration_and_never_backfills(monkeypatch, tmp_path):
    config = {"movies": ["megakino", "kinoger"], "series": ["serienstream"], "day": DAY}
    calls = []
    state = SimpleNamespace(
        provider_priority_lock=RLock(), content_languages=["de"],
        provider_health=SimpleNamespace(request_allowed=lambda provider: provider != "serienstream"),
    )

    def movie_pages(mode, _genre, requests, _budget, *, fresh_since):
        calls.append((mode, requests, fresh_since))
        return {(provider, 1): [movie("Measured" if provider == "megakino" else "Only upload")]
                for provider, _ in requests}

    backend = {
        "provider_priority": lambda kind, *, configured_only: list(config[kind]),
        "get_tmdb_client": lambda: None,
        "state": state, "_load_movie_provider_pages": movie_pages,
        "_load_series_provider_pages": lambda *args, **kwargs: pytest.fail("cooldown ignored"),
    }
    monkeypatch.setattr(charts, "chart_day", lambda: config["day"])
    monkeypatch.setattr(charts, "config_path", lambda: tmp_path / "settings.ini")
    monkeypatch.setattr(charts, "backend_value", backend.__getitem__)
    monkeypatch.setattr(charts, "_build", None)
    app = FastAPI()
    app.include_router(charts.discovery_router)

    with TestClient(app) as client:
        response = client.get("/api/v3/royal-charts", params={"period": (DAY - timedelta(days=1)).isoformat()})
        assert response.json()["candidates"] == []
        assert not calls
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(client.get, ["/api/v3/royal-charts"] * 4))
        first = responses[0].json()
        assert all(response.json() == first for response in responses)
        assert responses[0].headers["cache-control"] == "private, no-store"
        assert [item["item"]["title"] for item in first["candidates"]] == ["Measured"]
        assert first["timezone"] == "UTC"
        assert first["sources"]["series"]["serienstream"]["observed"] is False
        assert len(calls) == 2
        assert client.get("/api/daily-top").json()["version"] == 2
        assert client.get("/api/v1/daily-top").json()["candidates"] == first["candidates"]
        assert client.get("/api/v3/royal-charts?mode=wrong").status_code == 422
        assert len(calls) == 2
        config["movies"] = ["kinoger"]
        changed = client.get("/api/v3/royal-charts").json()
        assert changed["scope"] != first["scope"]
        assert changed["candidates"] == []
        config["movies"] = ["megakino", "kinoger"]
        config["day"] += timedelta(days=1)
        tomorrow = client.get("/api/v3/royal-charts?mode=week").json()
        assert tomorrow["recorded_days"] == 2
        assert calls[-1][2] - calls[0][2] == 86400


def test_empty_and_malformed_external_sources_keep_valid_signal(monkeypatch):
    def load_pages(mode, *_args, **_kwargs):
        if mode == "discover":
            raise OSError("fixture offline")
        return {("megakino", 1): [False, {}, movie("Measured")]}
    backend = {
        "_load_movie_provider_pages": load_pages, "_load_series_provider_pages": load_pages,
        "state": SimpleNamespace(provider_health=SimpleNamespace(request_allowed=lambda _: True)),
    }
    monkeypatch.setattr(charts, "backend_value", backend.__getitem__)
    client = SimpleNamespace(configured=True, _request=lambda *_: {"results": 42}, language="de-DE")
    result = charts._build_daily_top(DAY, ["megakino"], ["moflix"], client)
    assert [item["item"]["title"] for item in result["candidates"]] == ["Measured"]
    assert result["candidates"][0]["provider_ranks"]["megakino"] == 3
    assert result["sources"]["movie"]["tmdb"]["observed"] is False
