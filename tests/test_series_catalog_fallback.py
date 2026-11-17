import server
from application_services import series_catalog


def test_new_series_prioritizes_recent_feeds_and_keeps_preferred_source(monkeypatch):
    def row(provider, title):
        return server.FilmpalastSeriesResult(title, f"{provider}:{title}", "", "")

    pages = {
        ("huhu", 1): [row("huhu", "Shared"), row("huhu", "Catalog")],
        ("serienstream", 1): [row("serienstream", "Shared"), row("serienstream", "Recent")],
        ("filmpalast", 1): [row("filmpalast", "Updated")],
    }
    monkeypatch.setattr(server, "provider_priority", lambda _: ["filmpalast", "huhu", "serienstream"])
    monkeypatch.setattr(server, "provider_order", lambda _: ["huhu", "serienstream", "filmpalast"])
    monkeypatch.setattr(server, "_load_series_provider_pages",
                        lambda _mode, _letter, requests, *_: {key: pages.get(key, []) for key in requests})
    monkeypatch.setattr(server, "_series_provider_is_paginated", lambda *_: False)
    monkeypatch.setattr(series_catalog.series_catalog_cache, "stabilize_catalog",
                        lambda _key, entries, *_: entries)

    entries = series_catalog.series_catalog_page("new")["entries"]

    assert [entry.result.title for entry in entries] == ["Shared", "Recent", "Updated", "Catalog"]
    assert entries[0].provider == "huhu"
    assert entries[0].providers == ("huhu", "serienstream")


def test_trending_series_fall_back_when_serienstream_is_unavailable(monkeypatch):
    fallback = server.FilmpalastSeriesResult(
        title="Fallback-Serie",
        base_slug="fallback-serie",
        sample_slug="fallback-serie/staffel-1/episode-1",
        sample_url="https://example.invalid/fallback-serie",
    )
    calls = []

    def load_pages(mode, _letter, requests, _budget, *_timing):
        calls.append((mode, tuple(requests)))
        if mode == "trending":
            return {("serienstream", 1): []}
        return {("huhu", 1): [fallback]}

    monkeypatch.setattr(server, "provider_priority", lambda _media_type: ["serienstream", "huhu"])
    monkeypatch.setattr(server, "_load_series_provider_pages", load_pages)
    monkeypatch.setattr(server, "_series_provider_is_paginated", lambda _provider, _mode: False)

    result = server._series_catalog_page_locked("trending", 1)

    assert [entry.result.title for entry in result["entries"]] == ["Fallback-Serie"]
    assert calls == [
        ("trending", (("serienstream", 1),)),
        ("discover", (("huhu", 1),)),
    ]
