"""Movie provider routing, matching, and catalog services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# Eine Katalogantwort ist interaktiv. Langsame Anbieter duerfen ihre Futures
# weiter im Hintergrund fuellen, aber nicht den sichtbaren Film-Tab blockieren.
MOVIE_CATALOG_PAGE_BUDGET_SECONDS = 4.0
_MOVIE_PROVIDER_LOAD_POOL = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="movie-catalog",
)
_MOVIE_PROVIDER_INFLIGHT = {}
_MOVIE_PROVIDER_INFLIGHT_LOCK = threading.Lock()
_MOVIE_CATALOG_PREFETCH_POOL = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="movie-prefetch",
)
_MOVIE_CATALOG_PREFETCH_INFLIGHT = set()
_MOVIE_CATALOG_PREFETCH_LOCK = threading.Lock()


def strip_source_suffix(title: str) -> str:
    """Entfernt die UI-Markierung ``[Anbieter]``."""
    return re.sub(r"\s*\[[^\]]+\]\s*$", "", title or "").strip()


def clean_movie_title(title: str) -> str:
    """Bereinigt Filmtitel für Anzeige, TMDB und Jellyfin.

    Quellseiten hängen teils Editionen oder Sprachmarker an, etwa
    ``(Black and Chrome Edition) [Moflix]`` oder ``ENGLISH\\Titel``.
    """
    value = " ".join(str(title or "").split()).strip()
    language = r"(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI(?:LANGUAGE)?|OV|O-TON)"
    previous = None
    while value and value != previous:
        previous = value
        value = strip_source_suffix(value)
        value = re.sub(r"\s*\([^()]*\)\s*$", "", value).strip()
        value = re.sub(
            rf"^[\\/|:_-]*\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]+\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            rf"\s*[\\/|:_-]+\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]*\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        # Ein alleinstehender, großgeschriebener Release-Marker am Ende ist
        # ebenfalls kein Titelbestandteil. Normales „English Movie“ bleibt.
        value = re.sub(
            r"\s+(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI|OV|O-TON)"
            r"(?:\s+(?:DUB|SUB|DL))?\s*$",
            "",
            value,
        ).strip()
    return value


def provider_order(media_type: str) -> List[str]:
    defaults = {
        "movies": appconfig.MOVIE_PROVIDER_DEFAULTS,
        "series": appconfig.SERIES_PROVIDER_DEFAULTS,
        "anime": appconfig.ANIME_PROVIDER_DEFAULTS,
    }.get(media_type, ())
    with state.provider_priority_lock:
        configured = state.provider_priorities.get(media_type, defaults)
        return appconfig.normalize_provider_order(configured, defaults)


def provider_priority(media_type: str) -> List[str]:
    """Aktive, sprachlich passende Quellen in Benutzer-Reihenfolge."""
    ordered = provider_order(media_type)
    with state.provider_priority_lock:
        configured = state.provider_enabled.get(media_type, ordered)
        enabled = set(appconfig.normalize_provider_selection(configured, ordered))
        languages = set(state.content_languages)
    matching = [
        provider
        for provider in ordered
        if provider_content_language(provider) in languages
    ]
    active = [provider for provider in matching if provider in enabled]
    if media_type == "anime":
        return active
    return active or matching[:1] or ordered[:1]


def provider_for_value(value: str) -> str:
    """Erkennt die Katalogquelle an den zentral hinterlegten Merkmalen."""
    return provider_for_source(value)


def _apply_provider_metadata(item, provider: str):
    """Ergänzt normalisierte Medienobjekte um Quelle und Standardsprache."""
    if item is None:
        return None
    key = str(provider or "").strip().casefold()
    if hasattr(item, "provider"):
        item.provider = key
    if hasattr(item, "content_language"):
        item.content_language = provider_content_language(key)
    return item


def _apply_provider_metadata_many(items, provider: str) -> list:
    return [
        _apply_provider_metadata(item, provider)
        for item in (items or [])
        if item is not None
    ]


def _movie_provider(movie: Optional[FilmpalastMovie], fallback: str = "") -> str:
    stored = str(getattr(movie, "provider", "") or "").strip().casefold()
    if stored in PROVIDER_CATALOG:
        return stored
    value = getattr(movie, "url", "") if movie is not None else fallback
    return provider_for_value(value or fallback)


def _movie_content_language(
    movie: Optional[FilmpalastMovie],
    hoster_language: str = "",
    fallback: str = "",
) -> str:
    explicit = normalize_content_language(hoster_language)
    if explicit:
        return explicit
    if movie is not None:
        stored = normalize_content_language(
            str(getattr(movie, "content_language", "") or "")
        )
        if stored:
            return stored
    return provider_content_language(_movie_provider(movie, fallback))


def _ordered_episode_sources(movies: List[FilmpalastMovie]) -> List[FilmpalastMovie]:
    positions = {provider: index for index, provider in enumerate(provider_priority("series"))}
    return sorted(
        movies,
        key=lambda movie: positions.get(provider_for_value(movie.url), len(positions)),
    )


def clean_genre(value: str) -> str:
    return " ".join(str(value or "").split())


def canonical_movie_genre(value: str) -> str:
    genre = clean_genre(value)
    return MOVIE_GENRE_CANONICAL_BY_KEY.get(genre.casefold(), genre)


def movie_genre_aliases(value: str) -> tuple[str, ...]:
    canonical = canonical_movie_genre(value)
    return MOVIE_GENRE_GROUPS.get(canonical, (canonical,))


def watchlist_lookup(base_slug: str) -> Optional[dict]:
    return next((w for w in state.watchlist if w["base_slug"] == base_slug), None)


def watchlist_match_series(
    base_slug: str, title: str = "", tmdb_id="", aliases=(),
) -> Optional[dict]:
    """Ordnet dieselbe Serie providerübergreifend ihrer Watchlist zu."""
    exact = watchlist_lookup(base_slug)
    if exact is not None:
        return exact
    wanted_tmdb = str(tmdb_id or "").strip()
    if wanted_tmdb:
        tmdb_matches = [
            entry for entry in state.watchlist
            if str(entry.get("tmdb_id") or "").strip() == wanted_tmdb
        ]
        if len(tmdb_matches) == 1:
            return tmdb_matches[0]
    wanted_titles = {
        _norm_title(value) for value in (title, *aliases) if _norm_title(value)
    }
    if not wanted_titles:
        return None
    title_matches = []
    for entry in state.watchlist:
        stored_tmdb = str(entry.get("tmdb_id") or "").strip()
        if wanted_tmdb and stored_tmdb and stored_tmdb != wanted_tmdb:
            continue
        stored_titles = {
            _norm_title(value)
            for value in (entry.get("title", ""), *(entry.get("aliases") or []))
            if _norm_title(value)
        }
        if wanted_titles & stored_titles:
            title_matches.append(entry)
    return title_matches[0] if len(title_matches) == 1 else None


def load_movie_for_slug(slug: str) -> Optional[FilmpalastMovie]:
    if re.fullmatch(r"tmdb:\d+", slug or "", flags=re.IGNORECASE):
        sources = resolve_tmdb_movie_sources(slug.split(":", 1)[1])
        return sources[0] if sources else None
    provider = provider_for_value(slug)
    if slug.startswith(FILMFREI24_PREFIX):
        movie = FilmFrei24Scraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(FILMO_PREFIX):
        movie = FilmoScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(SERIENSTREAM_PREFIX):
        if not state.provider_health.request_allowed("serienstream"):
            raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
        with state.sto_lock:
            try:
                movie = get_sto_scraper().get_movie(slug)
            except ProviderBlockedError as exc:
                _mark_serienstream_blocked(exc.reason, str(exc))
                raise
    elif slug.startswith(MOFLIX_PREFIX):
        with state.moflix_lock:
            movie = get_moflix_scraper().get_movie(slug)
    elif slug.startswith((HUHU_PREFIX, HUHU_MOVIE_PREFIX)):
        with state.huhu_lock:
            movie = get_huhu_scraper().get_movie(slug)
    elif slug.startswith(EINSCHALTEN_PREFIX):
        movie = EinschaltenScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(KINOX_PREFIX):
        movie = KinoxScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(KINOGER_PREFIX):
        movie = KinogerScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(MEGAKINO_PREFIX):
        movie = MegaKinoScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(XCINE_PREFIX):
        movie = XcineScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(SFLIX_PREFIX):
        movie = SflixScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(RIDOMOVIES_PREFIX):
        movie = RidomoviesScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(MKISSA_PREFIX):
        with state.mkissa_lock:
            movie = get_mkissa_scraper().get_episode(slug)
    else:
        if slug.lower().startswith(("http://", "https://")):
            host = (urlparse(slug).hostname or "").casefold()
            if host != "filmpalast.to" and not host.endswith(".filmpalast.to"):
                raise ValueError("Direkte URLs sind nur für Filmpalast erlaubt.")
        scraper = get_fp_scraper()
        with state.fp_lock:
            movie = scraper.get_movie(slug)
    return _apply_provider_metadata(movie, provider)


def search_movie_candidates(query: str) -> List[FilmpalastSearchResult]:
    """Durchsucht alle Filmanbieter; gemeinsame Basis für Web und Telegram."""
    q = query.strip()
    if not q:
        return []
    def _fp():
        with state.fp_lock:
            return list(get_fp_scraper().search(q))

    def _huhu():
        with state.huhu_lock:
            return list(get_huhu_scraper().search(q))

    searches = {
        "filmfrei24": lambda: FilmFrei24Scraper(progress_cb=log).search(q),
        "filmo": lambda: FilmoScraper(progress_cb=log).search(q),
        "filmpalast": _fp,
        "huhu": _huhu,
        "moflix": lambda: MoflixScraper(progress_cb=log).search(q),
        "einschalten": lambda: EinschaltenScraper(progress_cb=log).search(q),
        "kinox": lambda: KinoxScraper(progress_cb=log).search(q),
        "kinoger": lambda: KinogerScraper(progress_cb=log).search(q),
        "megakino": lambda: MegaKinoScraper(progress_cb=log).search(q),
        "xcine": lambda: XcineScraper(progress_cb=log).search(q),
        "sflix": lambda: SflixScraper(progress_cb=log).search(q),
        "ridomovies": lambda: RidomoviesScraper(progress_cb=log).search(q),
    }
    tasks = [
        (key, PROVIDER_LABELS[key], searches[key])
        for key in provider_priority("movies")
    ]
    results: List[FilmpalastSearchResult] = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [(key, name, pool.submit(fn)) for key, name, fn in tasks]
        for key, name, future in futures:
            try:
                results.extend(_apply_provider_metadata_many(future.result(), key))
            except Exception as exc:
                log(f"{name} Suche übersprungen: {exc}", "warn")
    return results


def _tmdb_search_results(query: str) -> List[dict]:
    """Formatiert TMDB-Treffer als providerunabhängige Filmkarten."""
    movies = get_tmdb_client().search_movies(
        query, max_results=TMDB_MOVIE_SEARCH_MAX_RESULTS,
    )
    return [
        {
            **movie,
            "slug": f"tmdb:{movie['tmdb_id']}",
            "url": f"https://www.themoviedb.org/movie/{movie['tmdb_id']}",
            "is_movie": True,
            "provider": "",
            "content_language": "",
        }
        for movie in movies
    ]


_MOVIE_YEAR_SUFFIX_RE = re.compile(
    r"\s*[\(\[\{*]?\s*((?:19|20)\d{2})\s*[\)\]\}*]?\s*$"
)


def _movie_year_from_title(title: str) -> str:
    match = _MOVIE_YEAR_SUFFIX_RE.search(clean_movie_title(title))
    return match.group(1) if match else ""


def _resolved_movie_year(title: str, year: str = "") -> str:
    return str(year or "").strip() or _movie_year_from_title(title)


def _movie_title_match_keys(title: str) -> set[str]:
    raw = _MOVIE_YEAR_SUFFIX_RE.sub("", clean_movie_title(title)).strip()
    def _match_norm(value: str) -> str:
        ascii_value = (
            unicodedata.normalize("NFKD", value or "")
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())

    keys = {_match_norm(raw)}
    roman_to_number = {
        "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
        "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    }
    match = re.search(r"\b(i{1,3}|iv|v|vi{0,3}|ix|x|\d{1,2})$", raw, re.IGNORECASE)
    if match:
        suffix = match.group(1).casefold()
        replacement = roman_to_number.get(suffix)
        if replacement:
            keys.add(_match_norm(raw[:match.start()] + replacement))
        elif suffix.isdigit():
            number_to_roman = {value: key for key, value in roman_to_number.items()}
            roman = number_to_roman.get(str(int(suffix)))
            if roman:
                keys.add(_match_norm(raw[:match.start()] + roman))
    keys.discard("")
    return keys


def _movie_matches_tmdb_choice(
    title: str,
    year: str,
    aliases: set[str],
    wanted_year: str,
) -> bool:
    if not (_movie_title_match_keys(title) & aliases):
        return False
    candidate_year = _resolved_movie_year(title, year)
    return not (wanted_year and candidate_year and candidate_year != wanted_year)


def resolve_tmdb_movie_sources(tmdb_id) -> List[FilmpalastMovie]:
    """Sucht einen gewählten TMDB-Film bei allen aktiven Filmquellen.

    Das Ergebnis bleibt ein logischer Inhalt. Die erste Quelle folgt der
    Nutzerpriorität; jede weitere Quelle wird als echter Download-Fallback
    gespeichert und später automatisch durchprobiert.
    """
    key = str(tmdb_id or "").strip()
    if not key.isdigit():
        raise ValueError("Ungültige TMDB-Film-ID.")
    virtual_slug = f"tmdb:{int(key)}"
    with state.movie_source_cache_lock:
        cached = state.movie_source_cache.get(virtual_slug)
        if cached:
            return list(cached)

    tmdb = get_tmdb_client().movie_by_id(key)
    if not tmdb:
        raise LookupError("Der gewählte TMDB-Film ist nicht verfügbar.")
    search_titles = []
    for value in (tmdb.get("title"), tmdb.get("original_title")):
        value = " ".join(str(value or "").split()).strip()
        if value and _norm_title(value) not in {_norm_title(item) for item in search_titles}:
            search_titles.append(value)
    if not search_titles:
        raise LookupError("TMDB liefert keinen suchbaren Filmtitel.")

    aliases = {
        key
        for title in search_titles
        for key in _movie_title_match_keys(title)
    }
    wanted_year = str(tmdb.get("year") or "").strip()
    candidates: List[FilmpalastSearchResult] = []
    seen_candidates: set[str] = set()
    provider_candidate_counts: Counter = Counter()
    for search_title in search_titles:
        for candidate in search_movie_candidates(search_title):
            provider = str(candidate.provider or provider_for_value(candidate.slug)).casefold()
            if provider_candidate_counts[provider] >= 3 or candidate.slug in seen_candidates:
                continue
            if not candidate.is_movie or not _movie_matches_tmdb_choice(
                candidate.title, candidate.year, aliases, wanted_year,
            ):
                continue
            seen_candidates.add(candidate.slug)
            candidates.append(candidate)
            provider_candidate_counts[provider] += 1

    def _load(candidate: FilmpalastSearchResult):
        try:
            loaded = state.fp_movies.get(candidate.slug) or load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"Filmquelle {candidate.title} nicht ladbar: {exc}", "warn")
            return None
        if not loaded or not loaded.hosters:
            return None
        loaded_year = _resolved_movie_year(
            loaded.title, loaded.year or candidate.year,
        )
        if wanted_year and not loaded_year:
            return None
        if not _movie_matches_tmdb_choice(loaded.title, loaded_year, aliases, wanted_year):
            return None
        state.fp_movies[candidate.slug] = loaded
        return loaded

    loaded_sources: List[FilmpalastMovie] = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            loaded_sources = [
                movie for movie in pool.map(_load, candidates)
                if movie is not None
            ]

    positions = {
        provider: index for index, provider in enumerate(provider_priority("movies"))
    }
    loaded_sources.sort(
        key=lambda movie: positions.get(_movie_provider(movie), len(positions)),
    )
    unique_sources: List[FilmpalastMovie] = []
    seen_providers: set[str] = set()
    for movie in loaded_sources:
        provider = _movie_provider(movie)
        if provider in seen_providers:
            continue
        seen_providers.add(provider)
        unique_sources.append(movie)
    if not unique_sources:
        raise LookupError(
            f"«{tmdb.get('title') or search_titles[0]}» wurde bei keinem aktiven Anbieter gefunden."
        )

    primary = replace(
        unique_sources[0],
        title=tmdb.get("title") or unique_sources[0].title,
        year=wanted_year or unique_sources[0].year,
        runtime=tmdb.get("runtime") or unique_sources[0].runtime,
        cover_url=tmdb.get("cover_url") or unique_sources[0].cover_url,
        description=tmdb.get("description") or unique_sources[0].description,
        genres=tmdb.get("genres") or unique_sources[0].genres,
    )
    sources = [primary, *unique_sources[1:]]
    with state.movie_source_cache_lock:
        existing = state.movie_source_cache.get(virtual_slug)
        if existing:
            return list(existing)
        state.movie_source_cache[virtual_slug] = list(sources)
        state.fp_movies[virtual_slug] = primary
    log(
        f"TMDB-Film «{primary.title}»: {len(sources)} Anbieterquelle(n) gebündelt."
    )
    return sources


class MovieCatalogColdLoadLimit(RuntimeError):
    """Verhindert teure Sprünge über viele noch ungecachte Quellseiten."""


def _movie_provider_page_cache_state(
    cache_key: tuple,
) -> tuple[Optional[List[FilmpalastSearchResult]], str]:
    """Liefert eine frische oder noch brauchbare veraltete Providerseite."""
    with state.movie_list_cache_lock:
        cached = state.movie_list_cache.get(cache_key)
        ttl = cached[2] if cached and len(cached) > 2 else MOVIE_LIST_CACHE_TTL
        age = time.time() - cached[0] if cached else 0.0
        if cached and age < ttl:
            return list(cached[1]), "fresh"
        if cached and age < MOVIE_LIST_STALE_TTL:
            return list(cached[1]), "stale"
        if cached:
            state.movie_list_cache.pop(cache_key, None)
    return None, "missing"


def _cached_movie_provider_page(cache_key: tuple) -> Optional[List[FilmpalastSearchResult]]:
    results, freshness = _movie_provider_page_cache_state(cache_key)
    return results if freshness == "fresh" else None


def _cache_movie_provider_page(
    cache_key: tuple,
    results: List[FilmpalastSearchResult],
    ttl: int = MOVIE_LIST_CACHE_TTL,
) -> None:
    now = time.time()
    with state.movie_list_cache_lock:
        expired = [
            key for key, cached in state.movie_list_cache.items()
            if now - cached[0] >= MOVIE_LIST_STALE_TTL
        ]
        for key in expired:
            state.movie_list_cache.pop(key, None)
        while len(state.movie_list_cache) >= MOVIE_LIST_CACHE_MAX_ENTRIES:
            oldest = min(state.movie_list_cache, key=lambda key: state.movie_list_cache[key][0])
            state.movie_list_cache.pop(oldest, None)
        state.movie_list_cache[cache_key] = (now, list(results), ttl)


def _fetch_movie_provider_page(
    provider: str,
    mode: str,
    genre: str,
    source_page: int,
) -> List[FilmpalastSearchResult]:
    """Lädt genau eine Quellseite; nur markierte Anbieter paginieren."""
    if provider not in MOVIE_PAGINATED_PROVIDERS and source_page != 1:
        return []
    provider_genre = _movie_genre_for_provider(provider, genre) if mode == "genre" else genre

    if provider == "filmpalast":
        with state.fp_lock:
            scraper = get_fp_scraper()
            if mode == "genre":
                results = scraper.list_by_genre(provider_genre, source_page)
            else:
                results = scraper.list_movies(mode, source_page)
        return _apply_provider_metadata_many(results, provider)

    if provider == "huhu":
        with state.huhu_lock:
            scraper = get_huhu_scraper()
            results = (
                scraper.list_by_genre(provider_genre, source_page)
                if mode == "genre"
                else scraper.list_movies(mode, source_page)
            )
        return _apply_provider_metadata_many(results, provider)

    scraper_classes = {
        "filmfrei24": FilmFrei24Scraper,
        "filmo": FilmoScraper,
        "moflix": MoflixScraper,
        "einschalten": EinschaltenScraper,
        "kinox": KinoxScraper,
        "kinoger": KinogerScraper,
        "megakino": MegaKinoScraper,
        "xcine": XcineScraper,
        "sflix": SflixScraper,
        "ridomovies": RidomoviesScraper,
    }
    scraper_class = scraper_classes.get(provider)
    if scraper_class is None:
        return []
    scraper = scraper_class(progress_cb=log)
    if mode == "genre":
        results = scraper.list_by_genre(provider_genre, source_page)
    else:
        results = scraper.list_movies(mode, source_page)
    return _apply_provider_metadata_many(results, provider)


def _load_movie_provider_pages(
    mode: str,
    genre: str,
    requests_to_load: List[tuple[str, int]],
    cold_wave_budget: Optional[List[int]] = None,
    deadline: Optional[float] = None,
    timed_out: Optional[List[bool]] = None,
) -> Dict[tuple[str, int], List[FilmpalastSearchResult]]:
    """Lädt mehrere Quellseiten parallel und cached sie unabhängig voneinander."""
    loaded: Dict[tuple[str, int], List[FilmpalastSearchResult]] = {}
    missing: List[tuple[str, int, tuple]] = []
    stale: List[tuple[str, int, tuple, List[FilmpalastSearchResult]]] = []
    genre_key = clean_genre(genre).casefold()

    for provider, source_page in dict.fromkeys(requests_to_load):
        cache_key = ("provider", mode, genre_key, provider, int(source_page))
        cached, freshness = _movie_provider_page_cache_state(cache_key)
        if freshness == "missing":
            missing.append((provider, source_page, cache_key))
        else:
            loaded[(provider, source_page)] = list(cached or [])
            if freshness == "stale":
                stale.append((provider, source_page, cache_key, list(cached or [])))

    if not missing and not stale:
        return loaded
    if missing and cold_wave_budget is not None:
        if cold_wave_budget[0] <= 0:
            raise MovieCatalogColdLoadLimit(
                "Dieser Katalogabschnitt wird noch vorbereitet. Bitte kurz warten und erneut versuchen."
            )
        cold_wave_budget[0] -= 1

    deadline = deadline or (time.monotonic() + MOVIE_CATALOG_PAGE_BUDGET_SECONDS)

    def complete_provider_load(
        future, provider, source_page, cache_key, stale_fallback=None,
    ):
        try:
            results = list(future.result())
        except Exception as exc:
            label = PROVIDER_LABELS.get(provider, provider)
            log(f"{label} Liste (Quellseite {source_page}) übersprungen: {exc}", "warn")
            results = list(stale_fallback or [])
            _cache_movie_provider_page(
                cache_key, results, ttl=MOVIE_LIST_FAILURE_CACHE_TTL,
            )
        else:
            _cache_movie_provider_page(cache_key, results)
        finally:
            with _MOVIE_PROVIDER_INFLIGHT_LOCK:
                if _MOVIE_PROVIDER_INFLIGHT.get(cache_key) is future:
                    _MOVIE_PROVIDER_INFLIGHT.pop(cache_key, None)

    futures = []
    work = [
        (provider, source_page, cache_key, None, True)
        for provider, source_page, cache_key in missing
    ] + [
        (provider, source_page, cache_key, fallback, False)
        for provider, source_page, cache_key, fallback in stale
    ]
    for provider, source_page, cache_key, stale_fallback, should_wait in work:
        created = False
        with _MOVIE_PROVIDER_INFLIGHT_LOCK:
            future = _MOVIE_PROVIDER_INFLIGHT.get(cache_key)
            if future is None:
                future = _MOVIE_PROVIDER_LOAD_POOL.submit(
                    _fetch_movie_provider_page, provider, mode, genre, source_page,
                )
                _MOVIE_PROVIDER_INFLIGHT[cache_key] = future
                created = True
        if created:
            future.add_done_callback(
                lambda done, p=provider, s=source_page, key=cache_key,
                fallback=stale_fallback:
                complete_provider_load(done, p, s, key, fallback)
            )
        if should_wait:
            futures.append((provider, source_page, cache_key, future))

    # Stale-while-revalidate: Der bekannte Katalog ist bereits vollstaendig
    # sichtbar. Nur echte Cache-Misses gehoeren in das Request-Zeitbudget.
    if not futures:
        return loaded

    remaining = max(0.0, deadline - time.monotonic())
    done, pending = wait({future for *_meta, future in futures}, timeout=remaining)
    if pending:
        if timed_out is not None:
            timed_out[0] = True
        labels = sorted({
            PROVIDER_LABELS.get(provider, provider)
            for provider, _source_page, _cache_key, future in futures
            if future in pending
        })
        log(
            "Filmkatalog-Zeitbudget erreicht; lädt im Hintergrund weiter: "
            + ", ".join(labels),
            "warn",
        )

    for provider, source_page, _cache_key, future in futures:
        if future not in done:
            continue
        try:
            loaded[(provider, source_page)] = list(future.result())
        except Exception:
            loaded[(provider, source_page)] = []
    return loaded


def _schedule_movie_provider_prefetch(
    mode: str,
    genre: str,
    requests_to_load: List[tuple[str, int]],
) -> None:
    """Waermt die naechste Anbieterwelle, ohne den Browser warten zu lassen."""
    requests = tuple(dict.fromkeys(requests_to_load))
    if not requests:
        return
    key = (mode, clean_genre(genre).casefold(), requests)
    with _MOVIE_CATALOG_PREFETCH_LOCK:
        if key in _MOVIE_CATALOG_PREFETCH_INFLIGHT:
            return
        _MOVIE_CATALOG_PREFETCH_INFLIGHT.add(key)

    def _work():
        try:
            _load_movie_provider_pages(
                mode,
                genre,
                list(requests),
                deadline=time.monotonic() + MOVIE_CATALOG_PAGE_BUDGET_SECONDS,
            )
        except Exception as exc:
            log(f"Filmkatalog-Prefetch übersprungen: {exc}", "warn")
        finally:
            with _MOVIE_CATALOG_PREFETCH_LOCK:
                _MOVIE_CATALOG_PREFETCH_INFLIGHT.discard(key)

    _MOVIE_CATALOG_PREFETCH_POOL.submit(_work)


def _movie_provider_genres(provider: str) -> set:
    return {
        "filmfrei24": state.filmfrei24_provider_genres,
        "filmo": state.filmo_provider_genres,
        "filmpalast": state.fp_provider_genres,
        "huhu": state.huhu_provider_genres,
        "moflix": state.moflix_provider_genres,
        "einschalten": state.einschalten_provider_genres,
        "kinox": state.kinox_provider_genres,
        "kinoger": state.kinoger_provider_genres,
        "megakino": state.megakino_provider_genres,
        "xcine": state.xcine_provider_genres,
        "sflix": state.sflix_provider_genres,
        "ridomovies": state.ridomovies_provider_genres,
    }.get(provider, set())


def _movie_genre_for_provider(provider: str, genre: str) -> str:
    known_by_key = {
        clean_genre(item).casefold(): clean_genre(item)
        for item in _movie_provider_genres(provider)
    }
    for alias in movie_genre_aliases(genre):
        match = known_by_key.get(alias.casefold())
        if match:
            return match
    return clean_genre(genre)


def _provider_supports_movie_genre(provider: str, genre: str) -> bool:
    known_genres = _movie_provider_genres(provider)
    # Vor dem ersten Genre-Abruf sind die Mengen leer. Dann optimistisch laden;
    # der jeweilige Scraper kann ein unbekanntes Genre günstig mit [] ablehnen.
    if not known_genres:
        return True
    known_keys = {clean_genre(item).casefold() for item in known_genres}
    return any(alias.casefold() in known_keys for alias in movie_genre_aliases(genre))


def _movie_result_identity(
    result: FilmpalastSearchResult,
    provider: str,
    years_by_title: Dict[str, set[str]],
) -> tuple:
    title_key = _norm_title(clean_movie_title(result.title))
    if not title_key:
        return ("source", provider, str(result.slug or result.url))
    year = str(result.year or "").strip()
    known_years = years_by_title.get(title_key, set())
    # Fehlt bei nur einer Quelle das Jahr, kann sie sicher dem einzigen bekannten
    # Jahr zugeordnet werden. Bei Remakes bleiben jahrlose Treffer separat.
    if not year and len(known_years) == 1:
        year = next(iter(known_years))
    return ("movie", title_key, year)


def _mix_movie_provider_results(
    provider_results: Dict[str, List[FilmpalastSearchResult]],
    priority: List[str],
    claimed_identities: Optional[set[tuple]] = None,
) -> List[tuple[str, FilmpalastSearchResult]]:
    """Dedupliziert eine Quellwelle und mischt sie fair im Round-Robin."""
    years_by_title: Dict[str, set[str]] = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(clean_movie_title(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    filtered: Dict[str, List[FilmpalastSearchResult]] = {provider: [] for provider in priority}
    seen_identities = claimed_identities if claimed_identities is not None else set()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _movie_result_identity(result, provider, years_by_title)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            filtered[provider].append(result)

    mixed: List[tuple[str, FilmpalastSearchResult]] = []
    longest = max((len(results) for results in filtered.values()), default=0)
    for index in range(longest):
        for provider in priority:
            results = filtered[provider]
            if index < len(results):
                mixed.append((provider, results[index]))
    return mixed


def movie_catalog_page(mode: str, page: int = 1, genre: str = "") -> dict:
    """Erzeugt eine stabile globale 32er-Seite aus allen Filmkatalogen.

    Einseitige Anbieter speisen ihren gesamten Startbestand in die globalen
    Seiten ein. Weitere Quellseiten werden jeweils als abgeschlossene Welle
    gemischt und nur hinten angehängt, damit frühere Seitengrenzen stabil bleiben.
    """
    page = max(1, min(int(page), MOVIE_MAX_GLOBAL_PAGE))
    mode = "genre" if mode == "genre" else mode if mode in {"new", "top"} else "new"
    genre = canonical_movie_genre(genre)
    priority = provider_priority("movies")
    active = [
        provider for provider in priority
        if mode != "genre" or _provider_supports_movie_genre(provider, genre)
    ]
    provider_seen: Dict[str, set[str]] = {provider: set() for provider in priority}

    def unique_page(
        provider: str,
        results: List[FilmpalastSearchResult],
    ) -> List[FilmpalastSearchResult]:
        unique: List[FilmpalastSearchResult] = []
        for result in results:
            source_key = str(result.slug or result.url or result.title or "").strip()
            key = f"{source_key}\0{str(result.year or '').strip()}"
            if key in provider_seen[provider]:
                continue
            provider_seen[provider].add(key)
            unique.append(result)
        return unique

    cold_wave_budget = [MOVIE_MAX_COLD_WAVES_PER_REQUEST]
    deadline = time.monotonic() + MOVIE_CATALOG_PAGE_BUDGET_SECONDS
    timed_out = [False]
    first_pages = _load_movie_provider_pages(
        mode, genre, [(provider, 1) for provider in active], cold_wave_budget,
        deadline, timed_out,
    )
    first_wave = {
        provider: unique_page(provider, first_pages.get((provider, 1), []))
        for provider in active
    }
    # Priorität entscheidet innerhalb derselben Quellwelle. Bereits katalogisierte
    # Filme werden von späteren Wellen nicht ersetzt; sonst würden Seiten springen.
    claimed_identities: set[tuple] = set()
    catalog_entries = _mix_movie_provider_results(
        first_wave, priority, claimed_identities,
    )

    paginated = [provider for provider in active if provider in MOVIE_PAGINATED_PROVIDERS]
    exhausted = {
        provider for provider in paginated
        if (provider, 1) in first_pages and not first_wave[provider]
    }
    duplicate_only_pages = {provider: 0 for provider in paginated}
    target_end = page * MOVIE_BROWSE_PAGE_SIZE
    next_source_page = 2
    has_more_unverified = timed_out[0]

    while (
        not timed_out[0]
        and len(catalog_entries) <= target_end
        and next_source_page <= MOVIE_MAX_SOURCE_PAGE
    ):
        pending = [provider for provider in paginated if provider not in exhausted]
        if not pending:
            break
        try:
            next_pages = _load_movie_provider_pages(
                mode, genre, [(provider, next_source_page) for provider in pending],
                cold_wave_budget, deadline, timed_out,
            )
        except MovieCatalogColdLoadLimit:
            if len(catalog_entries) < target_end:
                raise
            # Die angeforderte Seite ist vollständig. Der nächste Klick darf die
            # preiswerte Folgeseiten-Prüfung in einem neuen Request fortsetzen.
            has_more_unverified = True
            break
        wave: Dict[str, List[FilmpalastSearchResult]] = {}
        for provider in pending:
            if (provider, next_source_page) not in next_pages:
                wave[provider] = []
                has_more_unverified = True
                continue
            results = next_pages.get((provider, next_source_page), [])
            wave[provider] = unique_page(provider, results)
            if not results:
                exhausted.add(provider)
            elif not wave[provider]:
                duplicate_only_pages[provider] += 1
                if duplicate_only_pages[provider] >= 2:
                    exhausted.add(provider)
            else:
                duplicate_only_pages[provider] = 0
        catalog_entries.extend(_mix_movie_provider_results(
            wave, priority, claimed_identities,
        ))
        next_source_page += 1
        has_more_unverified = has_more_unverified or timed_out[0]

    start = (page - 1) * MOVIE_BROWSE_PAGE_SIZE
    page_entries = catalog_entries[start:target_end]
    source_counts = Counter(provider for provider, _result in page_entries)
    sources = [
        {
            "key": provider,
            "label": PROVIDER_LABELS[provider],
            "content_language": provider_content_language(provider),
            "language_label": PROVIDER_CATALOG[provider].language_label,
            "count": source_counts[provider],
        }
        for provider in priority
        if source_counts[provider]
    ]
    has_more = page < MOVIE_MAX_GLOBAL_PAGE and (
        len(catalog_entries) > target_end or has_more_unverified
    )
    page_complete = len(page_entries) >= MOVIE_BROWSE_PAGE_SIZE or not has_more
    if has_more and not timed_out[0]:
        _schedule_movie_provider_prefetch(
            mode,
            genre,
            [
                (provider, next_source_page)
                for provider in paginated
                if provider not in exhausted
            ],
        )
    return {
        "results": [result for _provider, result in page_entries],
        "page": page,
        "page_complete": page_complete,
        "has_more": has_more,
        "sources": sources,
    }


def list_movie_candidates(mode: str, page: int = 1) -> List[FilmpalastSearchResult]:
    """Kompatibler Listen-Zugriff auf die globale, gemischte Katalogseite."""
    return list(movie_catalog_page(mode, page)["results"])


def warm_home_movie_cache():
    """Bereitet Film- und Serien-Startansicht vor dem ersten Browser vor."""
    try:
        movies = list_movie_candidates("new", 1)
        tmdb = get_tmdb_client()
        if not tmdb.configured or not movies:
            return

        unique = {}
        for movie in movies:
            title = clean_movie_title(movie.title)
            unique.setdefault((_norm_title(title), str(movie.year or "")), (title, movie.year or ""))
        values = list(unique.values())
        # Das erste sichtbare Detail hat Vorrang. Erst danach den Rest mit
        # geringer Parallelität laden, damit die Startansicht nicht verhungert.
        tmdb.movie_summary(*values[0])
        remaining = values[1:]
        if remaining:
            with ThreadPoolExecutor(max_workers=min(3, len(remaining))) as pool:
                futures = [pool.submit(tmdb.movie_summary, title, year) for title, year in remaining]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:
                        log(f"TMDB-Startcache: {exc}", "warn")
        log(f"Startansicht vorbereitet: {len(movies)} neue Filme.")
    except Exception as exc:
        log(f"Startansicht konnte nicht vorab geladen werden: {exc}", "warn")


_SERVICE_EXPORTS = (
    "strip_source_suffix",
    "clean_movie_title",
    "provider_order",
    "provider_priority",
    "provider_for_value",
    "_apply_provider_metadata",
    "_apply_provider_metadata_many",
    "_movie_provider",
    "_movie_content_language",
    "_ordered_episode_sources",
    "clean_genre",
    "canonical_movie_genre",
    "movie_genre_aliases",
    "watchlist_lookup",
    "watchlist_match_series",
    "load_movie_for_slug",
    "search_movie_candidates",
    "_tmdb_search_results",
    "_movie_title_match_keys",
    "_movie_year_from_title",
    "_resolved_movie_year",
    "_movie_matches_tmdb_choice",
    "resolve_tmdb_movie_sources",
    "MovieCatalogColdLoadLimit",
    "_movie_provider_page_cache_state",
    "_cached_movie_provider_page",
    "_cache_movie_provider_page",
    "_fetch_movie_provider_page",
    "_load_movie_provider_pages",
    "_schedule_movie_provider_prefetch",
    "_movie_provider_genres",
    "_movie_genre_for_provider",
    "_provider_supports_movie_genre",
    "_movie_result_identity",
    "_mix_movie_provider_results",
    "movie_catalog_page",
    "list_movie_candidates",
    "warm_home_movie_cache",
)
publish_service(globals(), _SERVICE_EXPORTS)
