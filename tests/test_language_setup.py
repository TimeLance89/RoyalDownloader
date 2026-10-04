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
