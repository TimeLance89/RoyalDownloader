"""Series provider routing, matching, catalog, and media-path services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# --- Serienanbieter ----------------------------------------------------------
def _sto_get_series(value: str) -> Optional[FilmpalastSeries]:
    if not state.provider_health.request_allowed("serienstream"):
        raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
    with state.sto_lock:
        try:
            return get_sto_scraper().get_series(value)
        except ProviderBlockedError as exc:
            _mark_serienstream_blocked(exc.reason, str(exc))
            raise


def _sto_search_series(query: str) -> List[FilmpalastSeriesResult]:
    if not state.provider_health.request_allowed("serienstream"):
        raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
    with state.sto_lock:
        try:
            return get_sto_scraper().search_series(query)
        except ProviderBlockedError as exc:
            _mark_serienstream_blocked(exc.reason, str(exc))
            raise


def _search_series_for_provider(provider: str, query: str) -> List[FilmpalastSeriesResult]:
    if provider == "serienstream":
        return _sto_search_series(query)
    if provider == "filmpalast":
        with state.fp_lock:
            return get_fp_scraper().search_series(query)
    if provider == "moflix":
        with state.moflix_lock:
            return get_moflix_scraper().search_series(query)
    if provider == "huhu":
        with state.huhu_lock:
            return get_huhu_scraper().search_series(query)
    if provider == "kinoger":
        return KinogerScraper(progress_cb=log).search_series(query)
    if provider == "megakino":
        return MegaKinoScraper(progress_cb=log).search_series(query)
    if provider == "xcine":
        return XcineScraper(progress_cb=log).search_series(query)
    if provider == "sflix":
        return SflixScraper(progress_cb=log).search_series(query)
    if provider == "ridomovies":
        return RidomoviesScraper(progress_cb=log).search_series(query)
    return []


def _load_series_for_provider(provider: str, value: str) -> Optional[FilmpalastSeries]:
    if provider == "serienstream":
        return _sto_get_series(value)
    if provider == "filmpalast":
        with state.fp_lock:
            return get_fp_scraper().get_series(value)
    if provider == "moflix":
        with state.moflix_lock:
            return get_moflix_scraper().get_series(value)
    if provider == "huhu":
        with state.huhu_lock:
            return get_huhu_scraper().get_series(value)
    if provider == "kinoger":
        return KinogerScraper(progress_cb=log).get_series(value)
    if provider == "megakino":
        return MegaKinoScraper(progress_cb=log).get_series(value)
    if provider == "xcine":
        return XcineScraper(progress_cb=log).get_series(value)
    if provider == "sflix":
        return SflixScraper(progress_cb=log).get_series(value)
    if provider == "ridomovies":
        return RidomoviesScraper(progress_cb=log).get_series(value)
    return None


def _search_series_provider_results(
    query: str,
) -> Dict[str, List[FilmpalastSeriesResult]]:
    """Durchsucht alle Serienkataloge parallel und trennt die Treffer je Quelle."""
    q = query.strip()
    if not q:
        return {}
    priority = provider_priority("series")
    tasks = [
        (provider, lambda key=provider: _search_series_for_provider(key, q))
        for provider in priority
    ]
    provider_results: Dict[str, List[FilmpalastSeriesResult]] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [(provider, pool.submit(fn)) for provider, fn in tasks]
        for provider, future in futures:
            try:
                provider_results[provider] = list(future.result())
            except Exception as exc:
                log(f"{PROVIDER_LABELS[provider]} Seriensuche übersprungen: {exc}", "warn")
                provider_results[provider] = []
    return provider_results


def search_series_candidates(query: str) -> List[FilmpalastSeriesResult]:
    """Durchsucht alle Serienkataloge und behält die konfigurierte Reihenfolge."""
    provider_results = _search_series_provider_results(query)
    results: List[FilmpalastSeriesResult] = []
    for provider in provider_priority("series"):
        results.extend(provider_results.get(provider, []))
    return results


@dataclass(frozen=True)
class _SeriesCatalogEntry:
    """Ein sichtbarer Serientreffer mit bevorzugter und alternativen Quellen."""

    provider: str
    result: FilmpalastSeriesResult
    providers: tuple[str, ...]


class SeriesCatalogColdLoadLimit(RuntimeError):
    """Verhindert teure Sprünge über viele noch ungecachte Serienseiten."""


def _series_result_identity(
    result: FilmpalastSeriesResult,
    provider: str,
    years_by_title: Dict[str, set[str]],
) -> tuple:
    title_key = _norm_title(strip_source_suffix(result.title))
    if not title_key:
        return ("source", provider, str(result.base_slug or result.sample_slug or result.sample_url))
    year = str(result.year or "").strip()
    known_years = years_by_title.get(title_key, set())
    if not year and len(known_years) == 1:
        year = next(iter(known_years))
    return ("series", title_key, year)


def _claim_series_identity(identity: tuple, claimed: set[tuple]) -> bool:
    """Reserviert eine Identität; True bedeutet, dass sie bereits sichtbar ist."""
    if identity in claimed:
        return True
    if len(identity) != 3 or identity[0] != "series":
        claimed.add(identity)
        return False

    _kind, title_key, year = identity
    unknown = ("series", title_key, "")
    known = {
        item for item in claimed
        if len(item) == 3 and item[0] == "series" and item[1] == title_key and item[2]
    }
    if year and unknown in claimed:
        # Ein früher jahrsloser Treffer wird durch den ersten eindeutigen
        # Jahrgang konkretisiert. Weitere Remakes dürfen danach sichtbar bleiben.
        claimed.remove(unknown)
        claimed.add(identity)
        return True
    if not year and len(known) == 1:
        return True
    claimed.add(identity)
    return False


def _mix_series_provider_results(
    provider_results: Dict[str, List[FilmpalastSeriesResult]],
    priority: List[str],
    claimed_identities: Optional[set[tuple]] = None,
) -> List[_SeriesCatalogEntry]:
    """Dedupliziert Serien und mischt die Leitquelle im Verhältnis 2:1 ein.

    Die erste konfigurierte Quelle erhält zwei Plätze je Runde. So bleibt die
    stärkste Quelle prägend, während jeder weitere Anbieter regelmäßig sichtbar
    wird. Identische Titel werden als eine Serie mit mehreren Quellen geführt.
    """
    years_by_title: Dict[str, set[str]] = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(strip_source_suffix(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    grouped: Dict[tuple, List[tuple[str, FilmpalastSeriesResult]]] = OrderedDict()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _series_result_identity(result, provider, years_by_title)
            grouped.setdefault(identity, []).append((provider, result))

    seen = claimed_identities if claimed_identities is not None else set()
    per_provider: Dict[str, List[_SeriesCatalogEntry]] = {provider: [] for provider in priority}
    for identity, matches in grouped.items():
        if _claim_series_identity(identity, seen):
            continue
        primary_provider, primary_result = matches[0]
        source_set = {provider for provider, _result in matches}
        sources = tuple(provider for provider in priority if provider in source_set)

        # Fehlende Listenmetadaten dürfen von einer alternativen Quelle ergänzt
        # werden, ohne die bevorzugte, klickbare Quelle auszutauschen.
        year = str(primary_result.year or "").strip()
        cover_url = str(primary_result.cover_url or "").strip()
        if not year:
            year = next((str(result.year).strip() for _provider, result in matches if result.year), "")
        if not cover_url:
            cover_url = next(
                (str(result.cover_url).strip() for _provider, result in matches if result.cover_url),
                "",
            )
        visible_result = replace(primary_result, year=year, cover_url=cover_url)
        per_provider[primary_provider].append(_SeriesCatalogEntry(
            provider=primary_provider,
            result=visible_result,
            providers=sources or (primary_provider,),
        ))

    mixed: List[_SeriesCatalogEntry] = []
    positions = {provider: 0 for provider in priority}
    while True:
        progressed = False
        for index, provider in enumerate(priority):
            quota = 2 if index == 0 else 1
            entries = per_provider[provider]
            start = positions[provider]
            end = min(start + quota, len(entries))
            if end > start:
                mixed.extend(entries[start:end])
                positions[provider] = end
                progressed = True
        if not progressed:
            break
    return mixed


def _interleave_series_lists(
    *lists: List[FilmpalastSeriesResult],
) -> List[FilmpalastSeriesResult]:
    """Verzahnt mehrere Signallisten stabil und entfernt Quell-Dubletten."""
    merged: List[FilmpalastSeriesResult] = []
    seen: set[str] = set()
    longest = max((len(items) for items in lists), default=0)
    for index in range(longest):
        for items in lists:
            if index >= len(items):
                continue
            result = items[index]
            key = str(result.base_slug or result.sample_slug or result.sample_url or result.title)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
    return merged


def _series_provider_is_paginated(provider: str, mode: str) -> bool:
    if mode == "alpha":
        return provider in SERIES_ALPHA_PROVIDERS
    return provider in SERIES_PAGINATED_PROVIDERS


def _cached_series_provider_page(
    cache_key: tuple,
) -> Optional[List[FilmpalastSeriesResult]]:
    with state.series_list_cache_lock:
        cached = state.series_list_cache.get(cache_key)
        ttl = cached[2] if cached and len(cached) > 2 else SERIES_LIST_CACHE_TTL
        if cached and time.time() - cached[0] < ttl:
            return list(cached[1])
        if cached:
            state.series_list_cache.pop(cache_key, None)
    return None


def _cache_series_provider_page(
    cache_key: tuple,
    results: List[FilmpalastSeriesResult],
    ttl: int = SERIES_LIST_CACHE_TTL,
) -> None:
    now = time.time()
    with state.series_list_cache_lock:
        expired = [
            key for key, cached in state.series_list_cache.items()
            if now - cached[0] >= (
                cached[2] if len(cached) > 2 else SERIES_LIST_CACHE_TTL
            )
        ]
        for key in expired:
            state.series_list_cache.pop(key, None)
        while len(state.series_list_cache) >= SERIES_LIST_CACHE_MAX_ENTRIES:
            oldest = min(
                state.series_list_cache,
                key=lambda key: state.series_list_cache[key][0],
            )
            state.series_list_cache.pop(oldest, None)
        state.series_list_cache[cache_key] = (now, list(results), ttl)


def _fetch_series_provider_page(
    provider: str,
    mode: str,
    letter: str,
    source_page: int,
) -> List[FilmpalastSeriesResult]:
    """Lädt eine Serien-Quellseite passend zum gewünschten Entdeckungsmodus."""
    if not _series_provider_is_paginated(provider, mode) and source_page != 1:
        return []

    if provider == "serienstream":
        if not state.provider_health.request_allowed("serienstream"):
            return []
        with state.sto_lock:
            scraper = get_sto_scraper()
            try:
                if mode == "alpha":
                    return list(scraper.list_series_alpha(letter, source_page))
                if source_page != 1:
                    return []
                if mode == "new":
                    return list(scraper.list_new(1))
                if mode == "trending":
                    return list(scraper.list_trending(1))
                return _interleave_series_lists(
                    list(scraper.list_trending(1)),
                    list(scraper.list_new(1)),
                )
            except ProviderBlockedError as exc:
                _mark_serienstream_blocked(exc.reason, str(exc))
                return []

    if provider == "filmpalast":
        with state.fp_lock:
            scraper = get_fp_scraper()
            if mode == "alpha":
                return list(scraper.list_series_alpha(letter, source_page))
            return list(scraper.list_series(source_page))

    if mode == "alpha":
        return []
    scraper_classes = {
        "moflix": MoflixScraper,
        "kinoger": KinogerScraper,
        "megakino": MegaKinoScraper,
        "xcine": XcineScraper,
        "sflix": SflixScraper,
        "ridomovies": RidomoviesScraper,
    }
    if provider == "huhu":
        with state.huhu_lock:
            return list(get_huhu_scraper().list_series(source_page))
    scraper_class = scraper_classes.get(provider)
    if scraper_class is None:
        return []
    return list(scraper_class(progress_cb=log).list_series(source_page))


def _load_series_provider_pages(
    mode: str,
    letter: str,
    requests_to_load: List[tuple[str, int]],
    cold_wave_budget: Optional[List[int]] = None,
) -> Dict[tuple[str, int], List[FilmpalastSeriesResult]]:
    loaded: Dict[tuple[str, int], List[FilmpalastSeriesResult]] = {}
    missing: List[tuple[str, int, tuple]] = []
    letter_key = str(letter or "").strip().upper()
    for provider, source_page in dict.fromkeys(requests_to_load):
        cache_mode = (
            "updates"
            if provider != "serienstream" and mode in {"discover", "new"}
            else mode
        )
        cache_key = ("series-provider", cache_mode, letter_key, provider, int(source_page))
        cached = _cached_series_provider_page(cache_key)
        if cached is None:
            missing.append((provider, source_page, cache_key))
        else:
            loaded[(provider, source_page)] = cached

    if not missing:
        return loaded
    if cold_wave_budget is not None:
        if cold_wave_budget[0] <= 0:
            raise SeriesCatalogColdLoadLimit(
                "Dieser Serienabschnitt wird noch vorbereitet. Bitte kurz warten und erneut versuchen."
            )
        cold_wave_budget[0] -= 1

    with ThreadPoolExecutor(max_workers=min(len(missing), len(PROVIDER_LABELS))) as pool:
        futures = [
            (
                provider,
                source_page,
                cache_key,
                pool.submit(
                    _fetch_series_provider_page,
                    provider,
                    mode,
                    letter,
                    source_page,
                ),
            )
            for provider, source_page, cache_key in missing
        ]
        for provider, source_page, cache_key, future in futures:
            try:
                results = list(future.result())
            except Exception as exc:
                log(
                    f"{PROVIDER_LABELS.get(provider, provider)} Serienliste "
                    f"(Quellseite {source_page}) übersprungen: {exc}",
                    "warn",
                )
                results = []
                _cache_series_provider_page(
                    cache_key,
                    results,
                    ttl=SERIES_LIST_FAILURE_CACHE_TTL,
                )
            else:
                _cache_series_provider_page(cache_key, results)
            loaded[(provider, source_page)] = results
    return loaded


def _series_catalog_sources(entries: List[_SeriesCatalogEntry], priority: List[str]) -> List[dict]:
    counts = Counter(provider for entry in entries for provider in entry.providers)
    return [
        {
            "key": provider,
            "label": PROVIDER_LABELS[provider],
            "content_language": provider_content_language(provider),
            "language_label": PROVIDER_CATALOG[provider].language_label,
            "count": counts[provider],
        }
        for provider in priority
        if counts[provider]
    ]


def _series_entry_to_dict(entry: _SeriesCatalogEntry) -> dict:
    payload = asdict(entry.result)
    payload["title"] = strip_source_suffix(entry.result.title)
    payload["provider"] = entry.provider
    payload["provider_label"] = PROVIDER_LABELS.get(entry.provider, entry.provider)
    payload["content_language"] = provider_content_language(entry.provider)
    payload["language_label"] = PROVIDER_CATALOG[entry.provider].language_label
    payload["sources"] = [
        {
            "key": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "content_language": provider_content_language(provider),
        }
        for provider in entry.providers
    ]
    return payload


def _series_catalog_page_locked(mode: str, page: int = 1, letter: str = "") -> dict:
    """Erzeugt eine stabile, gemischte Serienseite aus den verfügbaren Katalogen."""
    page = max(1, min(int(page), SERIES_MAX_GLOBAL_PAGE))
    mode = mode if mode in {"discover", "new", "trending", "alpha"} else "discover"
    priority = provider_priority("series")
    if mode == "trending":
        # Nur Serienstream liefert ein echtes Popularitätssignal. Andere
        # Aktualitätslisten werden bewusst nicht als „angesagt“ ausgegeben.
        active = [provider for provider in priority if provider == "serienstream"]
    elif mode == "alpha":
        active = [provider for provider in priority if provider in SERIES_ALPHA_PROVIDERS]
    else:
        active = list(priority)

    provider_seen: Dict[str, set[str]] = {provider: set() for provider in priority}

    def unique_page(
        provider: str,
        results: List[FilmpalastSeriesResult],
    ) -> List[FilmpalastSeriesResult]:
        unique: List[FilmpalastSeriesResult] = []
        for result in results:
            source_key = str(
                result.base_slug or result.sample_slug or result.sample_url or result.title
            ).strip()
            key = f"{source_key}\0{str(result.year or '').strip()}"
            if key in provider_seen[provider]:
                continue
            provider_seen[provider].add(key)
            unique.append(result)
        return unique

    catalog_mode = mode
    cold_wave_budget = [SERIES_MAX_COLD_WAVES_PER_REQUEST]
    first_pages = _load_series_provider_pages(
        catalog_mode,
        letter,
        [(provider, 1) for provider in active],
        cold_wave_budget,
    )
    first_wave = {
        provider: unique_page(provider, first_pages.get((provider, 1), []))
        for provider in active
    }
    claimed_identities: set[tuple] = set()
    catalog_entries = _mix_series_provider_results(
        first_wave,
        priority,
        claimed_identities,
    )

    if mode == "trending" and not catalog_entries:
        # SerienStream ist die einzige Quelle mit einem echten Popularitätssignal.
        # Bei CAPTCHA, Rate-Limit oder deaktivierter Quelle darf die Startseite
        # deshalb trotzdem nicht dauerhaft leer bleiben. In diesem Fall zeigen
        # wir verfügbare Serien aus den übrigen aktiven Katalogen an.
        active = [provider for provider in priority if provider != "serienstream"]
        catalog_mode = "discover"
        cold_wave_budget = [SERIES_MAX_COLD_WAVES_PER_REQUEST]
        fallback_pages = _load_series_provider_pages(
            catalog_mode,
            letter,
            [(provider, 1) for provider in active],
            cold_wave_budget,
        )
        first_wave = {
            provider: unique_page(provider, fallback_pages.get((provider, 1), []))
            for provider in active
        }
        claimed_identities.clear()
        catalog_entries = _mix_series_provider_results(
            first_wave,
            priority,
            claimed_identities,
        )

    paginated = [
        provider
        for provider in active
        if _series_provider_is_paginated(provider, catalog_mode)
    ]
    exhausted = {provider for provider in paginated if not first_wave[provider]}
    duplicate_only_pages = {provider: 0 for provider in paginated}
    target_end = page * SERIES_BROWSE_PAGE_SIZE
    next_source_page = 2
    has_more_unverified = False

    while len(catalog_entries) <= target_end and next_source_page <= SERIES_MAX_SOURCE_PAGE:
        pending = [provider for provider in paginated if provider not in exhausted]
        if not pending:
            break
        try:
            next_pages = _load_series_provider_pages(
                catalog_mode,
                letter,
                [(provider, next_source_page) for provider in pending],
                cold_wave_budget,
            )
        except SeriesCatalogColdLoadLimit:
            if len(catalog_entries) < target_end:
                raise
            has_more_unverified = True
            break
        wave: Dict[str, List[FilmpalastSeriesResult]] = {}
        for provider in pending:
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
        catalog_entries.extend(_mix_series_provider_results(
            wave,
            priority,
            claimed_identities,
        ))
        next_source_page += 1

    start = (page - 1) * SERIES_BROWSE_PAGE_SIZE
    page_entries = catalog_entries[start:target_end]
    return {
        "entries": page_entries,
        "page": page,
        "has_more": page < SERIES_MAX_GLOBAL_PAGE and (
            len(catalog_entries) > target_end or has_more_unverified
        ),
        "sources": _series_catalog_sources(page_entries, priority),
    }


def series_catalog_page(mode: str, page: int = 1, letter: str = "") -> dict:
    """Single-Flight-Wrapper für Warmup und gleichzeitig öffnende Browser."""
    with state.series_catalog_lock:
        return _series_catalog_page_locked(mode, page, letter)


def series_search_catalog(query: str) -> dict:
    """Gruppiert die freie Suche nach Titel und zeigt alternative Quellen an."""
    priority = provider_priority("series")
    entries = _mix_series_provider_results(
        _search_series_provider_results(query),
        priority,
    )
    wanted = _norm_title(query)
    entries.sort(key=lambda entry: (
        _norm_title(entry.result.title) != wanted,
        wanted not in _norm_title(entry.result.title),
        abs(len(_norm_title(entry.result.title)) - len(wanted)),
        strip_source_suffix(entry.result.title).casefold(),
    ))
    return {
        "entries": entries,
        "page": 1,
        "has_more": False,
        "sources": _series_catalog_sources(entries, priority),
    }


def warm_home_series_cache() -> None:
    """Bereitet die gemischte Serien-Startansicht im Hintergrund vor."""
    try:
        catalog = series_catalog_page("discover", 1)
        log(f"Serien-Startansicht vorbereitet: {len(catalog['entries'])} Serien.")
    except Exception as exc:
        log(f"Serien-Startansicht konnte nicht vorab geladen werden: {exc}", "warn")


def warm_jellyfin_identity_cache() -> None:
    """Bereitet den kleinen Serienindex für sofortige Detailabgleiche vor."""
    if not get_jellyfin_client().configured:
        return
    started = time.monotonic()
    items = get_jellyfin_series()
    if items is not None:
        logger.info(
            "Jellyfin-Serienindex vorbereitet: %d Serie(n) in %.2fs",
            len(items), time.monotonic() - started,
        )


def _norm_title(title: str) -> str:
    """Titel für Matching normalisieren: Provider-Suffix + Sonderzeichen weg."""
    t = re.sub(r"\s*\[[^\]]+\]\s*$", "", title or "")
    return re.sub(r"[^a-z0-9]+", "", t.casefold())


def _series_search_title(value: str) -> str:
    """Leitet aus einem Serien-Wert (Slug/URL) einen Such-Titel ab – auch aus
    Alt-/Fremdwerten (Moflix/Filmpalast), damit alte Watchlist-Einträge auf
    serienstream.to gematcht werden können."""
    v = value or ""
    is_kinoger = v.startswith(KINOGER_PREFIX) or "kinoger.com" in v.casefold()
    is_megakino = v.startswith(MEGAKINO_PREFIX) or "megakino.org" in v.casefold()
    is_xcine = v.startswith(XCINE_PREFIX) or "xcine.ru" in v.casefold()
    for pfx in (
        SERIENSTREAM_PREFIX, HUHU_PREFIX, MOFLIX_PREFIX, EINSCHALTEN_PREFIX, KINOX_PREFIX,
        KINOGER_PREFIX, MEGAKINO_PREFIX, XCINE_PREFIX,
        SFLIX_PREFIX, RIDOMOVIES_PREFIX,
    ):
        if v.startswith(pfx):
            v = v[len(pfx):]
            break
    if ":" in v and v.split(":", 1)[0].isdigit():   # moflix "123:the-bear"
        v = v.split(":", 1)[1]
    if is_megakino:
        v = re.sub(r"^[0-9a-f]{24}:", "", v, flags=re.I)
    if v.startswith("http"):
        m = re.search(r"/(?:serie|stream|titles|watch)/(?:stream/|\d+/)?([^/?#]+)", v)
        v = m.group(1) if m else v
    if is_kinoger:
        v = re.sub(r"^\d+-", "", v)
        v = re.sub(r"\.html$", "", v, flags=re.I)
    if is_xcine and ":" in v:
        v = v.split(":", 1)[1]
    parsed = parse_episode_slug(v)
    if parsed:
        v = parsed[0]
    return v.replace("-", " ").strip()


def _episode_placeholder(slug: str, series_title: str = "") -> FilmpalastMovie:
    """Behält eine vorübergehend nicht ladbare Episode als Queue-Job."""
    parsed = parse_episode_slug(slug)
    if not parsed:
        raise ValueError(f"Kein Episoden-Slug: {slug}")
    base_slug, season, episode = parsed
    if not series_title:
        with state.watchlist_lock:
            entry = watchlist_lookup(base_slug)
            if entry:
                series_title = str(entry.get("title") or "")
    if not series_title:
        cached = state.series_cache.get(base_slug)
        if cached:
            series_title = cached.title
    if not series_title:
        series_title = _series_search_title(base_slug).title() or "Unbekannte Serie"
    return FilmpalastMovie(
        title=f"{series_title} S{season:02d}E{episode:02d}",
        url=slug,
        hosters=[],
    )


def _best_title_match(title: str, results: List[FilmpalastSeriesResult]) -> Optional[FilmpalastSeriesResult]:
    want = _norm_title(title)
    if not want or not results:
        return None
    exact = [r for r in results if _norm_title(r.title) == want]
    if exact:
        return exact[0]
    partial = [r for r in results if want in _norm_title(r.title) or _norm_title(r.title) in want]
    return partial[0] if partial else None


def _find_series_by_title(
    value: str, providers: Optional[List[str]] = None,
) -> Optional[FilmpalastSeries]:
    """Sucht und lädt dieselbe Serie nach konfigurierter Anbieterpriorität."""
    title = _series_search_title(value)
    if not title:
        return None
    for provider in providers or provider_priority("series"):
        label = PROVIDER_LABELS[provider]
        log(f"Serie nicht direkt ladbar – suche «{title}» bei {label} …")
        try:
            results = _search_series_for_provider(provider, title)
            best = _best_title_match(title, results)
            series = _load_series_for_provider(provider, best.sample_slug) if best else None
        except Exception as exc:
            log(f"  {label}-Suche/Laden fehlgeschlagen: {exc}", "warn")
            continue
        if series and series.seasons:
            log(f"  Gefunden bei {label} ({len(series.all_episodes)} Episoden).")
            return series
    return None


def _sto_find_by_title(value: str) -> Optional[FilmpalastSeries]:
    """Kompatibilitätshelfer für gezielte Serienstream-Suche."""
    return _find_series_by_title(value, ["serienstream"])


def get_series_for_value(value: str) -> Optional[FilmpalastSeries]:
    """Lädt eine explizite Quelle direkt, danach greifen die Prioritäts-Fallbacks."""
    provider = provider_for_value(value)
    try:
        series = _load_series_for_provider(provider, value)
    except Exception as exc:
        log(f"{PROVIDER_LABELS[provider]} Serien-Laden fehlgeschlagen: {exc}", "warn")
        series = None
    if series and series.seasons:
        return series
    fallbacks = [key for key in provider_priority("series") if key != provider]
    if provider in appconfig.SERIES_PROVIDER_DEFAULTS:
        fallbacks.append(provider)
    return _find_series_by_title(value, fallbacks)


def movie_to_dict(
    movie: FilmpalastMovie,
    tmdb_override: Optional[dict] = None,
) -> dict:
    ranked = state.hoster_intel.rank(movie.hosters) if movie.hosters else []
    provider = _movie_provider(movie)
    content_language = _movie_content_language(movie)
    payload = {
        "title": clean_movie_title(movie.title),
        "url": movie.url, "year": movie.year,
        "runtime": movie.runtime, "cover_url": movie.cover_url,
        "description": movie.description, "genres": movie.genres,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "content_language": content_language,
        "language_label": PROVIDER_CATALOG[provider].language_label,
        "hosters": [asdict(h) for h in movie.hosters],
        "hoster_label": state.hoster_intel.best_label(movie.hosters) if movie.hosters else "kein Hoster",
        "hoster_route": state.hoster_intel.route_text(movie.hosters) if movie.hosters else "keine Route",
        "hoster_score": round(state.hoster_intel.score(ranked[0])) if ranked else None,
        "hoster_fallback_count": max(0, len(ranked) - 1) if ranked else 0,
        "metadata_source": "Anbieter",
    }
    tmdb = tmdb_override or get_tmdb_client().movie(
        clean_movie_title(movie.title), movie.year,
    )
    if tmdb:
        for field in (
            "title", "year", "runtime", "cover_url", "backdrop_url", "description", "genres",
            "original_title", "release_date", "rating", "vote_count", "tagline",
            "certification", "certification_country", "status", "original_language",
            "spoken_languages", "countries", "directors", "writers", "cast",
            "production_companies", "keywords", "collection", "budget", "revenue",
            "trailer", "tmdb_url",
        ):
            if tmdb.get(field):
                payload[field] = tmdb[field]
        payload["metadata_source"] = "TMDB"
        payload["tmdb_id"] = tmdb["tmdb_id"]
    return payload


def movie_detail_to_dict(slug: str, movie: FilmpalastMovie) -> dict:
    """Ergänzt einen Film um seine gebündelten Anbieterquellen."""
    tmdb_match = re.fullmatch(r"tmdb:(\d+)", slug or "", flags=re.IGNORECASE)
    tmdb = (
        get_tmdb_client().movie_by_id(tmdb_match.group(1))
        if tmdb_match else None
    )
    payload = movie_to_dict(movie, tmdb_override=tmdb)
    if tmdb_match:
        if tmdb:
            for field in (
                "title", "year", "runtime", "cover_url", "backdrop_url",
                "description", "genres", "original_title", "release_date",
                "rating", "vote_count", "tagline", "certification",
                "certification_country", "status", "original_language",
                "spoken_languages", "countries", "directors", "writers", "cast",
                "production_companies", "keywords", "collection", "budget",
                "revenue", "trailer", "tmdb_url",
            ):
                if tmdb.get(field):
                    payload[field] = tmdb[field]
            payload["metadata_source"] = "TMDB"
            payload["tmdb_id"] = tmdb["tmdb_id"]

    with state.movie_source_cache_lock:
        sources = list(state.movie_source_cache.get(slug) or [movie])
    provider_sources = []
    for source in sources:
        provider = _movie_provider(source)
        provider_sources.append({
            "key": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "content_language": _movie_content_language(source),
            "hoster_count": len(source.hosters),
            "hosters": [asdict(hoster) for hoster in source.hosters],
        })
    payload["source_providers"] = provider_sources
    payload["provider_count"] = len(provider_sources)
    payload["provider_fallback_count"] = max(0, len(provider_sources) - 1)
    payload["hoster_total"] = sum(source["hoster_count"] for source in provider_sources)
    payload["provider_route"] = " → ".join(
        source["label"] for source in provider_sources
    )
    return payload


def cached_movie_source_fallbacks(slug: str) -> Optional[List[FilmpalastMovie]]:
    with state.movie_source_cache_lock:
        sources = state.movie_source_cache.get(slug)
        return list(sources[1:]) if sources else None


def _series_folder_key(name: str) -> str:
    """Vergleichsschlüssel für vorhandene Serienordner.

    Linux unterscheidet Groß-/Kleinschreibung. Ohne diese Normalisierung würde
    z.B. neben "The rookie" ein zweiter Ordner "The Rookie" entstehen.
    """
    without_year = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", name or "")
    return re.sub(r"[^a-z0-9]+", "", without_year.casefold())


def _existing_series_dir(out_root: Path, desired_name: str) -> Path:
    desired = out_root / desired_name
    if not out_root.is_dir():
        return desired
    wanted = _series_folder_key(desired_name)
    cache_key = (str(out_root.resolve()), wanted)
    cached = state.series_dir_cache.get(cache_key)
    if cached is not None and cached.is_dir():
        return cached
    try:
        matches = [
            child for child in out_root.iterdir()
            if child.is_dir() and _series_folder_key(child.name) == wanted
        ]
    except OSError:
        return desired
    if not matches:
        return desired

    # Gibt es durch eine frühere Groß-/Kleinschreibungs-Abweichung bereits zwei
    # Ordner, gewinnt der etablierte Ordner mit den meisten Mediendateien.
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}

    def _content_score(path: Path) -> tuple:
        videos = 0
        dirs = 0
        try:
            for child in path.rglob("*"):
                if child.is_dir():
                    dirs += 1
                elif child.suffix.casefold() in video_suffixes:
                    videos += 1
        except OSError:
            pass
        return videos, dirs, path.name == desired_name

    chosen = max(matches, key=_content_score)
    state.series_dir_cache[cache_key] = chosen
    return chosen


def _season_output_dir(series_dir: Path, season: int) -> Path:
    """Übernimmt die vorhandene Staffelstruktur einer Serie.

    Unterstützt "Staffel 8", "Staffel 08", "Season 08" und "S08". Liegen
    vorhandene Episoden flach im Serienordner, bleibt auch die neue Episode dort.
    """
    preferred = series_dir / f"Staffel {season:02d}"
    if preferred.exists() or not series_dir.is_dir():
        return preferred

    season_re = re.compile(r"^(?:staffel|season|s)\s*0*(\d+)\b", re.IGNORECASE)
    season_dirs: List[tuple] = []
    has_flat_episodes = False
    episode_re = re.compile(r"(?:^|[. _-])s\d{1,2}e\d{1,3}(?:$|[. _-])", re.IGNORECASE)
    try:
        for child in series_dir.iterdir():
            if child.is_dir():
                match = season_re.match(child.name.strip())
                if match:
                    season_dirs.append((int(match.group(1)), child))
            elif child.is_file() and episode_re.search(child.stem):
                has_flat_episodes = True
    except OSError:
        return preferred

    for number, folder in season_dirs:
        if number == season:
            return folder
    if has_flat_episodes and not season_dirs:
        return series_dir
    return preferred


def series_episode_out_path(series_title: str, season: int, episode: int) -> Path:
    # Serien landen im SEPARATEN Serien-Ordner (state.series_path), Filme im
    # Film-Ordner (state.save_path). Vorhandene NAS-Strukturen werden bewahrt.
    out_root = Path(state.series_path)
    desired_name = sanitize_filename(series_title).strip() or "Serie"
    series_dir = _existing_series_dir(out_root, desired_name)
    season_dir = _season_output_dir(series_dir, season)
    return season_dir / build_filename(series_title, season, episode)


def _valid_media_cached(path: Path) -> tuple[bool, str]:
    """Validiert lokale Medien nur erneut, wenn Größe oder mtime sich ändern."""
    try:
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
    except OSError as exc:
        return False, f"Datei nicht lesbar: {exc}"
    key = str(path.resolve(strict=False))
    with state.media_validation_lock:
        cached = state.media_validation_cache.get(key)
        if cached and cached[:2] == signature:
            return bool(cached[2]), str(cached[3])
    valid, detail = validate_media_file(path)
    with state.media_validation_lock:
        state.media_validation_cache[key] = (*signature, valid, detail)
    return valid, detail


def compute_downloaded_episodes(series: FilmpalastSeries) -> set:
    """Scannt den Serienordner einmal statt eines NAS-Glob pro Episode."""
    out_root = Path(state.series_path)
    desired_name = sanitize_filename(series.title).strip() or "Serie"
    series_dir = _existing_series_dir(out_root, desired_name)
    if not series_dir.is_dir():
        return set()

    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    candidates: List[tuple[Path, tuple[int, int]]] = []
    try:
        for path in series_dir.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in video_suffixes:
                continue
            match = re.search(r"(?:^|[. _-])s(\d{1,2})e(\d{1,3})(?:$|[. _-])", path.stem, re.I)
            if match:
                candidates.append((path, (int(match.group(1)), int(match.group(2)))))
    except OSError:
        pass

    existing: set[tuple[int, int]] = set()
    if candidates:
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
            futures = [(pair, pool.submit(_valid_media_cached, path)) for path, pair in candidates]
            for pair, future in futures:
                try:
                    valid, _detail = future.result()
                except Exception:
                    valid = False
                if valid:
                    existing.add(pair)

    return {
        ep.slug for ep in series.all_episodes
        if (ep.season, ep.episode) in existing
    }


def series_to_dict(
    series: FilmpalastSeries,
    refresh_jellyfin: bool = False,
    defer_checks: bool = False,
) -> dict:
    """Serialisiert eine Serie, optional ohne blockierende Verfügbarkeitschecks.

    Beim ersten Öffnen werden damit Staffel- und Episodenstruktur sofort nach
    dem Anbieterabruf ausgeliefert. Lokaler Bestand, TMDB und Jellyfin dürfen
    anschließend in einem getrennten Request nachziehen.
    """
    downloaded = set() if defer_checks else compute_downloaded_episodes(series)
    with state.watchlist_lock:
        stored_entry = watchlist_match_series(series.base_slug, series.title)
        watchlist_entry = dict(stored_entry) if stored_entry else None
    stored_tmdb_id = watchlist_entry.get("tmdb_id") if watchlist_entry else ""
    tmdb_client = get_tmdb_client()
    tmdb = None if defer_checks else get_tmdb_series(series.title, stored_tmdb_id)
    aliases = list(dict.fromkeys(filter(None, (
        watchlist_entry.get("title", "") if watchlist_entry else "",
        *(watchlist_entry.get("aliases", []) if watchlist_entry else []),
        tmdb.get("title", "") if tmdb else "",
        tmdb.get("original_title", "") if tmdb else "",
    ))))
    tmdb_id = stored_tmdb_id or (tmdb or {}).get("tmdb_id")
    with state.watchlist_lock:
        refined_entry = watchlist_match_series(
            series.base_slug, series.title, tmdb_id=tmdb_id, aliases=aliases,
        )
        if refined_entry is not None:
            watchlist_entry = dict(refined_entry)
    if watchlist_entry:
        stored_tmdb_id = watchlist_entry.get("tmdb_id") or stored_tmdb_id
        tmdb_id = stored_tmdb_id or tmdb_id
        aliases = list(dict.fromkeys(filter(None, (
            watchlist_entry.get("title", ""),
            *(watchlist_entry.get("aliases") or []),
            *aliases,
        ))))
    season_episode_counts = (tmdb or {}).get("season_episode_counts") or (
        watchlist_entry.get("season_episode_counts", {}) if watchlist_entry else {}
    )
    season_counts_checked_at = (tmdb or {}).get("season_counts_checked_at") or (
        watchlist_entry.get("season_counts_checked_at", 0) if watchlist_entry else 0
    )
    unreleased_slugs = (
        _unreleased_episode_slugs(series, tmdb_id)
        if not defer_checks and tmdb_id else set()
    )
    jf_client = get_jellyfin_client()
    jellyfin_pending = bool(defer_checks and jf_client.configured)
    jf_identity_available: Optional[bool] = None if jellyfin_pending else True
    jf_existing: set[tuple[int, int]] = set()
    jf_stale = False
    jf_checked_at = 0.0
    if jf_client.configured and not jellyfin_pending:
        quick_status = _series_jellyfin_status(
            series.title,
            tmdb_id=tmdb_id,
            aliases=aliases,
            episodes=[
                {"slug": episode.slug, "season": episode.season, "episode": episode.episode}
                for episode in series.all_episodes
            ],
            force=refresh_jellyfin,
        )
        jf_identity_available = bool(quick_status["available"])
        jf_stale = bool(quick_status["stale"])
        jf_checked_at = float(quick_status["checked_at"] or 0)
        jf_existing = {
            (episode.season, episode.episode)
            for episode in series.all_episodes
            if quick_status["episodes"].get(episode.slug)
        }
    seasons = []
    for s in series.season_numbers:
        episodes = []
        for ep in series.seasons[s]:
            in_jellyfin = (ep.season, ep.episode) in jf_existing
            episodes.append({
                "season": ep.season, "episode": ep.episode, "slug": ep.slug,
                "url": ep.url, "release_name": ep.release_name,
                "queued": ep.slug in state.picked,
                "downloaded": ep.slug in downloaded,
                "in_jellyfin": in_jellyfin,
                "unreleased": ep.slug in unreleased_slugs,
            })
        seasons.append({"season": s, "episodes": episodes})
    provider = provider_for_value(series.url or series.base_slug)
    payload = {
        "title": series.title, "base_slug": series.base_slug, "url": series.url,
        "cover_url": series.cover_url, "description": series.description,
        "genres": series.genres, "seasons": seasons,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "content_language": provider_content_language(provider),
        "language_label": PROVIDER_CATALOG[provider].language_label,
        "episode_count": len(series.all_episodes),
        "watchlisted": watchlist_entry is not None,
        "availability_pending": defer_checks,
        "enrichment_pending": bool(
            defer_checks and (tmdb_client.configured or jf_client.configured)
        ),
        "jellyfin_configured": jf_client.configured,
        "jellyfin_pending": jellyfin_pending,
        "jellyfin_available": jf_identity_available,
        "jellyfin_stale": jf_stale,
        "jellyfin_checked_at": jf_checked_at,
        "watch_mode": normalize_watch_mode(
            watchlist_entry.get("download_mode") if watchlist_entry else None
        ),
        "cleanup_mode": normalize_cleanup_mode(
            watchlist_entry.get("cleanup_mode") if watchlist_entry else None
        ),
        "metadata_source": "Anbieter",
    }
    if tmdb:
        for field in (
            "title", "year", "first_air_date", "runtime", "cover_url",
            "backdrop_url", "description", "genres", "original_title",
            "rating", "vote_count", "status", "trailer", "cast", "creators",
            "networks",
        ):
            if tmdb.get(field):
                payload[field] = tmdb[field]
        payload["metadata_source"] = "TMDB"
        payload["tmdb_id"] = tmdb["tmdb_id"]
    if tmdb_id:
        payload["tmdb_id"] = tmdb_id
    if aliases:
        payload["aliases"] = aliases
    if season_episode_counts:
        payload["season_episode_counts"] = season_episode_counts
    if season_counts_checked_at:
        payload["season_counts_checked_at"] = season_counts_checked_at
    return payload


_SERVICE_EXPORTS = (
    "_sto_get_series",
    "_sto_search_series",
    "_search_series_for_provider",
    "_load_series_for_provider",
    "_search_series_provider_results",
    "search_series_candidates",
    "_SeriesCatalogEntry",
    "SeriesCatalogColdLoadLimit",
    "_series_result_identity",
    "_claim_series_identity",
    "_mix_series_provider_results",
    "_interleave_series_lists",
    "_series_provider_is_paginated",
    "_cached_series_provider_page",
    "_cache_series_provider_page",
    "_fetch_series_provider_page",
    "_load_series_provider_pages",
    "_series_catalog_sources",
    "_series_entry_to_dict",
    "_series_catalog_page_locked",
    "series_catalog_page",
    "series_search_catalog",
    "warm_home_series_cache",
    "warm_jellyfin_identity_cache",
    "_norm_title",
    "_series_search_title",
    "_episode_placeholder",
    "_best_title_match",
    "_find_series_by_title",
    "_sto_find_by_title",
    "get_series_for_value",
    "movie_to_dict",
    "movie_detail_to_dict",
    "cached_movie_source_fallbacks",
    "_series_folder_key",
    "_existing_series_dir",
    "_season_output_dir",
    "series_episode_out_path",
    "_valid_media_cached",
    "compute_downloaded_episodes",
    "series_to_dict",
)
publish_service(globals(), _SERVICE_EXPORTS)
