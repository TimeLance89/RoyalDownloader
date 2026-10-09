"""AniWorld must preserve series identity, episode numbering and audio lanes."""

import asyncio
from types import SimpleNamespace

import pytest

import server
from core.queue_jobs import new_job
from features.episode_language_probe import EpisodeLanguageProbes
from features.episode_source_probe import EpisodeSourceProbes, episode_source_providers
from media.provider_health import ProviderHealth
from providers.aniworld import AniWorldAnime, AniWorldEpisode, AniWorldScraper
from providers.models import FilmpalastMovie, FilmpalastSeries, HosterInfo, SeriesEpisode


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    for name in ("fallback_series_cache", "fallback_provider_errors", "series_cache",
                 "movie_source_cache", "queue_jobs", "queue_job_by_slug",
                 "watchlist_new_slugs", "subscription_content_languages"):
        monkeypatch.setattr(server.state, name, {})
    for name in ("picked", "counted_queue_slugs", "preparing_queue_slugs", "done_slugs"):
        monkeypatch.setattr(server.state, name, set())
    monkeypatch.setattr(server.state, "watchlist", [])
    monkeypatch.setattr(server.state, "provider_waiting_jobs", {})
    monkeypatch.setattr(server.state, "provider_health", ProviderHealth(tmp_path / "health.json"))
    monkeypatch.setattr(server.state, "provider_priorities", {"series": ["huhu"], "anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state, "provider_enabled", {"series": ["huhu"], "anime": ["aniworld"]})
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    monkeypatch.setattr(server, "broadcast", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: None)
    monkeypatch.setattr(server, "_ensure_provider_retry_worker", lambda: None)
    monkeypatch.setattr(server, "get_tmdb_client", lambda: SimpleNamespace(configured=False))
    anime = AniWorldAnime(
        "sailor-moon", "Sailor Moon", year="1992",
        episodes=[
            AniWorldEpisode(1, 1, tracks=("dub", "sub")),
            AniWorldEpisode(1, 2, tracks=("dub", "sub")),
            AniWorldEpisode(2, 1, tracks=("dub", "eng", "sub")),
            AniWorldEpisode(2, 43, tracks=("sub",)),
            AniWorldEpisode(5, 34, tracks=("dub", "sub")),
            AniWorldEpisode(0, 1, tracks=("dub",), kind="movie"),
        ],
    )
    loads, searches, fetched = [], [], []
    scraper = AniWorldScraper()
    monkeypatch.setattr(scraper, "_search", lambda query: searches.append(query) or [anime])
    monkeypatch.setattr(scraper, "get_anime", lambda identity: loads.append(identity) or anime)
    def soup(url):
        from bs4 import BeautifulSoup
        fetched.append(url)
        return BeautifulSoup('''
            <li data-lang-key="1" data-link-target="/redirect/dub"><h4>VOE</h4></li>
            <li data-lang-key="2" data-link-target="/redirect/eng"><h4>VOE</h4></li>
            <li data-lang-key="3" data-link-target="/redirect/sub"><h4>VOE</h4></li>
        ''', "html.parser")
    monkeypatch.setattr(scraper, "_soup", soup)
    monkeypatch.setattr(server, "get_aniworld_scraper", lambda: scraper)
    return SimpleNamespace(anime=anime, scraper=scraper, loads=loads, searches=searches, fetched=fetched)


def test_disabled_anime_sources_are_not_added_to_series_order():
    assert episode_source_providers(["huhu", "serienstream"], ["mkissa"]) == ("huhu", "serienstream")
    assert episode_source_providers(["huhu", "aniworld"], ["aniworld", "mkissa"]) == ("huhu", "aniworld")


def test_native_seasons_and_episode_flags_are_preserved_and_films_are_excluded(bridge):
    series = bridge.scraper.get_series("aniworld:sailor-moon")
    assert series.season_numbers == [1, 2, 5]
    assert [ep.episode for ep in series.seasons[2]] == [1, 43]
    assert series.seasons[2][1].content_languages == ("ja",)
    assert all(ep.season > 0 for ep in series.all_episodes)


def test_unknown_audio_does_not_remove_episode_numbering_or_invent_german(bridge):
    bridge.anime.episodes.append(AniWorldEpisode(1, 3))
    episode = bridge.scraper.get_series("aniworld:sailor-moon").seasons[1][-1]
    assert episode.episode == 3
    assert episode.content_languages == ()


@pytest.mark.parametrize("season,episode", [(1, 1), (5, 34)])
def test_huhu_falls_back_to_the_exact_aniworld_german_episode_and_shared_catalog_cache(bridge, season, episode):
    slug = f"huhu:3570:sailor-moon-s{season:02d}e{episode:02d}"
    for _ in range(2):
        found = server.find_episode_fallbacks("Sailor Moon", season, episode, source_slug=slug)
        assert len(found) == 1
        assert found[0].provider == "aniworld"
        assert found[0].content_language == "de"
        assert found[0].hosters[0].language == "Deutsch Dub"
        assert found[0].hosters[0].url.endswith("/dub")
        assert found[0].url.endswith(f"/staffel-{season}/episode-{episode}")
    assert bridge.searches == ["Sailor Moon"]


@pytest.mark.parametrize("enabled,blocked,excluded", [(False, False, False), (True, True, False), (True, False, True)])
def test_disabled_blocked_or_excluded_aniworld_is_never_contacted(monkeypatch, bridge, enabled, blocked, excluded):
    if not enabled:
        monkeypatch.setattr(server.state, "provider_enabled", {"series": ["huhu"], "anime": []})
    if blocked:
        server.state.provider_health.mark_blocked("aniworld", "captcha_gate")
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1,
        source_slug="huhu:3570:sailor-moon-s01e01",
        excluded_providers={"aniworld"} if excluded else set()) == []
    assert bridge.searches == bridge.fetched == []


@pytest.mark.parametrize("season,episode", [(2, 43), (9, 1), (1, 99), (0, 1)])
def test_subtitle_only_missing_and_movie_episodes_never_become_german_fallbacks(bridge, season, episode):
    assert server.find_episode_fallbacks("Sailor Moon", season, episode,
        source_slug=f"huhu:3570:sailor-moon-s{season:02d}e{episode:02d}", raise_on_error=True) == []
    assert bridge.fetched == []


def test_explicit_english_audio_selects_the_english_lane_instead_of_german(monkeypatch, bridge):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    found = server.find_episode_fallbacks("Sailor Moon", 2, 1,
        source_slug="huhu:3570:sailor-moon-s02e01", content_languages={"en"})
    assert found[0].content_language == "en"
    assert found[0].hosters[0].url.endswith("/eng")


def test_explicit_english_lane_cannot_override_german_only_global_filter(bridge):
    assert server.find_episode_fallbacks("Sailor Moon", 2, 1,
        source_slug="huhu:3570:sailor-moon-s02e01", content_languages={"en"}) == []


def test_temporary_catalog_failure_is_retried_after_cooldown(monkeypatch, bridge):
    def unavailable(_query):
        raise TimeoutError("temporary catalog timeout")
    monkeypatch.setattr(bridge.scraper, "_search", unavailable)
    slug = "huhu:3570:sailor-moon-s01e01"
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1, source_slug=slug) == []
    assert "aniworld" in server.state.fallback_provider_errors
    assert not server.state.fallback_series_cache
    monkeypatch.setattr(bridge.scraper, "_search", lambda _query: [bridge.anime])
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1, source_slug=slug) == []
    server.state.fallback_provider_errors["aniworld"] = (0, "expired")
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1, source_slug=slug)[0].provider == "aniworld"
    assert "aniworld" not in server.state.fallback_provider_errors


def test_pinned_queue_language_wins_over_global_mixed_lanes(monkeypatch, bridge):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    slug = "huhu:3570:sailor-moon-s02e01"
    job = new_job(slug, job_id="pinned-en")
    job["content_language"] = "en"
    server.state.queue_jobs[job["job_id"]] = job
    server.state.queue_job_by_slug[slug] = job["job_id"]
    assert server.find_episode_fallbacks("Sailor Moon", 2, 1, source_slug=slug)[0].content_language == "en"


def test_subscription_audio_preference_controls_aniworld_track(monkeypatch, bridge):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    base = "huhu:3570:sailor-moon"
    server.state.subscription_content_languages[base] = ["en"]
    assert server.find_episode_fallbacks("Sailor Moon", 2, 1,
        source_slug=f"{base}-s02e01")[0].content_language == "en"


def test_exact_alternate_title_matches_without_accepting_similar_sequel(bridge):
    bridge.anime.alternative_titles = ["Beautiful Girl Soldier Sailormoon"]
    assert server.find_episode_fallbacks("Beautiful Girl Soldier Sailormoon", 1, 1,
        source_slug="huhu:3570:sailor-moon-s01e01")[0].provider == "aniworld"
    assert server.find_episode_fallbacks("Sailor Moon Crystal", 1, 1,
        source_slug="huhu:3570:sailor-moon-crystal-s01e01") == []


def test_ambiguous_same_title_is_not_arbitrarily_selected(monkeypatch, bridge):
    monkeypatch.setattr(bridge.scraper, "_search", lambda _query: [bridge.anime, AniWorldAnime("remake", "Sailor Moon")])
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1,
        source_slug="huhu:3570:sailor-moon-s01e01") == []
    assert bridge.loads == []


def test_actual_detail_title_must_match_the_search_identity(monkeypatch, bridge):
    monkeypatch.setattr(bridge.scraper, "get_anime", lambda _identity: AniWorldAnime(
        "sailor-moon", "Sailor Moon Crystal", episodes=bridge.anime.episodes))
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1,
        source_slug="huhu:3570:sailor-moon-s01e01") == []


@pytest.mark.parametrize("year,numbers", [("2014", [1, 2]), ("1992", [1, 2, 3])])
def test_known_remakes_or_different_season_splits_are_rejected(bridge, year, numbers):
    base = "huhu:3570:sailor-moon"
    server.state.series_cache[base] = FilmpalastSeries("Sailor Moon", base, "https://huhu.to/item", year=year,
        seasons={1: [SeriesEpisode(1, number, f"{base}-s01e{number:02d}", "") for number in numbers]})
    assert server.find_episode_fallbacks("Sailor Moon", 1, 1, source_slug=f"{base}-s01e01") == []
    assert bridge.fetched == []


def test_identical_known_numbering_keeps_the_aniworld_source(bridge):
    base = "huhu:3570:sailor-moon"
    server.state.series_cache[base] = FilmpalastSeries("Sailor Moon", base, "https://huhu.to/item", year="1992",
        seasons={1: [SeriesEpisode(1, number, f"{base}-s01e{number:02d}", "") for number in (1, 2)]})
    assert len(server.find_episode_fallbacks("Sailor Moon", 1, 1, source_slug=f"{base}-s01e01")) == 1


def test_huhu_gersub_is_rejected_then_aniworld_dub_enqueues_with_original_identity(monkeypatch, bridge, tmp_path):
    from application_services import source_resolution
    from media.resolved_link_cache import ResolvedLinkCache
    from media.source_language import StreamInfo
    slug = "huhu:3570:sailor-moon-s01e01"
    primary = FilmpalastMovie("Sailor Moon S01E01", "https://huhu.to/item", provider="huhu",
        hosters=[HosterInfo("VOE", "https://voe.sx/sub", "de")])
    job = new_job(slug, job_id="fallback-de")
    job["content_language"] = "de"
    server.state.queue_jobs[job["job_id"]] = job
    server.state.queue_job_by_slug[slug] = job["job_id"]
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server, "_episode_fallback_aliases", lambda *_args: ())
    monkeypatch.setattr(server.state, "resolved_link_cache", ResolvedLinkCache(tmp_path / "links.json"))
    monkeypatch.setattr(bridge.scraper, "resolve_play_url", lambda *_args, **_kwargs: "https://voe.sx/dub")
    monkeypatch.setattr(source_resolution.state.hoster_intel, "rank", lambda hosters: list(hosters))
    monkeypatch.setattr(source_resolution.state.hoster_intel, "cooldown", lambda *_args, **_kwargs: (0, ""))
    monkeypatch.setattr(source_resolution.state.hoster_intel, "record_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(source_resolution, "hoster_attempt_safely", lambda *_args: None)
    monkeypatch.setattr(source_resolution, "observe_hoster_safely", lambda *_args: None)
    monkeypatch.setattr(source_resolution, "_shared_browser_pool", lambda _reason: object())
    monkeypatch.setattr(source_resolution, "pre_check_voe", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(source_resolution, "hoster_profile_safely", lambda *_args: {})
    extracted, probed = [], []
    def extract(url, **_kwargs):
        extracted.append(url)
        track = "sub" if url.endswith("/sub") else "dub"
        return StreamInfo(f"https://cdn.example/{track}.m3u8", "hls", [
            "Sailor.Moon.S01E01.GerSub.mp4" if track == "sub" else "Sailor.Moon.S01E01.German.Dub.mp4",
        ])
    monkeypatch.setattr(source_resolution, "extract_stream_url", extract)
    monkeypatch.setattr(source_resolution, "probe_stream_url", lambda url, **_kwargs: (probed.append(url) or True, "ok"))
    queued = []
    monkeypatch.setattr(server, "_enqueue_hoster_attempt", lambda **kwargs: queued.append(kwargs) or True)
    assert server.run_download_queue([(primary, slug)], tmp_path, start_queue=False) == {slug}
    assert queued[0]["movie"].provider == "aniworld"
    assert queued[0]["movie"]._required_content_language == "de"
    assert queued[0]["movie_slug"] == slug
    assert server.state.queue_jobs[job["job_id"]]["content_language"] == "de"
    assert extracted == ["https://voe.sx/sub", "https://voe.sx/dub"]
    assert probed == ["https://cdn.example/dub.m3u8"]


def test_language_probe_finds_aniworld_and_keeps_original_queue_identity(monkeypatch, bridge):
    import api.api_discovery_router as discovery
    import api.api_library_router as library
    primary, sources = EpisodeLanguageProbes(workers=1), EpisodeSourceProbes(workers=1)
    monkeypatch.setattr("features.episode_language_probe.language_probes", primary)
    monkeypatch.setattr("features.episode_source_probe.episode_source_probes", sources)
    monkeypatch.setattr(discovery, "episode_languages_for_slug", lambda *_args: ["en"])
    monkeypatch.setattr(library, "record_watchlist_episode_languages", lambda _values: None)
    slug = "huhu:3570:sailor-moon-s01e01"
    try:
        result = asyncio.run(discovery.api_series_episode_languages(discovery.SeriesEpisodeLanguagesBody(
            provider="huhu", slugs=[slug], title="Sailor Moon", content_languages=["de"])))
        assert result["available"][slug] is True
        assert result["source_providers"][slug] == ["aniworld"]
        cached = server.state.movie_source_cache[slug]
        assert cached[0].url == slug
        assert cached[1].provider == "aniworld"
        assert cached[1].hosters[0].language == "Deutsch Dub"
    finally:
        primary.close()
        sources.close()


def test_transfer_failure_searches_aniworld_lazily_and_retains_language_and_path(monkeypatch, bridge, tmp_path):
    from application_services import source_resolution
    import application_services.storage_autopilot_runtime as storage
    slug = "huhu:3570:sailor-moon-s01e01"
    primary = FilmpalastMovie("Sailor Moon S01E01", "https://huhu.to/item", provider="huhu",
        hosters=[HosterInfo("VOE", "https://voe.sx/primary", "de")])
    logical = new_job(slug, job_id="transfer-fallback")
    logical["content_language"] = "de"
    server.state.queue_jobs[logical["job_id"]] = logical
    server.state.queue_job_by_slug[slug] = logical["job_id"]
    server.state.picked.add(slug)
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server, "_existing_valid_episode_path", lambda *_args: None)
    monkeypatch.setattr(server, "_episode_fallback_aliases", lambda *_args: ())
    monkeypatch.setattr(server, "on_job_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storage, "place_download", lambda _logical, path, **_kwargs: path)
    monkeypatch.setattr(source_resolution.state.hoster_intel, "record_download", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.state.resolved_link_cache, "invalidate", lambda *_args: None)
    def resolve(movie, _unsupported, excluded_hoster_urls=None, **_kwargs):
        result = server._HosterResult()
        hoster = movie.hosters[0]
        if hoster.url in (excluded_hoster_urls or set()):
            return result
        result.provider = movie.provider
        result.content_language = "de"
        result.hoster_used = hoster.name
        result.source_hoster_url = result.hoster_url_used = hoster.url
        result.stream_info = (f"https://cdn.example/{movie.provider}.m3u8", "hls")
        return result
    monkeypatch.setattr(server, "_extract_from_movie", resolve)
    monkeypatch.setattr(server, "DownloadJob", lambda **kwargs: SimpleNamespace(**kwargs))
    queued = []
    monkeypatch.setattr(server.state, "dl_queue", SimpleNamespace(add=queued.append, add_front=queued.append))
    assert server.run_download_queue([(primary, slug)], tmp_path, start_queue=False) == {slug}
    assert bridge.searches == []
    assert queued[0].provider == "huhu"
    queued[0].on_done(False, "CDN transfer failed")
    assert len(queued) == 2
    assert queued[1].provider == "aniworld"
    assert queued[1].queue_slug == queued[0].queue_slug == slug
    assert queued[1].content_language == "de"
    assert queued[1].out_path == queued[0].out_path
    assert server.state.queue_jobs[logical["job_id"]]["content_language"] == "de"
