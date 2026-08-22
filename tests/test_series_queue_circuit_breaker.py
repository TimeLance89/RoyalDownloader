import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import server
from hoster_intel import HosterIntel
from provider_health import ProviderHealth
from resolved_link_cache import ResolvedLinkCache
from providers.models import (
    FilmpalastMovie,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    HosterInfo,
    SeriesEpisode,
)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    server.state.provider_health = ProviderHealth(
        tmp_path / "provider-health.json",
        initial_cooldown=10,
        maximum_cooldown=40,
    )
    server.state.resolved_link_cache = ResolvedLinkCache(
        tmp_path / "resolved-links.json", ttl_seconds=60,
    )
    server.state.hoster_intel = HosterIntel(tmp_path / "hoster-intel.json")
    server.state.picked.clear()
    server.state.queue_jobs.clear()
    server.state.queue_job_by_slug.clear()
    server.state.queue_history.clear()
    server.state.fp_movies.clear()
    server.state.counted_queue_slugs.clear()
    server.state.preparing_queue_slugs.clear()
    server.state.provider_waiting_jobs.clear()
    server.state.queue_content_keys.clear()
    server.state.fallback_series_cache.clear()
    server.state.fallback_provider_errors.clear()
    server.state.series_cache.clear()
    server.state.done_slugs.clear()
    server.state.total_jobs = 0
    server.state.done_jobs = 0
    monkeypatch.setattr(server, "broadcast", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_persist_queue_state", lambda: None)
    monkeypatch.setattr(server, "_ensure_provider_retry_worker", lambda: None)


def episode_movie(provider, slug, title="Exact Show S02E04", hosters=True):
    url = (
        f"https://serienstream.to/{slug}"
        if provider == "serienstream"
        else f"https://{provider}.invalid/{slug}"
    )
    return FilmpalastMovie(
        title=title,
        url=url,
        provider=provider,
        hosters=[HosterInfo("Direct", f"https://cdn.invalid/{slug}.m3u8")] if hosters else [],
    )


def test_series_preparations_share_one_scheduler_group():
    first = server._QueuePreparationJob([], Path("/tmp/one"))
    second = server._QueuePreparationJob([], Path("/tmp/two"))

    assert first.is_preparation_job is True
    assert first.host_group == second.host_group == "__series_preparation__"


def test_movie_preparation_has_priority_over_series_episode():
    movie = episode_movie("filmpalast", "movie", title="A Movie")
    episode = episode_movie(
        "serienstream", "serienstream:exact-show-s02e04",
    )
    movie_job = server._QueuePreparationJob([(movie, "filmpalast:a-movie")], Path("/tmp"))
    series_job = server._QueuePreparationJob(
        [(episode, "serienstream:exact-show-s02e04")], Path("/tmp"),
    )

    assert movie_job.queue_priority < series_job.queue_priority


def test_two_preparations_can_progress_without_global_head_of_line_blocking():
    slots = server._PreparationSlots(2)

    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    assert slots.locked()

    slots.release()
    assert slots.locked()
    slots.release()
    assert not slots.locked()


def test_serienstream_remains_first_source(monkeypatch):
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream", "filmpalast"])
    ordered = server._ordered_episode_sources([
        episode_movie("filmpalast", "fallback"),
        episode_movie("serienstream", "primary"),
    ])
    assert ordered[0].provider == "serienstream"


def test_queue_add_twenty_episodes_does_not_load_pages(monkeypatch):
    slugs = [f"serienstream:exact-show-s01e{i:02d}" for i in range(1, 21)]
    calls = []
    monkeypatch.setattr(server, "load_movie_for_slug", lambda slug: calls.append(slug))
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))
    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=slugs)))
    assert response["added"] == 20
    assert calls == []
    assert all(not server.state.fp_movies[slug].hosters for slug in slugs)


def test_queue_add_rejects_known_scheduled_episode(monkeypatch):
    slug = "serienstream:exact-show-s01e06"
    server.state.series_cache["serienstream:exact-show"] = FilmpalastSeries(
        title="Exact Show",
        base_slug="serienstream:exact-show",
        url="https://serienstream.to/serie/exact-show",
        seasons={1: [SeriesEpisode(
            1, 6, slug, "https://serienstream.to/serie/exact-show/staffel-1/episode-6",
            release_at="2099-08-12T00:00:00+02:00",
            release_label="12.08.2099 · 00:00",
        )]},
    )
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))

    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=[slug])))

    assert response["added"] == 0
    assert response["skipped_details"][slug] == "noch nicht veröffentlicht (ab 12.08.2099 · 00:00)"
    assert slug not in server.state.picked


def test_jellyfin_duplicate_protection_still_rejects_episode(monkeypatch):
    slug = "serienstream:exact-show-s01e01"
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (True, "in Jellyfin vorhanden"))
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))
    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=[slug])))
    assert response["added"] == 0
    assert response["skipped_details"][slug] == "in Jellyfin vorhanden"
    assert slug not in server.state.picked


def test_series_queue_does_not_wait_for_stale_jellyfin_status(monkeypatch):
    slug = "serienstream:exact-show-s01e02"
    waits = []
    monkeypatch.setattr(
        server,
        "_content_already_available",
        lambda *_args: (True, "Jellyfin nicht erreichbar"),
    )
    monkeypatch.setattr(
        server,
        "wait_for_jellyfin_live_ready",
        lambda: waits.append(True) or False,
    )
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))

    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=[slug])))

    assert response["added"] == 1
    assert waits == []


def test_movie_queue_waits_once_for_jellyfin_before_enqueue(monkeypatch):
    slugs = ["filmpalast:first", "filmpalast:second"]
    waits = []
    for slug in slugs:
        server.state.fp_movies[slug] = episode_movie("filmpalast", slug, title=slug)
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(
        server,
        "wait_for_jellyfin_live_ready",
        lambda: waits.append(True) or True,
    )
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))

    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=slugs)))

    assert response["added"] == 2
    assert waits == [True]


def test_movie_queue_stays_fail_closed_when_jellyfin_refresh_times_out(monkeypatch):
    slug = "filmpalast:offline"
    checks = []
    server.state.fp_movies[slug] = episode_movie("filmpalast", slug, title="Offline")
    monkeypatch.setattr(server, "wait_for_jellyfin_live_ready", lambda: False)
    monkeypatch.setattr(
        server,
        "_content_already_available",
        lambda *_args: checks.append(True) or (False, ""),
    )
    monkeypatch.setattr(server, "_enqueue_automatic_downloads", lambda values, **_kwargs: set(values))

    response = asyncio.run(server.api_queue_add(server.QueueAddBody(slugs=[slug])))

    assert response["added"] == 0
    assert "Jellyfin nicht erreichbar" in response["skipped_details"][slug]
    assert checks == []
    assert slug not in server.state.picked


def test_fallback_uses_exact_series_season_episode_and_ttl_cache(monkeypatch):
    result = FilmpalastSeriesResult(
        title="Exact Show", base_slug="filmpalast:exact", sample_slug="filmpalast:exact",
        sample_url="https://filmpalast.to/serien/exact",
    )
    series = FilmpalastSeries(
        title="Exact Show", base_slug="filmpalast:exact", url=result.sample_url,
        seasons={2: [SeriesEpisode(2, 4, "filmpalast:exact-show-s02e04", "https://x")]},
    )
    calls = {"search": 0, "load": 0}
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream", "filmpalast"])
    monkeypatch.setattr(server, "_search_series_for_provider", lambda *_args: (
        calls.__setitem__("search", calls["search"] + 1) or [
            FilmpalastSeriesResult("Exact Show Extra", "wrong", "wrong", "https://wrong"), result,
        ]
    ))
    monkeypatch.setattr(server, "_load_series_for_provider", lambda *_args: (
        calls.__setitem__("load", calls["load"] + 1) or series
    ))
    monkeypatch.setattr(server, "load_movie_for_slug", lambda slug: episode_movie("filmpalast", slug))
    first = server.find_episode_fallbacks("Exact Show", 2, 4, source_slug="serienstream:x-s02e04")
    second = server.find_episode_fallbacks("Exact Show", 2, 4, source_slug="serienstream:x-s02e04")
    missing = server.find_episode_fallbacks("Exact Show", 2, 5, source_slug="serienstream:x-s02e05")
    assert len(first) == len(second) == 1
    assert missing == []
    assert calls == {"search": 1, "load": 1}


def test_huhu_fallback_uses_known_tmdb_id_without_title_search(monkeypatch):
    series = FilmpalastSeries(
        title="Exact Show",
        base_slug="huhu:123:exact-show",
        url="https://huhu.to/item?id=123",
        seasons={2: [SeriesEpisode(2, 4, "huhu:123:exact-show-s02e04", "https://x")]},
    )
    loaded = []
    monkeypatch.setattr(
        server, "_search_series_for_provider",
        lambda *_args: (_ for _ in ()).throw(AssertionError("title search used")),
    )
    monkeypatch.setattr(
        server, "_load_series_for_provider",
        lambda provider, value: loaded.append((provider, value)) or series,
    )

    assert server._fallback_get_series("huhu", "Exact Show", tmdb_id="123") is series
    assert loaded == [("huhu", "huhu:123:tmdb")]


def test_first_exact_fallback_starts_without_searching_later_providers(monkeypatch):
    huhu_series = FilmpalastSeries(
        title="Exact Show",
        base_slug="huhu:123:exact-show",
        url="https://huhu.to/item?id=123",
        seasons={2: [SeriesEpisode(2, 4, "huhu:123:exact-show-s02e04", "https://x")]},
    )
    calls = []
    monkeypatch.setattr(
        server, "provider_priority",
        lambda _kind: ["serienstream", "huhu", "moflix"],
    )
    monkeypatch.setattr(
        server, "_fallback_get_series",
        lambda provider, *_args, **_kwargs: calls.append(provider) or huhu_series,
    )
    monkeypatch.setattr(
        server, "load_movie_for_slug",
        lambda slug: episode_movie("huhu", slug),
    )

    results = server.find_episode_fallbacks(
        "Exact Show", 2, 4,
        source_slug="serienstream:exact-show-s02e04",
        limit=1,
    )

    assert [movie.provider for movie in results] == ["huhu"]
    assert calls == ["huhu"]


def test_network_error_is_not_negative_cached(monkeypatch):
    calls = {"count": 0}

    def fail(*_args):
        calls["count"] += 1
        raise ConnectionError("temporary")

    monkeypatch.setattr(server, "_search_series_for_provider", fail)
    assert server._fallback_get_series("filmpalast", "Exact Show") is None
    assert server._fallback_get_series("filmpalast", "Exact Show") is None
    assert calls["count"] == 1


def test_transient_provider_error_expires_without_negative_series_cache(monkeypatch):
    calls = {"count": 0}
    clock = {"now": 100.0}

    def fail(*_args):
        calls["count"] += 1
        raise ConnectionError("temporary")

    monkeypatch.setattr(server.time, "time", lambda: clock["now"])
    monkeypatch.setattr(server.appconfig, "SERIES_PROVIDER_TRANSIENT_ERROR_TTL_SECONDS", 10)
    monkeypatch.setattr(server, "_search_series_for_provider", fail)
    assert server._fallback_get_series("moflix", "Exact Show") is None
    clock["now"] += 9
    assert server._fallback_get_series("moflix", "Exact Show") is None
    clock["now"] += 2
    assert server._fallback_get_series("moflix", "Exact Show") is None
    assert calls["count"] == 2


def test_without_fallback_episode_stays_waiting_not_failed():
    slug = "serienstream:exact-show-s02e04"
    movie = episode_movie("serienstream", slug, hosters=False)
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.total_jobs = 1
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    assert server._defer_provider_episode(movie, slug, Path("/tmp"))
    payload = server.build_queue_payload()
    item = payload["groups"][0]["items"][0]
    assert item["status"] == "waiting_provider"
    assert slug in server.state.picked
    assert server.state.done_jobs == 0


def test_cooldown_queue_distinguishes_fallback_checks_from_provider_waits():
    checking_slug = "serienstream:exact-show-s02e04"
    waiting_slug = "serienstream:exact-show-s02e05"
    for slug in (checking_slug, waiting_slug):
        server.state.picked.add(slug)
        server.state.counted_queue_slugs.add(slug)
        server.state.fp_movies[slug] = episode_movie(
            "serienstream", slug, hosters=False,
        )
    server.state.provider_waiting_jobs[waiting_slug] = {
        "slug": waiting_slug,
        "movie": server.state.fp_movies[waiting_slug],
    }
    server.state.preparing_queue_slugs.add(checking_slug)
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")

    payload = server.build_queue_payload()
    items = {
        item["slug"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    status = payload["providers"]["serienstream"]

    assert items[checking_slug]["status"] == "checking_fallback"
    assert items[waiting_slug]["status"] == "waiting_provider"
    assert status["fallback_episode_count"] == 1
    assert status["checking_episode_count"] == 1
    assert status["queued_fallback_episode_count"] == 0
    assert status["waiting_episode_count"] == 1


def test_healthy_provider_marks_the_current_episode_as_preparing():
    slug = "serienstream:exact-show-s02e04"
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.preparing_queue_slugs.add(slug)
    server.state.fp_movies[slug] = episode_movie(
        "serienstream", slug, hosters=False,
    )

    payload = server.build_queue_payload()
    item = payload["groups"][0]["items"][0]

    assert item["status"] == "preparing_source"


def test_waiting_episode_retries_fallback_without_serienstream_probe(
    monkeypatch, tmp_path,
):
    slug = "serienstream:exact-show-s02e04"
    movie = episode_movie("serienstream", slug, hosters=False)
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.provider_waiting_jobs[slug] = {
        "slug": slug,
        "movie": movie,
        "out_root": tmp_path,
        "movie_fallbacks": None,
    }
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    calls = []
    monkeypatch.setattr(
        server,
        "run_download_queue",
        lambda jobs, out_root, movie_fallbacks=None: calls.append(
            (jobs, out_root, movie_fallbacks)
        ) or {slug},
    )
    monkeypatch.setattr(
        server,
        "_probe_serienstream_once",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("SerienStream probe must not run")
        ),
    )

    assert server._retry_one_waiting_fallback()
    assert len(calls) == 1
    assert calls[0][0] == [(movie, slug)]
    assert slug not in server.state.provider_waiting_jobs
    assert slug not in server.state.preparing_queue_slugs
    assert not server.state.queue_prepare_lock.locked()


def test_waiting_episode_claim_survives_queue_persistence(monkeypatch, tmp_path):
    slug = "serienstream:exact-show-s02e04"
    queue_file = tmp_path / "download_queue.json"
    monkeypatch.setattr(server.appconfig, "_queue_file", lambda: queue_file)
    monkeypatch.setattr(server.appconfig, "_config_dir", lambda: tmp_path)
    assert server.appconfig.save_queue({slug})
    assert server.appconfig.load_queue() == [slug]


def test_remove_waiting_episode_removes_delayed_retry():
    slug = "serienstream:exact-show-s02e04"
    movie = episode_movie("serienstream", slug, hosters=False)
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.provider_waiting_jobs[slug] = {"slug": slug, "movie": movie}
    server._release_removed_queue_slugs({slug})
    assert slug not in server.state.picked
    assert slug not in server.state.provider_waiting_jobs
    assert slug not in server.state.counted_queue_slugs


def test_successful_probe_reuses_resolved_url(monkeypatch):
    slug = "serienstream:exact-show-s02e04"
    movie = FilmpalastMovie(
        title="Exact Show S02E04",
        url="https://serienstream.to/episode",
        provider="serienstream",
        hosters=[HosterInfo("VOE", "https://serienstream.to/r?t=one")],
    )
    calls = {"count": 0}
    scraper = SimpleNamespace(
        reset_gate=lambda: None,
        is_redirect_url=server.SerienstreamScraper.is_redirect_url,
        resolve_play_url=lambda *_args, **_kwargs: (
            calls.__setitem__("count", calls["count"] + 1) or "https://voe.invalid/e/one"
        ),
        last_block_reason="",
    )
    monkeypatch.setattr(server, "get_sto_scraper", lambda: scraper)
    item = {"slug": slug, "movie": movie}
    assert server._probe_serienstream_once(item)
    assert calls["count"] == 1
    assert movie.hosters[0].url == "https://serienstream.to/r?t=one"
    assert server.state.resolved_link_cache.get(movie.hosters[0].url) == (
        "https://voe.invalid/e/one"
    )


def test_cached_redirect_works_during_provider_cooldown(monkeypatch):
    redirect = "https://serienstream.to/r?t=one"
    target = "https://hoster.invalid/embed/one"
    movie = FilmpalastMovie(
        title="Exact Show S02E04",
        url="https://serienstream.to/episode",
        provider="serienstream",
        hosters=[HosterInfo("Generic", redirect)],
    )
    server.state.resolved_link_cache.put(redirect, target)
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    monkeypatch.setattr(
        server,
        "get_sto_scraper",
        lambda: (_ for _ in ()).throw(AssertionError("SerienStream requested")),
    )
    monkeypatch.setattr(server, "probe_stream_url", lambda *_args, **_kwargs: (True, "ok"))
    result = server._extract_from_movie(movie, set())
    assert result.stream_info == (target, "web")
    assert result.resolved_from_cache
    assert result.gated


def test_redirect_is_resolved_once_then_reused(monkeypatch):
    redirect = "https://serienstream.to/r?t=once"
    target = "https://hoster.invalid/embed/once"
    movie = FilmpalastMovie(
        title="Exact Show S02E05",
        url="https://serienstream.to/episode-5",
        provider="serienstream",
        hosters=[HosterInfo("Generic", redirect)],
    )
    calls = {"count": 0}
    scraper = SimpleNamespace(
        gated=False,
        last_block_reason="",
        resolve_play_url=lambda *_args, **_kwargs: (
            calls.__setitem__("count", calls["count"] + 1) or target
        ),
    )
    monkeypatch.setattr(server, "get_sto_scraper", lambda: scraper)
    monkeypatch.setattr(server, "probe_stream_url", lambda *_args, **_kwargs: (True, "ok"))
    first = server._extract_from_movie(movie, set())
    second = server._extract_from_movie(movie, set())
    assert first.stream_info == second.stream_info == (target, "web")
    assert not first.resolved_from_cache
    assert second.resolved_from_cache
    assert calls["count"] == 1


def test_parallel_redirect_attempts_share_one_resolution(monkeypatch):
    redirect = "https://serienstream.to/r?t=parallel"
    target = "https://hoster.invalid/embed/parallel"
    movie = FilmpalastMovie(
        title="Exact Show S02E06",
        url="https://serienstream.to/episode-6",
        provider="serienstream",
        hosters=[HosterInfo("Generic", redirect)],
    )
    calls = {"count": 0}
    scraper = SimpleNamespace(
        gated=False,
        last_block_reason="",
        resolve_play_url=lambda *_args, **_kwargs: (
            calls.__setitem__("count", calls["count"] + 1) or target
        ),
    )
    original_get = server.state.resolved_link_cache.get
    first_reads = threading.local()
    both_started = threading.Barrier(2)

    def synchronized_get(url):
        count = getattr(first_reads, "count", 0)
        first_reads.count = count + 1
        if count == 0:
            both_started.wait(timeout=2)
        return original_get(url)

    monkeypatch.setattr(server.state.resolved_link_cache, "get", synchronized_get)
    monkeypatch.setattr(server, "get_sto_scraper", lambda: scraper)
    monkeypatch.setattr(server, "probe_stream_url", lambda *_args, **_kwargs: (True, "ok"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: server._extract_from_movie(movie, set()), range(2)))

    assert [result.stream_info for result in results] == [(target, "web")] * 2
    assert calls["count"] == 1


def test_manual_retry_rejects_parallel_probe():
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    assert server.state.provider_health.begin_probe("serienstream", force=True)
    with pytest.raises(server.HTTPException) as error:
        asyncio.run(server.api_serienstream_retry())
    assert error.value.status_code == 409


def test_successful_fallback_is_enqueued_normally(monkeypatch, tmp_path):
    slug = "serienstream:exact-show-s02e04"
    primary = episode_movie("serienstream", slug, hosters=False)
    fallback = episode_movie("filmpalast", "fallback-s02e04")
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    monkeypatch.setattr(server, "find_episode_fallbacks", lambda *_args, **_kwargs: [fallback])
    def extract(movie, *_args, **_kwargs):
        return SimpleNamespace(
            stream_info=("https://cdn.invalid/video.m3u8", "hls") if movie.provider == "filmpalast" else None,
            gated=movie.provider == "serienstream",
            provider=movie.provider,
            content_language="de",
            hoster_used="Direct",
            hoster_url_used="https://cdn.invalid/video.m3u8",
            source_hoster_url="https://cdn.invalid/video.m3u8",
            referer=movie.url,
            origin="https://cdn.invalid",
            quality="HD",
        )

    monkeypatch.setattr(server, "_extract_from_movie", extract)
    enqueued = []
    monkeypatch.setattr(server, "_enqueue_hoster_attempt", lambda **kwargs: enqueued.append(kwargs["movie"]) or True)
    queued = server.run_download_queue([(primary, slug)], tmp_path, start_queue=False)
    assert queued == {slug}
    assert enqueued[0].provider == "filmpalast"
    assert slug not in server.state.provider_waiting_jobs


def test_empty_prepared_episode_fallbacks_do_not_suppress_live_moflix_search(
    monkeypatch, tmp_path,
):
    slug = "serienstream:exact-show-s02e04"
    primary = episode_movie("serienstream", slug, hosters=False)
    moflix = episode_movie("moflix", "exact-show-s02e04")
    server.state.picked.add(slug)
    server.state.counted_queue_slugs.add(slug)
    server.state.provider_health.mark_blocked("serienstream", "captcha_gate")
    monkeypatch.setattr(server, "_content_already_available", lambda *_args: (False, ""))
    searches = []

    def find(*_args, **_kwargs):
        searches.append((_args, _kwargs))
        return [moflix]

    monkeypatch.setattr(server, "find_episode_fallbacks", find)

    def extract(movie, *_args, **_kwargs):
        return SimpleNamespace(
            stream_info=("https://cdn.invalid/video.m3u8", "hls")
            if movie.provider == "moflix" else None,
            gated=movie.provider == "serienstream",
            provider=movie.provider,
            content_language="de",
            hoster_used="Direct",
            hoster_url_used="https://cdn.invalid/video.m3u8",
            source_hoster_url="https://cdn.invalid/video.m3u8",
            referer=movie.url,
            origin="https://cdn.invalid",
            quality="HD",
        )

    monkeypatch.setattr(server, "_extract_from_movie", extract)
    enqueued = []
    monkeypatch.setattr(
        server, "_enqueue_hoster_attempt",
        lambda **kwargs: enqueued.append(kwargs["movie"]) or True,
    )
    queued = server.run_download_queue(
        [(primary, slug)], tmp_path, movie_fallbacks={slug: []}, start_queue=False,
    )
    assert queued == {slug}
    assert len(searches) == 1
    assert enqueued[0].provider == "moflix"
