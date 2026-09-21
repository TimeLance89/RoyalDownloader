from pathlib import Path

import pytest

import server
from providers.models import FilmpalastSeriesResult
from providers.series_migrations import (
    canonical_identity_for_source,
    series_search_identity,
)


CANONICAL = "monster-2022"
ED_GEIN = "monster-die-geschichte-von-ed-gein"


@pytest.mark.parametrize(
    "query",
    [
        "Monster",
        "Monster (2022)",
        "monster-2022",
        "serienstream:monster-2022",
        "Monster: Die Geschichte von Ed Gein",
        "Dahmer - Monster: Die Geschichte von Jeffrey Dahmer",
    ],
)
def test_monster_search_aliases_resolve_provider_canonical_identity(query):
    identity = series_search_identity(query)

    assert identity is not None
    assert identity.provider == "serienstream"
    assert identity.canonical_slug == CANONICAL
    assert identity.title == "Monster"
    assert identity.year == "2022"
    assert identity.metadata_policy == "provider_authoritative"


def test_canonical_identity_is_recognized_from_current_provider_source():
    identity = canonical_identity_for_source(f"serienstream:{CANONICAL}")

    assert identity is not None
    assert identity.canonical_slug == CANONICAL


def test_slug_search_injects_navigable_canonical_provider_result(monkeypatch):
    monkeypatch.setattr(
        server,
        "provider_priority",
        lambda kind: ["serienstream"] if kind == "series" else [],
    )
    monkeypatch.setattr(server, "_search_series_for_provider", lambda *_args: [])

    catalog = server.series_search_catalog("monster-2022")

    assert catalog["entries"]
    entry = catalog["entries"][0]
    assert entry.provider == "serienstream"
    assert entry.result.base_slug == f"serienstream:{CANONICAL}"
    assert entry.result.sample_slug == f"serienstream:{CANONICAL}"
    assert entry.result.sample_url == f"https://serienstream.to/serie/{CANONICAL}"
    assert entry.result.title.startswith("Monster")
    assert entry.result.year == "2022"

    payload = server._series_entry_to_dict(entry)
    assert payload["metadata_policy"] == "provider_authoritative"
    assert payload["canonical_series_source"] == f"serienstream:{CANONICAL}"


def test_direct_slug_search_does_not_leak_fuzzy_other_provider_hits(monkeypatch):
    calls = []

    def search(provider, query):
        calls.append((provider, query))
        if provider == "serienstream":
            return [FilmpalastSeriesResult(
                title="Monster  [S.to]",
                base_slug=f"serienstream:{CANONICAL}",
                sample_slug=f"serienstream:{CANONICAL}",
                sample_url=f"https://serienstream.to/serie/{CANONICAL}",
                cover_url="https://img.example/monster.jpg",
            )]
        return [FilmpalastSeriesResult(
            title="Monarch: Legacy of Monsters",
            base_slug="huhu:monarch",
            sample_slug="huhu:monarch",
            sample_url="https://example.invalid/monarch",
        )]

    monkeypatch.setattr(
        server,
        "provider_priority",
        lambda kind: ["serienstream", "huhu"] if kind == "series" else [],
    )
    monkeypatch.setattr(server, "_search_series_for_provider", search)

    catalog = server.series_search_catalog("monster-2022")

    assert calls == [("serienstream", "Monster")]
    assert len(catalog["entries"]) == 1
    assert catalog["entries"][0].provider == "serienstream"
    assert catalog["entries"][0].result.base_slug == f"serienstream:{CANONICAL}"
    assert catalog["entries"][0].result.cover_url == "https://img.example/monster.jpg"


def test_legacy_provider_search_hit_collapses_to_current_monster_series(monkeypatch):
    legacy = FilmpalastSeriesResult(
        title="Monster: Die Geschichte von Ed Gein  [S.to]",
        base_slug=f"serienstream:{ED_GEIN}",
        sample_slug=f"serienstream:{ED_GEIN}",
        sample_url=f"https://serienstream.to/serie/{ED_GEIN}",
        year="2025",
    )
    monkeypatch.setattr(
        server,
        "provider_priority",
        lambda kind: ["serienstream"] if kind == "series" else [],
    )
    monkeypatch.setattr(server, "_search_series_for_provider", lambda *_args: [legacy])

    catalog = server.series_search_catalog("Monster")

    assert catalog["entries"]
    result = catalog["entries"][0].result
    assert result.base_slug == f"serienstream:{CANONICAL}"
    assert result.title.startswith("Monster")
    assert result.year == "2022"


def test_provider_authoritative_series_use_tmdb_for_artwork_only():
    runtime = (
        Path(__file__).resolve().parents[1] / "web" / "global-search-runtime.js"
    ).read_text(encoding="utf-8")

    assert 'item?.metadata_policy === "provider_authoritative"' in runtime
    assert "const artworkClones = authoritativeItems.map" in runtime
    assert '["cover_url", "backdrop_url"]' in runtime
    assert "target[field] = clone[field]" in runtime
    assert "tmdb_id" not in runtime.split("const artworkClones", 1)[1].split(
        "function uniqueCatalogContentEntries", 1,
    )[0]


def test_canonical_provider_detail_load_never_falls_back_to_other_series(monkeypatch):
    calls = []

    def load(provider, value):
        calls.append(("load", provider, value))
        return None

    def search(provider, query):
        calls.append(("search", provider, query))
        return [FilmpalastSeriesResult(
            title="Monarch: Legacy of Monsters",
            base_slug="huhu:monarch",
            sample_slug="huhu:monarch",
            sample_url="https://example.invalid/monarch",
        )]

    monkeypatch.setattr(server, "_load_series_for_provider", load)
    monkeypatch.setattr(server, "_search_series_for_provider", search)

    loaded = server.get_series_for_value(f"serienstream:{CANONICAL}")

    assert loaded is None
    assert calls == [
        ("load", "serienstream", f"serienstream:{CANONICAL}"),
        ("search", "serienstream", "Monster"),
    ]
    assert all(call[1] == "serienstream" for call in calls)
