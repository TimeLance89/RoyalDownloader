import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import api_discovery_router
from series_calendar_service import SeriesCalendarService, normalize_calendar_document

ROOT = Path(__file__).resolve().parents[1]


def _calendar_document():
    return {
        "2026-08-23": [{
            "date": "2026-08-23", "time": "20:15", "title": "Test Serie",
            "language": "Deutsch", "language_id": 1, "season": 2, "episode": 4,
            "released": True, "url": "/serie/test-serie/staffel-2/episode-4",
            "cover_url": "/media/images/channel/desktop/test-poster",
        }, {
            "title": "Fremdlink", "url": "https://evil.invalid/serie/test",
        }],
        "not-a-date": [],
    }


def test_calendar_service_validates_entries_and_uses_direct_cover():
    result = normalize_calendar_document(_calendar_document(), fetched_at=1234)

    assert result["ready"] is True
    assert result["total"] == 1
    assert result["available_from"] == "2026-08-23"
    entry = result["days"][0]["entries"][0]
    assert entry["base_slug"] == "serienstream:test-serie"
    assert entry["sample_slug"] == "serienstream:test-serie-s02e04"
    assert entry["cover_url"] == (
        "https://serienstream.to/media/images/channel/desktop/test-poster"
    )

    document = _calendar_document()
    document["2026-08-23"][0]["cover_url"] = (
        "https://www.serienstream.to/media/images/channel/desktop/test-poster"
    )
    canonical = normalize_calendar_document(document, fetched_at=1234)
    assert canonical["days"][0]["entries"][0]["cover_url"] == entry["cover_url"]


def test_calendar_service_persists_last_valid_snapshot(tmp_path):
    path = tmp_path / "calendar.json"
    service = SeriesCalendarService(
        path, fetcher=_calendar_document, now=lambda: 1000,
    )
    first = service.refresh()
    assert first["total"] == 1
    assert path.is_file()

    restored = SeriesCalendarService(
        path,
        fetcher=lambda: (_ for _ in ()).throw(ConnectionError("offline")),
        now=lambda: 2000,
    ).refresh()

    assert restored["ready"] is True
    assert restored["stale"] is True
    assert restored["total"] == 1
    assert restored["error"] == "offline"


def test_calendar_service_returns_terminal_failure_without_snapshot(tmp_path):
    service = SeriesCalendarService(
        tmp_path / "missing.json",
        fetcher=lambda: (_ for _ in ()).throw(TimeoutError("Zeitlimit")),
    )

    result = service.get()

    assert result["ready"] is False
    assert result["refreshing"] is False
    assert result["days"] == []
    assert result["error"] == "Zeitlimit"


def test_calendar_service_waits_for_initial_background_refresh(tmp_path):
    release = threading.Event()

    def delayed_fetch():
        release.wait(timeout=1)
        return _calendar_document()

    service = SeriesCalendarService(tmp_path / "calendar.json", fetcher=delayed_fetch)
    assert service.refresh_async() is True
    threading.Thread(target=lambda: (time.sleep(0.02), release.set()), daemon=True).start()

    result = service.get()

    assert result["ready"] is True
    assert result["refreshing"] is False
    assert result["total"] == 1


def test_calendar_api_marks_watchlist_series_as_subscribed(monkeypatch):
    payload = {
        "days": [{"date": "2026-08-23", "entries": [{
            "title": "Test", "base_slug": "serienstream:test",
        }]}],
        "total": 1,
        "provider": "serienstream",
    }
    service = SimpleNamespace(get=lambda **_kwargs: payload)
    monkeypatch.setattr(
        api_discovery_router,
        "provider_priority",
        lambda _kind: (_ for _ in ()).throw(AssertionError("provider setting read")),
    )
    monkeypatch.setattr(api_discovery_router, "get_series_calendar_service", lambda: service)
    monkeypatch.setattr(api_discovery_router, "state", SimpleNamespace(
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
    assert "api.seriesCalendar(force)" in screen
    assert "data-calendar-retry" in screen
    assert 'switchTab("serien", { autoLoad: false })' in screen
    assert "loadSeries({" in screen
    assert 'fetchpriority="high"' in screen
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_calendar_uses_an_independent_provider_session_and_client_timeout():
    router = (ROOT / "api_discovery_router.py").read_text(encoding="utf-8")
    service = (ROOT / "series_calendar_service.py").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")

    assert "get_series_calendar_service().get(force=refresh)" in router
    assert "series_calendar_snapshot.json" in service
    assert "os.replace(temporary, self.snapshot_path)" in service
    assert "get_series_calendar_service().refresh_async()" in server
    assert 'controller.abort(), 15_000' in api
    assert 'opts.signal = signal' in api


def test_calendar_has_a_terminal_state_and_no_browser_provider_request():
    screen = (ROOT / "web" / "screens" / "series-calendar.js").read_text(encoding="utf-8")

    assert "SERIES_CALENDAR_WATCHDOG_MS = 16_000" in screen
    assert "calendarNextRequestId()" in screen
    assert "calendarCheckHardDeadline" in screen
    assert "calendarInstallSafetyNet()" in screen
    assert "state.calendar.phase = \"error\"" in screen
    assert "https://serienstream.to/api/calendar" not in screen
    assert "SERIES_CALENDAR_CACHE_MAX_AGE" in screen
    assert "calendarRestoreSnapshot()" in screen
    assert "calendarStoreSnapshot(payload)" in screen
    assert "Sendeplan wird geladen" not in screen
    assert ".calendar-status[hidden]" in (ROOT / "web" / "styles" / "series-calendar.css").read_text(encoding="utf-8")


def test_series_catalog_checks_jellyfin_before_artwork_hydration():
    screen = (ROOT / "web" / "screens" / "series.js").read_text(encoding="utf-8")
    body = screen.split("function applySeriesResults", 1)[1].split(
        "function clearSeriesSearchContext", 1
    )[0]

    assert body.index("refreshCatalogJellyfinStatus") < body.index("hydrateHomeSeriesArtwork")
    assert "for (const result of state.series.results) updateSeriesResultCard" in body
