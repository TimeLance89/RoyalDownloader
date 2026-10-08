import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server  # noqa: F401
from api import api_administration_router as administration
from application_services import automation, content_language_policy
from core import config
from features.language_setup import language_setup_selection, language_setup_subscriptions
from features.subscription_languages import subscription_content_languages
from providers.catalog import provider_supports_languages
from providers.models import FilmpalastMovie, HosterInfo


@pytest.fixture
def studio(monkeypatch):
    orders = {"movies": list(config.MOVIE_PROVIDER_DEFAULTS), "series": list(config.SERIES_PROVIDER_DEFAULTS), "anime": list(config.ANIME_PROVIDER_DEFAULTS)}
    enabled = {kind: {p for p in ids if provider_supports_languages(p, {"de"})} for kind, ids in orders.items()}
    state = SimpleNamespace(ui_language="de", content_languages={"de"}, provider_enabled=enabled,
        subscription_content_languages={}, watchlist=[{"base_slug": "show-a", "title": "A", "episode_states": {"a": "available"}},
                                                     {"base_slug": "show-b", "title": "B", "episode_states": {"b": "available"}}],
        provider_priority_lock=threading.RLock(), ui_language_lock=threading.RLock(), watchlist_lock=threading.RLock(),
        movie_list_cache_lock=threading.RLock(), series_list_cache_lock=threading.RLock(), movie_source_cache_lock=threading.RLock(),
        movie_list_cache={"old": 1}, series_list_cache={"old": 1}, movie_source_cache={"old": 1}, fallback_series_cache={"old": 1},
        watchlist_new_slugs={"show-a": {"a"}, "show-b": {"b"}}, tmdb_cfg={"api_key": "", "language": "de-DE"})
    monkeypatch.setattr(administration, "state", state)
    monkeypatch.setattr(administration, "provider_order", lambda kind: orders[kind])
    monkeypatch.setattr(administration, "watchlist_payload", lambda: {})
    monkeypatch.setattr(administration, "broadcast", lambda _: None)
    monkeypatch.setattr(automation, "wake_watchlist_auto_check", lambda: None)
    writes = []
    monkeypatch.setattr(config, "save_language_setup", lambda *args: writes.append(args) or True)
    payload = asyncio.run(administration.api_language_setup_get())
    body = administration.LanguageSetupBody(ui_language="en", content_languages=["en"], update_subscriptions=["show-a"], revision=payload["revision"])
    return state, writes, body, orders


def test_transition_pins_future_subscription_languages_and_invalidates_old_checks(studio):
    state, writes, body, _ = studio
    result = asyncio.run(administration.api_language_setup_set(body))
    assert len(writes) == 1
    assert state.ui_language == "en" and state.content_languages == {"en"}
    assert state.subscription_content_languages == {"show-a": ["en"], "show-b": ["de"]}
    assert all(provider_supports_languages(p, {"en"}) for p in state.provider_enabled["movies"])
    assert all(entry["check_generation"] == 1 for entry in state.watchlist)
    assert state.watchlist_new_slugs == {}
    assert state.watchlist[0]["episode_states"]["a"] == "language_pending"
    assert result["saved"] is True and result["revision"] != body.revision
    assert state.movie_list_cache == state.movie_source_cache == state.series_list_cache == {}


def test_failed_atomic_write_leaves_runtime_and_subscriptions_unchanged(studio, monkeypatch):
    state, writes, body, _ = studio
    monkeypatch.setattr(config, "save_language_setup", lambda *_: False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(administration.api_language_setup_set(body))
    assert error.value.status_code == 503
    assert state.ui_language == "de" and state.content_languages == {"de"}
    assert state.subscription_content_languages == {}
    assert state.watchlist[0]["episode_states"]["a"] == "available"
    assert state.movie_list_cache == {"old": 1}


def test_stale_review_cannot_overwrite_newer_settings(studio):
    state, writes, body, _ = studio
    state.content_languages = {"de", "en"}
    with pytest.raises(HTTPException) as error:
        asyncio.run(administration.api_language_setup_set(body))
    assert error.value.status_code == 409 and writes == []


@pytest.mark.parametrize("language,languages", [("invalid", ["en"]), ("en", []), ("en", ["invalid"])])
def test_invalid_languages_are_rejected_without_mutation(studio, language, languages):
    _, writes, body, _ = studio
    if not languages:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            administration.LanguageSetupBody(**{**body.model_dump(), "content_languages": languages})
    else:
        invalid = administration.LanguageSetupBody(**{**body.model_dump(), "ui_language": language, "content_languages": languages})
        with pytest.raises(HTTPException):
            asyncio.run(administration.api_language_setup_set(invalid))
    assert writes == []


def test_atomic_language_config_survives_restart_and_failed_replace(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    enabled = {"movies": [config.MOVIE_PROVIDER_DEFAULTS[0]], "series": [config.SERIES_PROVIDER_DEFAULTS[0]], "anime": []}
    assert config.save_language_setup("en", ["en"], enabled, {"show": ["de"]})
    assert config.load_ui_language() == "en"
    assert config.load_content_languages() == ["en"]
    assert config.load_subscription_languages() == {"show": ["de"]}
    before = (tmp_path / "settings.ini").read_bytes()
    monkeypatch.setattr(config.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    assert not config.save_language_setup("de", ["de"], enabled, {"show": ["en"]})
    assert (tmp_path / "settings.ini").read_bytes() == before


def test_keep_current_languages_does_not_make_new_subscriptions_inherit_old_choice():
    entries = [{"base_slug": "old"}]
    prefs = language_setup_subscriptions(entries, {}, ["de"], ["en"], [])
    assert subscription_content_languages(entries[0], ["en"], prefs) == ["de"]
    assert subscription_content_languages({"base_slug": "new"}, ["en"], prefs) == ["en"]


def test_subscription_queue_contract_uses_its_retained_language(monkeypatch):
    slug = "serienstream:retained-s01e01"
    movie = FilmpalastMovie("Retained", "https://s.to/series/retained/episode-1", provider="serienstream", hosters=[HosterInfo("VOE", "https://voe.test/en", "en")])
    movie._subscription_content_languages = ["de"]
    monkeypatch.setattr(server.state, "content_languages", {"en"})
    monkeypatch.setattr(server.state, "queue_jobs", {})
    monkeypatch.setattr(server.state, "queue_job_by_slug", {})
    assert server._ensure_queue_job(slug, movie)["content_language"] == "de"


def test_manual_subscribed_episode_keeps_german_without_auto_download_attribute(monkeypatch):
    base = "serienstream:chicago-pd"
    movie = FilmpalastMovie("Chicago P.D. S13E07", f"{base}-s13e07", provider="serienstream",
        hosters=[HosterInfo("VOE", "https://voe.test/en", "en")])
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    monkeypatch.setattr(server.state, "subscription_content_languages", {base: ["de"]})
    monkeypatch.setattr(server.state, "watchlist", [{"base_slug": base, "title": "Chicago P.D."}])
    monkeypatch.setattr(server.state, "queue_jobs", {})
    monkeypatch.setattr(server.state, "queue_job_by_slug", {})
    assert server._ensure_queue_job(f"{base}-s13e07", movie)["content_language"] == "de"


def test_retained_subscription_can_still_reach_its_old_language_provider(monkeypatch):
    from application_services import movie_catalog
    from providers import sentinel_runtime
    fake = SimpleNamespace(content_languages={"en"}, provider_priority_lock=threading.RLock(),
        provider_enabled={"series": {"sflix"}}, watchlist=[{"base_slug": "retained"}],
        subscription_content_languages={"retained": ["de"]},
        provider_health=SimpleNamespace(routing_allowed=lambda _: True))
    monkeypatch.setattr(movie_catalog, "state", fake)
    monkeypatch.setattr(movie_catalog, "provider_order", lambda _: ["sflix", "serienstream"])
    monkeypatch.setattr(movie_catalog, "provider_supports_languages", lambda provider, langs: bool(set(langs) & ({"en"} if provider == "sflix" else {"de"})))
    monkeypatch.setattr(sentinel_runtime, "provider_routing_penalty", lambda _: 0)
    assert movie_catalog.provider_priority.__wrapped__("series") == ["sflix", "serienstream"]
    fake.watchlist = []
    assert movie_catalog.provider_priority.__wrapped__("series") == ["sflix"]


@pytest.mark.parametrize("method", ["get", "post"])
def test_busy_profile_times_out_without_blocking_event_loop_or_mutating(studio, method):
    state, writes, body, _ = studio
    # Hold a later lock to exercise cleanup of the already acquired watchlist lock.
    state.provider_priority_lock = threading.Lock()
    state.provider_priority_lock.acquire()
    async def exercise():
        request = asyncio.create_task(administration.api_language_setup_get() if method == "get"
                                      else administration.api_language_setup_set(body))
        await asyncio.sleep(0.05)
        assert not request.done(), "Profile locking must run outside the event loop"
        with pytest.raises(HTTPException) as error:
            await request
        assert error.value.status_code == 503
    try:
        asyncio.run(exercise())
        assert state.watchlist_lock.acquire(timeout=0.05)
        state.watchlist_lock.release()
        assert writes == [] and state.ui_language == "de"
    finally:
        state.provider_priority_lock.release()


@pytest.mark.parametrize("switch", [False, True])
def test_onboarding_subscription_choice_is_in_same_atomic_config_write(monkeypatch, tmp_path, switch):
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    entries = [{"base_slug": "restored"}]
    prefs = language_setup_subscriptions(entries, {}, ["de"], ["en"], ["restored"] if switch else [])
    assert config.save_initial_setup("/movies", "/series", ui_language="en", content_languages=["en"], subscription_languages=prefs)
    assert config.load_content_languages() == ["en"]
    assert config.load_subscription_languages() == {"restored": ["en"] if switch else ["de"]}
    before = (tmp_path / "settings.ini").read_bytes()
    monkeypatch.setattr(config.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    assert not config.save_initial_setup("/new", "/new", ui_language="de", content_languages=["de"], subscription_languages={})
    assert (tmp_path / "settings.ini").read_bytes() == before


@pytest.mark.parametrize("switch,fail", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("jellyfin_url", ["", "http://optional-jellyfin:8096"])
def test_initial_setup_applies_subscription_policy_only_after_durable_save(studio, monkeypatch, tmp_path, switch, fail, jellyfin_url):
    from unittest.mock import AsyncMock
    from api.api_setup_router import SetupCompleteBody
    state, _, _, _ = studio
    state.jellyfin_cache_lock = threading.RLock()
    state.jellyfin_cfg = {}
    state.telegram_cfg = {}
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "is_initialized", lambda: False)
    monkeypatch.setattr(administration, "auth_configured", lambda: True)
    monkeypatch.setattr(administration, "_validate_setup_tmdb_key", AsyncMock())
    monkeypatch.setattr(administration, "_prepare_media_directory", lambda *_: None)
    monkeypatch.setattr(administration, "_write_deployment_environment", lambda *_: {"path": "fixture", "created": False})
    monkeypatch.setattr(administration, "_set_runtime_jellyfin_config", lambda *_: None)
    monkeypatch.setattr(administration, "start_background_services", lambda: None)
    body = SetupCompleteBody(save_path="/movies", series_path="/series", tmdb_api_key="fixture",
        jellyfin_url=jellyfin_url, jellyfin_api_key="",
        ui_language="en", content_languages=["en"], movie_providers=["moviebox"],
        series_providers=["vidrift"], anime_providers=[], update_existing_subscriptions=switch)
    if fail:
        monkeypatch.setattr(config, "_update_all", lambda *args, **kwargs: False)
        with pytest.raises(HTTPException):
            asyncio.run(administration._api_setup_complete_locked(body, SimpleNamespace()))
        assert state.subscription_content_languages == {}
        assert state.watchlist[0]["episode_states"]["a"] == "available"
        return
    result = asyncio.run(administration._api_setup_complete_locked(body, SimpleNamespace()))
    assert result["saved"] is True
    assert config.load_jellyfin()["url"] == jellyfin_url
    assert config.load_jellyfin()["api_key"] == ""
    assert state.subscription_content_languages == config.load_subscription_languages() == {
        "show-a": ["en"] if switch else ["de"], "show-b": ["en"] if switch else ["de"]}
    assert state.watchlist_new_slugs == {}
    assert state.watchlist[0]["episode_states"]["a"] == "language_pending"
