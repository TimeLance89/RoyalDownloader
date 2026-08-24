import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import api_discovery_router
from providers.serienstream import SerienstreamScraper

ROOT = Path(__file__).resolve().parents[1]


class _CalendarSession:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def get(self, url, fast=False):
        self.calls.append((url, fast))
        return json.dumps(self.document)


class _JsonCalendarSession:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.document


def test_serienstream_calendar_validates_entries_and_uses_direct_cover():
    session = _CalendarSession({
        "2026-08-23": [{
            "date": "2026-08-23", "time": "20:15", "title": "Test Serie",
            "language": "Deutsch", "language_id": 1, "season": 2, "episode": 4,
            "released": True, "url": "/serie/test-serie/staffel-2/episode-4",
            "cover_url": "/media/images/channel/desktop/test-poster",
        }, {
            "title": "Fremdlink", "url": "https://evil.invalid/serie/test",
        }],
        "not-a-date": [],
    })
    scraper = SerienstreamScraper(session=session)

    result = scraper.series_calendar()

    assert result["total"] == 1
    assert result["available_from"] == "2026-08-23"
    entry = result["days"][0]["entries"][0]
    assert entry["base_slug"] == "serienstream:test-serie"
    assert entry["sample_slug"] == "serienstream:test-serie-s02e04"
    assert entry["cover_url"] == (
        "https://serienstream.to/media/images/channel/desktop/test-poster"
    )
    assert session.calls == [("https://serienstream.to/api/calendar", True)]


def test_serienstream_calendar_uses_last_valid_snapshot_on_provider_failure():
    session = _CalendarSession({"2026-08-23": []})
    scraper = SerienstreamScraper(session=session)
    first = scraper.series_calendar(max_age=0)
    assert first["total"] == 0
    session.get = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("down"))

    result = scraper.series_calendar(max_age=0)

    assert result["stale"] is True
    assert result["days"] == [{"date": "2026-08-23", "entries": []}]


def test_serienstream_calendar_uses_short_json_endpoint_with_page_referer():
    session = _JsonCalendarSession({"2026-08-23": []})

    result = SerienstreamScraper(session=session).series_calendar(max_age=0)

    assert result["days"] == [{"date": "2026-08-23", "entries": []}]
    assert session.calls == [(
        "https://serienstream.to/api/calendar",
        {
            "referer": "https://serienstream.to/serienkalender",
            "timeout": 8,
        },
    )]


def test_calendar_api_marks_watchlist_series_as_subscribed(monkeypatch):
    payload = {
        "days": [{"date": "2026-08-23", "entries": [{
            "title": "Test", "base_slug": "serienstream:test",
        }]}],
        "total": 1,
        "provider": "serienstream",
    }
    scraper = SimpleNamespace(series_calendar=lambda: payload)
    monkeypatch.setattr(
        api_discovery_router,
        "provider_priority",
        lambda _kind: (_ for _ in ()).throw(AssertionError("provider setting read")),
    )
    monkeypatch.setattr(api_discovery_router, "get_sto_calendar_scraper", lambda: scraper)
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(
        sto_calendar_lock=threading.Lock(),
        watchlist=[{"base_slug": "serienstream:test"}],
    ))

    result = asyncio.run(api_discovery_router.api_series_calendar())

    assert result["disabled"] is False
    assert result["days"][0]["entries"][0]["subscribed"] is True


def test_dedicated_calendar_ui_has_navigation_filters_and_direct_series_flow():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    screen = (ROOT / "web" / "screens" / "series-calendar.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "styles" / "series-calendar.css").read_text(encoding="utf-8")

    assert index.count('data-tab="kalender"') == 2
    for contract in (
        'id="tab-kalender"', 'id="calendar-week-strip"',
        'id="calendar-search"', 'id="calendar-subscribed"',
        'class="calendar-ledger"', 'class="calendar-legend"',
    ):
        assert contract in index
    assert "api.seriesCalendar()" in screen
    assert "data-calendar-retry" in screen
    assert 'switchTab("serien", { autoLoad: false })' in screen
    assert "loadSeries({" in screen
    assert 'fetchpriority="high"' in screen
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_calendar_uses_an_independent_provider_session_and_client_timeout():
    router = (ROOT / "api_discovery_router.py").read_text(encoding="utf-8")
    clients = (ROOT / "application_services" / "media_clients.py").read_text(encoding="utf-8")
    api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")

    assert "with state.sto_calendar_lock" in router
    assert "get_sto_calendar_scraper().series_calendar()" in router
    assert "def get_sto_calendar_scraper()" in clients
    assert 'controller.abort(), 20_000' in api
    assert 'opts.signal = signal' in api


def test_calendar_has_a_bounded_direct_provider_fallback():
    screen = (ROOT / "web" / "screens" / "series-calendar.js").read_text(encoding="utf-8")

    assert "function calendarNormalizeProviderPayload" in screen
    assert "async function calendarDirectProviderLoad" in screen
    assert 'fetch("https://serienstream.to/api/calendar"' in screen
    assert "controller.abort(), 10_000" in screen
    assert "calendarLoadPayload()" in screen
    assert "Der lokale Kalenderdienst antwortet nicht." in screen
    assert "SERIES_CALENDAR_CACHE_MAX_AGE" in screen
    assert "calendarRestoreSnapshot()" in screen
    assert "calendarStoreSnapshot(payload)" in screen
    assert "void seriesCalendarLoad();" in screen


def test_series_catalog_checks_jellyfin_before_artwork_hydration():
    screen = (ROOT / "web" / "screens" / "series.js").read_text(encoding="utf-8")
    body = screen.split("function applySeriesResults", 1)[1].split(
        "function clearSeriesSearchContext", 1
    )[0]

    assert body.index("refreshCatalogJellyfinStatus") < body.index("hydrateHomeSeriesArtwork")
    assert "for (const result of state.series.results) updateSeriesResultCard" in body
