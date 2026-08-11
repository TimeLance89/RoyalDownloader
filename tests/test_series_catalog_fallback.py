import server


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
