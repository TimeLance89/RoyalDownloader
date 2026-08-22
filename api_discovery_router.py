"""Movie, series, anime, metadata, and discovery HTTP routes."""

# Provider adapters intentionally fail independently at this HTTP boundary.
# ruff: noqa: BLE001

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config as appconfig
from providers.catalog import provider_content_language
from providers.einschalten import EinschaltenScraper
from providers.filmfrei24 import FilmFrei24Scraper
from providers.filmo import FilmoScraper
from providers.kinoger import KinogerScraper
from providers.kinox import KinoxScraper
from providers.megakino import MegaKinoScraper
from providers.mkissa import anime_episode_page
from providers.models import FilmpalastSeriesResult
from providers.moflix import MoflixScraper
from providers.ridomovies import RidomoviesScraper
from providers.sflix import SflixScraper
from providers.xcine import XcineScraper

router = APIRouter(tags=["discovery"])

TMDB_METADATA_BATCH_BUDGET_SECONDS = 3.0
_TMDB_METADATA_POOL = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="tmdb-metadata",
)
_TMDB_METADATA_BACKGROUND_POOL = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="tmdb-metadata-background",
)
_TMDB_SERIES_METADATA_POOL = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="tmdb-series-metadata",
)
_TMDB_METADATA_INFLIGHT: dict[tuple, Any] = {}
_TMDB_METADATA_INFLIGHT_LOCK = threading.Lock()


def _discard_tmdb_metadata_future(key: tuple, future) -> None:
    with _TMDB_METADATA_INFLIGHT_LOCK:
        if _TMDB_METADATA_INFLIGHT.get(key) is future:
            _TMDB_METADATA_INFLIGHT.pop(key, None)

# Replaced by ``create_discovery_router`` before the app starts serving. The
# explicit sentinel also gives accidental standalone use a useful failure.
def _unbound_dependency(*_args, **_kwargs):
    raise RuntimeError("Discovery router dependencies are not configured")


state: Any = None
MOVIE_MAX_GLOBAL_PAGE = 0
SERIES_MAX_GLOBAL_PAGE = 0
TMDB_MOVIE_BATCH_MAX_WORKERS = 0
PROVIDER_LABELS: dict = {}
MovieCatalogColdLoadLimit = RuntimeError
SeriesCatalogColdLoadLimit = RuntimeError
_SeriesCatalogEntry = _unbound_dependency
_existing_valid_episode_path = _unbound_dependency
_norm_title = _unbound_dependency
_resolved_movie_year = _unbound_dependency
_series_catalog_sources = _unbound_dependency
_series_entry_to_dict = _unbound_dependency
_series_jellyfin_status = _unbound_dependency
_tmdb_search_results = _unbound_dependency
canonical_movie_genre = _unbound_dependency
clean_genre = _unbound_dependency
clean_movie_title = _unbound_dependency
get_fp_scraper = _unbound_dependency
get_huhu_scraper = _unbound_dependency
get_jellyfin_client = _unbound_dependency
get_jellyfin_library = _unbound_dependency
get_jellyfin_movie_identities = _unbound_dependency
get_jellyfin_series = _unbound_dependency
get_mkissa_scraper = _unbound_dependency
get_series_for_value = _unbound_dependency
get_tmdb_client = _unbound_dependency
load_movie_for_slug = _unbound_dependency
log = _unbound_dependency
merge_series_snapshots = _unbound_dependency
movie_catalog_page = _unbound_dependency
movie_detail_to_dict = _unbound_dependency
provider_for_value = _unbound_dependency
provider_priority = _unbound_dependency
series_catalog_page = _unbound_dependency
series_payload_missing_seasons = _unbound_dependency
series_search_catalog = _unbound_dependency
series_to_dict = _unbound_dependency
strip_source_suffix = _unbound_dependency

_DYNAMIC_CALLS = (
    "_existing_valid_episode_path",
    "_norm_title",
    "_resolved_movie_year",
    "_series_catalog_sources",
    "_series_entry_to_dict",
    "_series_jellyfin_status",
    "_tmdb_search_results",
    "canonical_movie_genre",
    "clean_genre",
    "clean_movie_title",
    "get_fp_scraper",
    "get_huhu_scraper",
    "get_jellyfin_client",
    "get_jellyfin_library",
    "get_jellyfin_movie_identities",
    "get_jellyfin_series",
    "get_mkissa_scraper",
    "get_series_for_value",
    "get_tmdb_client",
    "load_movie_for_slug",
    "log",
    "merge_series_snapshots",
    "movie_catalog_page",
    "movie_detail_to_dict",
    "provider_for_value",
    "provider_priority",
    "series_catalog_page",
    "series_payload_missing_seasons",
    "series_search_catalog",
    "series_to_dict",
    "strip_source_suffix",
)


def create_discovery_router(backend) -> APIRouter:
    """Bind the migration facade and return the domain router.

    Callable lookups remain dynamic so tests and runtime adapters can replace a
    provider function on the composition root without rebuilding the app.
    """

    def dynamic(name):
        return lambda *args, **kwargs: getattr(backend, name)(*args, **kwargs)

    globals().update({name: dynamic(name) for name in _DYNAMIC_CALLS})
    globals().update({
        "state": backend.state,
        "MOVIE_MAX_GLOBAL_PAGE": backend.MOVIE_MAX_GLOBAL_PAGE,
        "SERIES_MAX_GLOBAL_PAGE": backend.SERIES_MAX_GLOBAL_PAGE,
        "TMDB_MOVIE_BATCH_MAX_WORKERS": backend.TMDB_MOVIE_BATCH_MAX_WORKERS,
        "PROVIDER_LABELS": backend.PROVIDER_LABELS,
        "MovieCatalogColdLoadLimit": backend.MovieCatalogColdLoadLimit,
        "SeriesCatalogColdLoadLimit": backend.SeriesCatalogColdLoadLimit,
        "_SeriesCatalogEntry": backend._SeriesCatalogEntry,
    })
    return router


# ── Genres ──────────────────────────────────────────────────────────────────
@router.get("/api/v1/genres")
@router.get("/api/genres")
async def api_genres():
    def _work():
        loaders = {
            "filmfrei24": lambda: FilmFrei24Scraper(progress_cb=log).list_genres(),
            "filmo": lambda: FilmoScraper(progress_cb=log).list_genres(),
            "filmpalast": lambda: get_fp_scraper().list_genres(),
            "huhu": lambda: get_huhu_scraper().list_genres(),
            "moflix": lambda: MoflixScraper(progress_cb=log).list_genres(),
            "einschalten": lambda: EinschaltenScraper(progress_cb=log).list_genres(),
            "kinox": lambda: KinoxScraper(progress_cb=log).list_genres(),
            "kinoger": lambda: KinogerScraper(progress_cb=log).list_genres(),
            "megakino": lambda: MegaKinoScraper(progress_cb=log).list_genres(),
            "xcine": lambda: XcineScraper(progress_cb=log).list_genres(),
            "sflix": lambda: SflixScraper(progress_cb=log).list_genres(),
            "ridomovies": lambda: RidomoviesScraper(progress_cb=log).list_genres(),
        }
        cleaned = {provider: set() for provider in appconfig.MOVIE_PROVIDER_DEFAULTS}
        for provider in provider_priority("movies"):
            try:
                values = loaders[provider]()
            except Exception as exc:
                log(f"{PROVIDER_LABELS[provider]} Genres übersprungen: {exc}", "warn")
                continue
            cleaned[provider] = {
                clean_genre(genre)
                for genre in values
                if clean_genre(genre)
            }
        return cleaned

    provider_genres = await run_in_threadpool(_work)
    ff_c = provider_genres["filmfrei24"]
    fo_c = provider_genres["filmo"]
    fp_c = provider_genres["filmpalast"]
    hh_c = provider_genres["huhu"]
    mx_c = provider_genres["moflix"]
    es_c = provider_genres["einschalten"]
    kx_c = provider_genres["kinox"]
    kg_c = provider_genres["kinoger"]
    mk_c = provider_genres["megakino"]
    xc_c = provider_genres["xcine"]
    sf_c = provider_genres["sflix"]
    rm_c = provider_genres["ridomovies"]
    state.filmfrei24_provider_genres = ff_c
    state.filmo_provider_genres = fo_c
    state.fp_provider_genres = fp_c
    state.huhu_provider_genres = hh_c
    state.moflix_provider_genres = mx_c
    state.einschalten_provider_genres = es_c
    state.kinox_provider_genres = kx_c
    state.kinoger_provider_genres = kg_c
    state.megakino_provider_genres = mk_c
    state.xcine_provider_genres = xc_c
    state.sflix_provider_genres = sf_c
    state.ridomovies_provider_genres = rm_c
    genres = sorted(
        {
            canonical_movie_genre(genre)
            for genre in (
                ff_c | fo_c | fp_c | hh_c | mx_c | es_c | kx_c | kg_c | mk_c | xc_c | sf_c
                | rm_c
            )
            if canonical_movie_genre(genre).casefold()
            not in {"deutsch", "englisch", "english", "german"}
        },
        key=str.casefold,
    )
    return {"genres": genres}


# ── Filme: Suche / Listen / Genre ───────────────────────────────────────────
@router.get("/api/v1/movies")
@router.get("/api/movies")
async def api_movies(mode: str = "search", query: str = "", genre: str = "", page: int = 1):
    if page < 1 or page > MOVIE_MAX_GLOBAL_PAGE:
        raise HTTPException(400, f"Seite muss zwischen 1 und {MOVIE_MAX_GLOBAL_PAGE} liegen.")

    def _work():
        if mode == "search":
            q = query.strip()
            if not q:
                return {
                    "results": [], "category": None, "page": 1,
                    "has_more": False, "sources": [],
                }
            if not get_tmdb_client().configured:
                raise HTTPException(
                    503,
                    "Für die eindeutige Filmsuche muss TMDB in den Einstellungen konfiguriert sein.",
                )
            results = _tmdb_search_results(q)
            return {
                "results": results, "category": None, "page": 1,
                "has_more": False, "sources": [],
            }

        category = "genre" if mode == "genre" else mode if mode in {"new", "top"} else "new"
        try:
            catalog = movie_catalog_page(category, page, genre if category == "genre" else "")
        except MovieCatalogColdLoadLimit as exc:
            raise HTTPException(409, str(exc)) from exc
        return {**catalog, "category": category}

    data = await run_in_threadpool(_work)
    result_dicts = [
        dict(result) if isinstance(result, dict) else asdict(result)
        for result in data["results"]
    ]
    for result in result_dicts:
        if result.get("provider"):
            result["title"] = clean_movie_title(result.get("title", ""))
    # Jellyfin ist eine nachgelagerte Badge-Anreicherung. Der separate
    # /jellyfin/matches-Aufruf der Weboberflaeche aktualisiert sie asynchron;
    # eine grosse oder schlafende NAS-Bibliothek blockiert dadurch nicht mehr
    # die Filmkarten und Poster.
    return {
        "results": result_dicts,
        "category": data["category"],
        "page": data["page"],
        "page_complete": data.get("page_complete", True),
        "has_more": data["has_more"],
        # Rückwärtskompatibel für ältere Web-Builds. Semantisch ist dies jetzt
        # korrekt: Eine weitere globale Seite ist tatsächlich vorhanden.
        "last_page_full": data["has_more"],
        "sources": data["sources"],
    }


@router.get("/api/v1/movie/{slug:path}")
@router.get("/api/movie/{slug:path}")
async def api_movie(slug: str, tmdb_id: int | None = None):
    def _work():
        movie = state.fp_movies.get(slug)
        if movie is None or not getattr(movie, "hosters", None):
            movie = load_movie_for_slug(slug)
        if (
            (movie is None or not getattr(movie, "hosters", None))
            and tmdb_id is not None
            and slug.casefold() != f"tmdb:{tmdb_id}"
        ):
            try:
                movie = load_movie_for_slug(f"tmdb:{tmdb_id}")
            except (LookupError, ValueError):
                movie = None
        if movie is not None and getattr(movie, "hosters", None):
            state.fp_movies[slug] = movie
            return movie_detail_to_dict(slug, movie)
        return None

    try:
        payload = await run_in_threadpool(_work)
    except (LookupError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    if payload is None:
        raise HTTPException(
            404,
            {
                "code": "movie_hoster_unavailable",
                "message": "Aktuell ist für diesen Film kein Hoster verfügbar.",
            },
        )
    return payload


class PreloadBody(BaseModel):
    slugs: list[str]


@router.post("/api/v1/movies/preload")
@router.post("/api/movies/preload")
async def api_movies_preload(body: PreloadBody):
    def _work():
        payloads = {}
        for slug in body.slugs:
            movie = state.fp_movies.get(slug)
            if movie is None:
                movie = load_movie_for_slug(slug)
            if movie is not None:
                state.fp_movies[slug] = movie
                payloads[slug] = movie_detail_to_dict(slug, movie)
        return payloads

    payloads = await run_in_threadpool(_work)
    return {"movies": payloads}


class MovieMetadataItem(BaseModel):
    slug: str
    title: str
    year: str = ""
    tmdb_id: int | None = None
    media_type: str = "movie"


class MovieMetadataBody(BaseModel):
    items: list[MovieMetadataItem]
    background: bool = False


class SeriesMetadataItem(BaseModel):
    base_slug: str
    title: str
    year: str = ""


class SeriesMetadataBody(BaseModel):
    items: list[SeriesMetadataItem]


@router.post("/api/v1/tmdb/movie")
@router.post("/api/tmdb/movie")
async def api_tmdb_movie(item: MovieMetadataItem):
    """Vollständige TMDB-Details eines Films – ohne Anbieter-/Hoster-Aufruf."""
    if not get_tmdb_client().configured:
        return {"movie": None}
    title = clean_movie_title(item.title)
    if item.tmdb_id:
        movie = await run_in_threadpool(
            get_tmdb_client().movie_by_id, item.tmdb_id, title,
        )
    else:
        movie = await run_in_threadpool(get_tmdb_client().movie, title, item.year)
    return {"movie": movie}


@router.post("/api/v1/jellyfin/matches")
@router.post("/api/jellyfin/matches")
async def api_jellyfin_matches(body: MovieMetadataBody):
    """Liefert schnelle Bibliotheks-Badges für Filme, Serien und Anime."""
    def _work():
        client = get_jellyfin_client()
        if not client.configured:
            return {
                "configured": False, "available": True, "matches": {},
                "statuses": {item.slug: "unconfigured" for item in body.items[:100]},
            }
        requested = body.items[:100]
        needs_movies = any(item.media_type == "movie" for item in requested)
        needs_series = any(item.media_type != "movie" for item in requested)
        movie_items = get_jellyfin_movie_identities() if needs_movies else []
        series_items = get_jellyfin_series() if needs_series else []
        with state.jellyfin_cache_lock:
            movie_available = not needs_movies or bool(
                movie_items is not None and state.jellyfin_movie_identities_available
            )
            series_available = not needs_series or bool(
                series_items is not None and state.jellyfin_series_available
            )
        movie_matches = {}
        movie_requests = [item for item in requested if item.media_type == "movie"]
        match_many = getattr(client, "match_many", None)
        if movie_available and movie_requests and callable(match_many):
            batch_matches = match_many([{
                "title": clean_movie_title(item.title),
                "year": item.year,
                "tmdb_id": item.tmdb_id,
            } for item in movie_requests], items=movie_items)
            movie_matches = dict(zip(
                (item.slug for item in movie_requests), batch_matches, strict=True,
            ))
        statuses = {}
        matches = {}
        for item in requested:
            if item.media_type == "movie":
                if not movie_available:
                    statuses[item.slug] = "unavailable"
                    continue
                owned = movie_matches.get(item.slug) if callable(match_many) else client.match(
                    clean_movie_title(item.title), item.year,
                    items=movie_items, tmdb_id=item.tmdb_id,
                )
            else:
                if not series_available:
                    statuses[item.slug] = "unavailable"
                    continue
                series_ids = client.series_ids_for(
                    item.title, tmdb_id=item.tmdb_id, items=series_items,
                )
                if series_ids is None:
                    statuses[item.slug] = "ambiguous"
                    continue
                owned = bool(series_ids)
            matches[item.slug] = owned
            statuses[item.slug] = "owned" if owned else "missing"
        return {
            "configured": True,
            "available": movie_available and series_available,
            "matches": matches,
            "statuses": statuses,
        }
    return await run_in_threadpool(_work)


@router.post("/api/v1/tmdb/movies")
@router.post("/api/tmdb/movies")
async def api_tmdb_movies(body: MovieMetadataBody):
    """Lädt schnelle TMDB-Listenmetadaten parallel, ohne Hoster-Seiten."""
    if not get_tmdb_client().configured or not body.items:
        return {"movies": {}}

    def _work():
        tmdb_client = get_tmdb_client()
        cached_now_playing = getattr(tmdb_client, "cached_now_playing_ids", None)
        now_playing_ids = cached_now_playing() if callable(cached_now_playing) else set()
        unique = {}
        for item in body.items[:100]:
            title = clean_movie_title(item.title)
            key = (
                ("tmdb", str(item.tmdb_id))
                if item.tmdb_id
                else ("title", _norm_title(title), str(item.year or ""))
            )
            group = unique.setdefault(key, {
                "title": title,
                "year": item.year,
                "tmdb_id": item.tmdb_id,
                "slugs": [],
            })
            group["slugs"].append(item.slug)

        def _group_metadata(group: dict) -> dict[str, dict]:
            if group["tmdb_id"]:
                metadata = tmdb_client.movie_summary_by_id(
                    group["tmdb_id"], group["title"],
                ) or tmdb_client.movie_summary(group["title"], group["year"])
                return {slug: metadata for slug in group["slugs"] if metadata}
            if group["year"]:
                metadata = tmdb_client.movie_summary(group["title"], group["year"])
                return {slug: metadata for slug in group["slugs"] if metadata}

            wanted = _norm_title(group["title"])
            exact = [
                candidate for candidate in tmdb_client.search_movies(group["title"], max_results=20)
                if wanted in {
                    _norm_title(candidate.get("title", "")),
                    _norm_title(candidate.get("original_title", "")),
                }
            ]
            by_id = {str(candidate.get("tmdb_id") or ""): candidate for candidate in exact}
            by_id.pop("", None)
            if len(by_id) == 1:
                metadata = next(iter(by_id.values()))
                return {slug: metadata for slug in group["slugs"]}
            if len(by_id) < 2:
                metadata = tmdb_client.movie_summary(group["title"], "")
                return {slug: metadata for slug in group["slugs"] if metadata}

            # Gleicher Titel, verschiedene Filme: Die Katalogseite des
            # Anbieters ist jetzt die einzige zulässige Quelle für das Jahr.
            resolved = {}
            for slug in group["slugs"]:
                try:
                    movie = state.fp_movies.get(slug) or load_movie_for_slug(slug)
                except Exception as exc:
                    log(f"TMDB-Jahresauflösung fehlgeschlagen ({slug}): {exc}", "warn")
                    continue
                year = _resolved_movie_year(
                    getattr(movie, "title", ""), getattr(movie, "year", ""),
                ) if movie else ""
                matches = [candidate for candidate in by_id.values() if str(candidate.get("year") or "") == year]
                if year and len(matches) == 1:
                    state.fp_movies[slug] = movie
                    resolved[slug] = matches[0]
            return resolved

        result = {}
        groups = list(unique.values())
        pool = _TMDB_METADATA_BACKGROUND_POOL if body.background else _TMDB_METADATA_POOL
        futures = []
        for group in groups:
            job_key = (
                "background" if body.background else "interactive",
                str(group.get("tmdb_id") or ""),
                "" if group.get("tmdb_id") else _norm_title(group["title"]),
                str(group.get("year") or ""),
                tuple(group["slugs"]),
            )
            created = False
            with _TMDB_METADATA_INFLIGHT_LOCK:
                future = _TMDB_METADATA_INFLIGHT.get(job_key)
                if future is None:
                    future = pool.submit(_group_metadata, group)
                    _TMDB_METADATA_INFLIGHT[job_key] = future
                    created = True
            if created:
                future.add_done_callback(
                    lambda done, key=job_key: _discard_tmdb_metadata_future(key, done)
                )
            futures.append((group, future))

        done, _pending = wait(
            {future for _group, future in futures},
            timeout=TMDB_METADATA_BATCH_BUDGET_SECONDS,
        )
        for group, future in futures:
            if future not in done:
                continue
            try:
                resolved = future.result()
            except Exception as exc:
                log(f"TMDB-Vorladen fehlgeschlagen ({group['title']}): {exc}", "warn")
                resolved = {}
            for slug, metadata in resolved.items():
                metadata = {
                    **metadata,
                    "in_cinema": metadata.get("tmdb_id") in now_playing_ids,
                    "catalog_identity_version": 2,
                }
                result[slug] = metadata
        return result

    return {"movies": await run_in_threadpool(_work)}


@router.post("/api/v1/tmdb/series")
@router.post("/api/tmdb/series")
async def api_tmdb_series(body: SeriesMetadataBody):
    """Lädt Serien-Backdrops innerhalb eines festen First-Paint-Budgets."""
    if not get_tmdb_client().configured or not body.items:
        return {"series": {}, "pending": []}

    def _work():
        unique = {}
        for item in body.items[:100]:
            title = strip_source_suffix(item.title)
            key = (_norm_title(title), str(item.year or ""))
            group = unique.setdefault(
                key,
                {"title": title, "year": item.year, "base_slugs": []},
            )
            group["base_slugs"].append(item.base_slug)

        result = {}
        groups = list(unique.values())
        client = get_tmdb_client()
        futures = []
        for group in groups:
            job_key = (
                "series",
                _norm_title(group["title"]),
                str(group.get("year") or ""),
            )
            created = False
            with _TMDB_METADATA_INFLIGHT_LOCK:
                future = _TMDB_METADATA_INFLIGHT.get(job_key)
                if future is None:
                    future = _TMDB_SERIES_METADATA_POOL.submit(
                        client.series_summary,
                        group["title"],
                        group["year"],
                    )
                    _TMDB_METADATA_INFLIGHT[job_key] = future
                    created = True
            if created:
                future.add_done_callback(
                    lambda done, key=job_key: _discard_tmdb_metadata_future(key, done)
                )
            futures.append((group, future))

        done, _pending = wait(
            {future for _group, future in futures},
            timeout=TMDB_METADATA_BATCH_BUDGET_SECONDS,
        )
        pending_base_slugs = []
        for group, future in futures:
            if future not in done:
                pending_base_slugs.extend(group["base_slugs"])
                continue
            try:
                metadata = future.result()
            except Exception as exc:
                log(f"TMDB-Serienbild fehlgeschlagen ({group['title']}): {exc}", "warn")
                metadata = None
            if metadata:
                for base_slug in group["base_slugs"]:
                    result[base_slug] = metadata
        return {"series": result, "pending": pending_base_slugs}

    return await run_in_threadpool(_work)


# ── Serien ───────────────────────────────────────────────────────────────────
@router.get("/api/v1/series")
@router.get("/api/series")
async def api_series(mode: str = "search", query: str = "", letter: str = "", page: int = 1):
    if page < 1 or page > SERIES_MAX_GLOBAL_PAGE:
        raise HTTPException(400, f"Seite muss zwischen 1 und {SERIES_MAX_GLOBAL_PAGE} liegen.")

    def _work():
        if mode == "search":
            q = query.strip()
            if not q:
                return {
                    "entries": [], "direct_series": None, "mode": "search",
                    "page": 1, "has_more": False, "sources": [],
                }
            if q.startswith("http"):
                series = get_series_for_value(q)
                if series is None:
                    return {
                        "entries": [], "direct_series": None, "mode": "search",
                        "page": 1, "has_more": False, "sources": [],
                    }
                stub = FilmpalastSeriesResult(
                    title=series.title, base_slug=series.base_slug,
                    sample_slug=series.all_episodes[0].slug if series.all_episodes else "",
                    sample_url=series.url,
                )
                state.series_cache[series.base_slug] = series
                provider = provider_for_value(stub.sample_slug or stub.base_slug or stub.sample_url)
                entry = _SeriesCatalogEntry(provider, stub, (provider,))
                return {
                    "entries": [entry],
                    "direct_series": series_to_dict(series, defer_checks=True),
                    "mode": "search", "page": 1, "has_more": False,
                    "sources": _series_catalog_sources(
                        [entry], provider_priority("series"),
                    ),
                }
            try:
                catalog = series_search_catalog(q)
            except Exception as exc:
                log(f"Serien-Suche fehlgeschlagen: {exc}", "warn")
                catalog = {
                    "entries": [], "page": 1, "has_more": False, "sources": [],
                }
            return {**catalog, "direct_series": None, "mode": "search"}

        browse_mode = mode if mode in {"discover", "new", "trending", "alpha"} else "discover"
        try:
            catalog = series_catalog_page(browse_mode, page, letter)
        except SeriesCatalogColdLoadLimit as exc:
            raise HTTPException(409, str(exc)) from exc
        return {**catalog, "direct_series": None, "mode": browse_mode}

    data = await run_in_threadpool(_work)
    return {
        "results": [_series_entry_to_dict(entry) for entry in data["entries"]],
        "direct_series": data["direct_series"],
        "mode": data["mode"],
        "page": data["page"],
        "has_more": data["has_more"],
        "last_page_full": data["has_more"],
        "sources": data["sources"],
    }


class SeriesLoadBody(BaseModel):
    sample_slug: str
    base_slug: str = ""
    refresh_jellyfin: bool = False
    defer_checks: bool = False


class SeriesJellyfinEpisodeBody(BaseModel):
    slug: str = Field(min_length=1, max_length=240)
    season: int = Field(ge=0, le=100)
    episode: int = Field(ge=0, le=10000)


class SeriesJellyfinStatusBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    tmdb_id: int | None = None
    aliases: list[str] = Field(default_factory=list, max_length=30)
    episodes: list[SeriesJellyfinEpisodeBody] = Field(max_length=2000)
    force: bool = False


@router.post("/api/v1/series/jellyfin-status")
@router.post("/api/series/jellyfin-status")
async def api_series_jellyfin_status(body: SeriesJellyfinStatusBody):
    return await run_in_threadpool(
        _series_jellyfin_status,
        body.title,
        tmdb_id=body.tmdb_id or "",
        aliases=body.aliases,
        episodes=[item.model_dump() for item in body.episodes],
        force=body.force,
    )


@router.post("/api/v1/series/load")
@router.post("/api/series/load")
async def api_series_load(body: SeriesLoadBody):
    def _work():
        series = state.series_cache.get(body.base_slug) if body.base_slug else None
        if series is None:
            series = get_series_for_value(body.sample_slug)
        if series is None:
            return None, None
        payload = series_to_dict(
            series,
            refresh_jellyfin=body.refresh_jellyfin,
            defer_checks=body.defer_checks,
        )
        missing_seasons = set() if body.defer_checks else series_payload_missing_seasons(payload)
        if missing_seasons:
            log(
                f"Serienstruktur für «{series.title}» unvollständig "
                f"(fehlende Staffeln: {sorted(missing_seasons)}) – Provider wird erneut gelesen.",
                "warn",
            )
            fresh = get_series_for_value(body.sample_slug or series.url)
            series = merge_series_snapshots(series, fresh)
            if series is not None:
                payload = series_to_dict(
                    series,
                    refresh_jellyfin=body.refresh_jellyfin,
                    defer_checks=False,
                )
                missing_seasons = series_payload_missing_seasons(payload)
        if missing_seasons:
            # Einen unvollständigen Snapshot niemals sechs Stunden festhalten.
            state.series_cache.pop(series.base_slug, None)
        else:
            state.series_cache[series.base_slug] = series
        return series, payload

    series, payload = await run_in_threadpool(_work)
    if series is None:
        raise HTTPException(404, "Serie nicht gefunden.")
    return payload


# ── Anime ───────────────────────────────────────────────────────────────────
@router.get("/api/v1/anime")
@router.get("/api/anime")
async def api_anime(
    mode: str = "latest",
    query: str = "",
    page: int = 1,
):
    if page < 1 or page > 50:
        raise HTTPException(400, "Seite muss zwischen 1 und 50 liegen.")
    if "mkissa" not in provider_priority("anime"):
        return {
            "results": [],
            "mode": mode,
            "page": 1,
            "has_more": False,
            "total": 0,
            "disabled": True,
            "disabled_reason": (
                "MKissa ist pausiert. Aktiviere englische Inhalte und die "
                "Anime-Quelle in den Einstellungen."
            ),
        }
    browse_mode = mode if mode in {"search", "latest", "popular", "trending"} else "latest"
    if browse_mode == "search" and not query.strip():
        return {
            "results": [],
            "mode": browse_mode,
            "page": 1,
            "has_more": False,
            "total": 0,
            "disabled": False,
        }

    def _work():
        with state.mkissa_lock:
            return get_mkissa_scraper().browse(
                mode=browse_mode,
                query=query,
                page=page,
                limit=50,
            )

    try:
        payload = await run_in_threadpool(_work)
    except Exception as exc:
        log(f"MKissa-Katalog fehlgeschlagen: {exc}", "warn")
        raise HTTPException(502, f"MKissa ist gerade nicht erreichbar: {exc}") from exc
    return {
        **payload,
        "mode": browse_mode,
        "disabled": False,
        "provider": "mkissa",
        "provider_label": PROVIDER_LABELS["mkissa"],
        "content_language": provider_content_language("mkissa"),
    }


@router.get("/api/v1/anime/{anime_id}")
@router.get("/api/anime/{anime_id}")
async def api_anime_detail(
    anime_id: str,
    translation: str = "",
    episode_page: int = 1,
):
    if "mkissa" not in provider_priority("anime"):
        raise HTTPException(
            409,
            "MKissa ist in den Quellen oder über die Inhaltssprache deaktiviert.",
        )
    requested_track = str(translation or "").strip().casefold()

    def _work():
        with state.mkissa_lock:
            anime = get_mkissa_scraper().get_anime(anime_id)
        available = anime.translations
        track = requested_track if requested_track in available else (
            "dub" if available.get("dub") else
            "sub" if available.get("sub") else
            next(iter(available), "")
        )
        if not track:
            raise LookupError("MKissa meldet keine verfügbaren Episoden.")
        episodes = anime_episode_page(
            anime,
            track,
            page=episode_page,
            page_size=100,
        )
        for episode in episodes["episodes"]:
            slug = episode["slug"]
            episode["queued"] = slug in state.picked
            episode["downloaded"] = bool(
                _existing_valid_episode_path(
                    anime.title,
                    1,
                    int(episode["number"]),
                )
            )
        return {
            **anime.public_dict(),
            "translation": track,
            "translation_labels": {
                "dub": "English Dub",
                "sub": "English Sub",
                "raw": "Japanese Raw",
            },
            **episodes,
        }

    try:
        return await run_in_threadpool(_work)
    except (LookupError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        log(f"MKissa-Details fehlgeschlagen: {exc}", "warn")
        raise HTTPException(502, f"MKissa-Details sind nicht verfügbar: {exc}") from exc
