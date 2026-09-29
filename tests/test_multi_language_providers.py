"""Capabilities, concrete tracks and language evidence must remain separate."""
import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from providers.catalog import (
    PROVIDER_CATALOG, provider_catalog_payload, provider_content_language,
    provider_content_languages, provider_supports_languages, provider_track_language,
    provider_language_keys, selected_episode_language,
    selected_source_language_allowed,
)
from providers.aniworld import AniWorldAnime, AniWorldEpisode, aniworld_episode_page
from providers.mkissa import MkissaAnime, MkissaScraper, anime_episode_page
from providers.models import FilmpalastMovie, HosterInfo
from application_services.provider_monitor import ProviderMonitor
from application_services.provider_probe import ProviderProbe
from application_services.source_service_health import source_service_health
from media.provider_health import ProviderHealth

NOW = 2_000_000


@pytest.mark.parametrize("key,primary,supported", [
    ("aniworld", "de", ("de", "en")), ("mkissa", "en", ("en",)),
    ("filmpalast", "de", ("de",)), ("sflix", "en", ("en",)),
])
def test_catalog_preserves_primary_and_exposes_capabilities(key, primary, supported):
    assert provider_content_language(key) == primary
    assert PROVIDER_CATALOG[key].primary_language == primary
    assert provider_content_languages(key) == supported
    row = provider_catalog_payload()[key]
    assert row["content_language"] == primary
    assert row["content_languages"] == list(supported)
    assert len(row["language_labels"]) == len(supported)


@pytest.mark.parametrize("languages", [{"de"}, {"en"}, {"de", "en"}])
def test_aniworld_selection_intersects_both_languages(languages, monkeypatch):
    import server
    from application_services.movie_catalog import provider_priority
    monkeypatch.setattr(server.state, "content_languages", languages)
    monkeypatch.setattr(server.state, "provider_enabled", {"anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state, "provider_priorities", {"anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state.provider_health, "request_allowed", lambda _key: True)
    assert "aniworld" in provider_priority("anime")
    assert "aniworld" in server._sentinel_enabled_providers()
    assert ("mkissa" in provider_priority("anime")) == ("en" in languages)


def test_raw_remains_an_explicit_japanese_track_not_global_english():
    assert provider_track_language("mkissa", "raw") == "ja"
    assert selected_episode_language("mkissa", "mkissa:fixture|raw-s01e001") == "ja"
    assert selected_episode_language("mkissa", "aniworld:fixture|eng-s01e001") == ""
    assert "ja" not in provider_language_keys()
    assert not provider_supports_languages("mkissa", {"de"})
    anime = MkissaAnime("fixture", "Fixture", translations={"dub": 1, "sub": 1, "raw": 1})
    assert anime.public_dict()["content_languages"] == ["en", "ja"]
    assert anime_episode_page(anime, "raw")["episodes"][0]["content_language"] == "ja"


def test_actual_raw_episode_object_is_japanese(monkeypatch):
    scraper = MkissaScraper.__new__(MkissaScraper)
    monkeypatch.setattr(scraper, "get_anime", lambda _id: MkissaAnime("fixture", "Fixture", translations={"raw": 1}))
    monkeypatch.setattr(scraper, "_episode_sources", lambda *_args: [{"sourceName": "VOE", "sourceUrl": "https://voe.example/fixture"}])
    monkeypatch.setattr(scraper, "_resolve_source_url", lambda url: url)
    movie = scraper.get_episode("mkissa:fixture|raw-s01e001")
    assert movie.content_language == "ja"
    assert movie.hosters[0].language == "Japanese Raw"


def test_auxiliary_track_requires_explicit_selection_and_matching_provider():
    assert selected_source_language_allowed("mkissa", "ja", {"en"}, "mkissa:fixture|raw-s01e001")
    assert not selected_source_language_allowed("mkissa", "ja", {"de"}, "mkissa:fixture|raw-s01e001")
    assert not selected_source_language_allowed("mkissa", "ja", {"en"}, "mkissa:fixture|dub-s01e001")
    assert not selected_source_language_allowed("aniworld", "en", {"de"}, "aniworld:fixture|eng-s01e001")


def test_real_load_path_keeps_explicit_raw_and_honors_disabled_aniworld_english(monkeypatch):
    import server
    from application_services import movie_catalog
    monkeypatch.setattr(server.state, "content_languages", {"en"})
    raw = FilmpalastMovie("Fixture", "mkissa:fixture|raw-s01e001", provider="mkissa", content_language="ja")
    monkeypatch.setattr(movie_catalog, "get_mkissa_scraper", lambda: SimpleNamespace(get_episode=lambda _slug: raw))
    assert movie_catalog.load_movie_for_slug(raw.url).content_language == "ja"
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    assert movie_catalog.load_movie_for_slug(raw.url) is None
    english = FilmpalastMovie("Fixture", "aniworld:fixture|eng-s01e001", provider="aniworld", content_language="en")
    monkeypatch.setattr(movie_catalog, "get_aniworld_scraper", lambda: SimpleNamespace(get_episode=lambda _slug: english))
    assert movie_catalog.load_movie_for_slug(english.url) is None


@pytest.mark.parametrize("tracks,expected", [({"dub": 1, "sub": 1}, ["de"]), ({"dub": 1, "sub": 1, "eng": 1}, ["de", "en"])])
def test_title_tracks_never_inherit_provider_capabilities(tracks, expected):
    anime = AniWorldAnime("fixture", "Fixture", translations=tracks,
                          episodes=[AniWorldEpisode(1, 1, tracks=tuple(tracks))])
    assert anime.public_dict()["content_languages"] == expected
    assert anime.public_dict()["translations"] == tracks
    assert aniworld_episode_page(anime, "sub")["episodes"][0]["content_language"] == "de"
    assert provider_content_languages("aniworld") == ("de", "en")


def source(key, supported, language, evidence=(), broken=False):
    return {"provider": key, "enabled": True, "contract": {"media_types": ["anime"]},
            "content_language": language, "content_languages": list(supported),
            "language_evidence": {"anime": {lang: NOW - 30 for lang in evidence}},
            "diagnosis": "broken" if broken else "healthy", "last_check_at": NOW - 60,
            "runtime": {"state": "cooldown" if broken else "healthy"}, "routing": {"allowed": not broken}}


def health(ani=True, mk=True, languages=("de", "en"), evidence=("de", "en")):
    providers = [source("aniworld", ("de", "en"), "de", evidence, not ani),
                 source("mkissa", ("en",), "en", broken=not mk)]
    hosters = [{"hoster": "working", "providers": ["aniworld", "mkissa"], "diagnosis": "healthy", "last_check_at": NOW - 10}]
    return source_service_health(providers, hosters, NOW, languages)


@pytest.mark.parametrize("languages", [("de",), ("en",), ("de", "en")])
def test_confirmed_aniworld_paths_are_counted_once_and_only_when_enabled(languages):
    summary = health(languages=languages)
    paths = {row["language"]: row for row in summary["paths"]}
    assert set(paths) == set(languages)
    assert all(row["state"] == "healthy" for row in paths.values())
    if "de" in paths:
        assert paths["de"]["configured_sources"] == 1  # dub/sub are not two sources
    if "en" in paths:
        assert paths["en"]["configured_sources"] == 2
    assert not summary["action_required"]


def test_missing_german_cannot_be_hidden_by_english_provider():
    summary = health(ani=False)
    paths = {row["language"]: row for row in summary["paths"]}
    assert summary["action_required"]
    assert paths["de"]["state"] == "action_required"
    assert paths["en"]["available_sources"] == 1
    assert paths["en"]["state"] != "action_required"


def test_aniworld_english_alternative_avoids_loss_but_not_false_redundancy_claim():
    summary = health(mk=False)
    paths = {row["language"]: row for row in summary["paths"]}
    assert paths["de"]["state"] == "healthy"
    assert paths["en"]["available_sources"] == 1
    assert paths["en"]["state"] == "degraded"  # works, one confirmed fallback lost
    assert not summary["action_required"]


def test_provider_health_and_german_success_do_not_prove_english_track():
    summary = health(mk=False, evidence=("de",))
    paths = {row["language"]: row for row in summary["paths"]}
    assert paths["de"]["state"] == "healthy"
    assert paths["en"]["state"] == "unconfirmed"
    assert not summary["action_required"]


def test_stale_language_evidence_does_not_prove_track():
    providers = [source("aniworld", ("de", "en"), "de", ("de", "en"))]
    providers[0]["language_evidence"]["anime"]["en"] = NOW - 86401
    videos = [{"hoster": "working", "providers": ["aniworld"], "diagnosis": "healthy", "last_check_at": NOW}]
    summary = source_service_health(providers, videos, NOW, ("en",))
    assert summary["paths"][0]["state"] == "unconfirmed"


def test_full_probe_reports_only_the_concrete_track_it_tested():
    title = AniWorldAnime("fixture", "Fixture", translations={"eng": 1},
                         episodes=[AniWorldEpisode(1, 1, tracks=("eng",))])
    episode = FilmpalastMovie("Fixture S01E01", "aniworld:fixture|eng-s01e001", provider="aniworld", content_language="en",
                              hosters=[HosterInfo("VOE", "https://voe.example/fixture")])
    adapter = SimpleNamespace(session=SimpleNamespace(get=lambda _url: True),
        browse=lambda **_kwargs: {"results": [title.public_dict()]}, get_anime=lambda *_args, **_kwargs: title,
        get_episode=lambda _slug: episode)
    result = ProviderProbe(factory=lambda _key: adapter).run("aniworld", "full")
    assert result["details"][0]["content_languages"] == ["en"]
    assert result["details"][0]["ok"]
    episode.hosters = []
    assert ProviderProbe(factory=lambda _key: adapter).run("aniworld", "full")["details"][0]["content_languages"] == []


def test_language_runtime_observation_is_optional_and_fail_open(monkeypatch, tmp_path):
    from providers import sentinel_runtime as runtime
    owner = ProviderMonitor(tmp_path / "monitor.json", ProviderHealth(tmp_path / "health.json"), lambda: ["aniworld"], clock=lambda: NOW)
    monkeypatch.setattr(runtime, "_runtime", owner)
    runtime.observe_language_safely("aniworld", "anime", "en")
    assert owner.store.entry("aniworld")["language_evidence"] == {"anime": {"en": NOW}}
    monkeypatch.setattr(owner, "record_language_success", lambda *_args: (_ for _ in ()).throw(OSError("disk unavailable")))
    runtime.observe_language_safely("aniworld", "anime", "en")
    owner.stop()


def test_language_evidence_reuses_store_and_survives_restart_without_identifiers(tmp_path):
    path = tmp_path / "monitor.json"
    owner = ProviderMonitor(path, ProviderHealth(tmp_path / "health.json"), lambda: ["aniworld"],
                            languages=lambda: ["en"], clock=lambda: NOW)
    owner.record_language_success("aniworld", "anime", "en")
    owner.record_language_success("aniworld", "anime", "ja")  # not a configured capability
    owner.record_language_success("aniworld", "movies", "en")
    episode = FilmpalastMovie("Private title", "aniworld:private|dub-s01e001", provider="aniworld", content_language="de",
                              hosters=[HosterInfo("VOE", "https://voe.example/private?token=secret")])
    owner.observe("aniworld", True, .1, episode.url, episode, "get_episode")
    reloaded = ProviderMonitor(path, ProviderHealth(tmp_path / "health2.json"), lambda: ["aniworld"], clock=lambda: NOW)
    assert reloaded.store.entry("aniworld")["language_evidence"] == {"anime": {"en": NOW, "de": NOW}}
    assert [p["language"] for p in owner.diagnostics()["service"]["paths"]] == ["en"]
    assert "Private title" not in path.read_text() and "token=secret" not in path.read_text()
    owner.stop(); reloaded.stop()


@pytest.mark.parametrize("languages", [["de"], ["en"], ["de", "en"]])
def test_real_admin_language_validation_accepts_aniworld(languages, monkeypatch):
    import api.api_administration_router as admin
    import core.config as config
    # Stop after the complete validation, before writing any installation data.
    class Validated(Exception):
        pass
    def after_validation(*_args, **_kwargs):
        raise Validated
    monkeypatch.setattr(config, "load_provider_enabled", lambda: {"movies": [], "series": [], "anime": []})
    monkeypatch.setattr(config, "save_provider_priorities", after_validation)
    body = admin.ProviderPriorityBody(
        movies=list(config.MOVIE_PROVIDER_DEFAULTS), series=list(config.SERIES_PROVIDER_DEFAULTS), anime=list(config.ANIME_PROVIDER_DEFAULTS),
        enabled_movies=["filmpalast" if "de" in languages else "sflix"],
        enabled_series=["serienstream" if "de" in languages else "sflix"], enabled_anime=["aniworld"], content_languages=languages,
    )
    with pytest.raises(Validated):
        asyncio.run(admin.api_provider_priority_set(body))
    body.enabled_anime = ["mkissa"]
    if languages == ["de"]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(admin.api_provider_priority_set(body))
        assert error.value.status_code == 400


def test_english_only_aniworld_detail_uses_actual_english_tracks(monkeypatch):
    import api.api_discovery_router as discovery
    anime = AniWorldAnime("fixture", "Fixture", translations={"dub": 1, "sub": 1, "eng": 1},
                          episodes=[AniWorldEpisode(1, 1, tracks=("dub", "sub", "eng"))])
    monkeypatch.setattr(discovery, "provider_priority", lambda _kind: ["aniworld"])
    monkeypatch.setattr(discovery, "state", SimpleNamespace(content_languages={"en"}, provider_enabled={"anime": ["aniworld"]}, provider_health=SimpleNamespace(routing_allowed=lambda _p: True), aniworld_lock=threading.RLock(), picked=set()))
    monkeypatch.setattr(discovery, "get_aniworld_scraper", lambda: SimpleNamespace(get_anime=lambda _id: anime))
    monkeypatch.setattr(discovery, "_existing_valid_episode_path", lambda *_args: None)
    detail = asyncio.run(discovery.api_aniworld_detail("fixture", translation="dub"))
    assert detail["translation"] == "eng"
    assert detail["translations"] == {"eng": 1}
    assert detail["content_languages"] == ["en"]
    assert detail["episodes"][0]["content_language"] == "en"


@pytest.mark.parametrize("languages", [["de"], ["en"], ["de", "en"]])
def test_setup_validates_multilingual_provider_before_external_validation(languages, monkeypatch):
    import api.api_administration_router as admin
    from api.api_setup_router import SetupCompleteBody
    import core.config as config
    class Validated(Exception):
        pass
    async def after_validation(*_args):
        raise Validated
    monkeypatch.setattr(config, "is_initialized", lambda: False)
    monkeypatch.setattr(admin, "auth_configured", lambda: True)
    monkeypatch.setattr(admin, "_validate_setup_tmdb_key", after_validation)
    body = SetupCompleteBody(save_path="/fixture/movies", anime_providers=["aniworld"], content_languages=languages,
        movie_providers=["filmpalast" if "de" in languages else "sflix"],
        series_providers=["serienstream" if "de" in languages else "sflix"])
    with pytest.raises(Validated):
        asyncio.run(admin._api_setup_complete_locked(body, SimpleNamespace()))


def test_old_queue_language_stays_single_and_new_raw_job_records_selected_language(monkeypatch):
    import server
    from application_services import content_language_policy as policy
    old = {"content_language": "en", "provider": "mkissa"}
    monkeypatch.setattr(policy, "_ORIGINAL_ENSURE_QUEUE_JOB", lambda *_args, **_kwargs: old)
    raw = FilmpalastMovie("Fixture", "mkissa:fixture|raw-s01e001", provider="mkissa", content_language="ja")
    assert policy._ensure_queue_job(raw.url, raw)["content_language"] == "en"
    new = {}
    monkeypatch.setattr(policy, "_ORIGINAL_ENSURE_QUEUE_JOB", lambda *_args, **_kwargs: new)
    assert policy._ensure_queue_job(raw.url, raw)["content_language"] == "ja"
    assert server.appconfig.normalize_content_languages(["de"]) == ["de"]
