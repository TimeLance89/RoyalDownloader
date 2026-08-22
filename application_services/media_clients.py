"""Provider clients, Jellyfin snapshots, and TMDB metadata services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# Hilfsfunktionen (1:1 Logik aus der früheren main.py)
# ---------------------------------------------------------------------------
def get_fp_scraper() -> FilmpalastScraper:
    if state.fp_scraper is None:
        state.fp_scraper = FilmpalastScraper(progress_cb=log)
    return state.fp_scraper


def get_sto_scraper() -> SerienstreamScraper:
    if state.sto_scraper is None:
        state.sto_scraper = SerienstreamScraper(progress_cb=log)
    return state.sto_scraper


def get_moflix_scraper() -> MoflixScraper:
    if state.moflix_scraper is None:
        state.moflix_scraper = MoflixScraper(progress_cb=log)
    return state.moflix_scraper


def get_huhu_scraper() -> HuhuScraper:
    if state.huhu_scraper is None:
        state.huhu_scraper = HuhuScraper(progress_cb=log)
    return state.huhu_scraper


def get_mkissa_scraper() -> MkissaScraper:
    if state.mkissa_scraper is None:
        state.mkissa_scraper = MkissaScraper(progress_cb=log)
    return state.mkissa_scraper


def get_aniworld_scraper() -> AniWorldScraper:
    if state.aniworld_scraper is None:
        state.aniworld_scraper = AniWorldScraper(progress_cb=log)
    return state.aniworld_scraper


def get_jellyfin_client() -> JellyfinClient:
    with state.jellyfin_cache_lock:
        cfg = dict(state.jellyfin_cfg)
    return JellyfinClient(cfg.get("url", ""), cfg.get("api_key", ""))


def _build_recommender_config() -> JellyfinRecommenderConfig:
    """Baut die Laufkonfiguration aus der persistenten settings.ini."""
    jellyfin = appconfig.load_jellyfin()
    env = {
        "JELLYFIN_URL": jellyfin.get("url", ""),
        "JELLYFIN_API_KEY": jellyfin.get("api_key", ""),
        "JELLYFIN_USER_ID": jellyfin.get("user_id", ""),
        "COLLECTION_NAME": os.environ.get("COLLECTION_NAME", "Für dich empfohlen"),
        "TOP_N": os.environ.get("TOP_N", "20"),
        "RECENCY_HALF_LIFE_DAYS": os.environ.get("RECENCY_HALF_LIFE_DAYS", "180"),
        "REQUEST_TIMEOUT_SECONDS": os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"),
        "PAGE_SIZE": os.environ.get("PAGE_SIZE", "100"),
        # Das Intervall steuert der Server-Worker, nicht das Standalone-Script.
        "RUN_INTERVAL_SECONDS": "0",
    }
    return JellyfinRecommenderConfig.from_env(env)


def _run_recommender_once() -> bool:
    try:
        config = _build_recommender_config()
    except JellyfinRecommenderConfigurationError as exc:
        logger.info("Jellyfin-Empfehlungen übersprungen: %s", exc)
        return False

    try:
        recommendations = run_jellyfin_recommender_once(
            config,
            profile_callback=state.taste_profile.replace_jellyfin_items,
        )
    except JellyfinRecommenderError as exc:
        logger.warning("Jellyfin-Empfehlungen fehlgeschlagen: %s", exc)
        return False
    except Exception:
        logger.exception("Unerwarteter Fehler bei den Jellyfin-Empfehlungen")
        return False

    logger.info(
        "Jellyfin-Empfehlungen aktualisiert: %d Eintrag/Einträge",
        len(recommendations),
    )
    return True


def _recommender_interval_seconds() -> int:
    raw = os.environ.get("RECOMMENDER_INTERVAL_SECONDS", "86400").strip()
    try:
        interval = int(raw)
    except ValueError:
        logger.warning(
            "RECOMMENDER_INTERVAL_SECONDS=%r ist ungültig; nutze 86400", raw,
        )
        return 86400
    if interval < 60:
        logger.warning("RECOMMENDER_INTERVAL_SECONDS muss mindestens 60 sein; nutze 60")
        return 60
    return interval


def jellyfin_recommender_loop() -> None:
    while not _recommender_stop_event.is_set():
        successful = _run_recommender_once()
        regular_interval = _recommender_interval_seconds()
        interval = regular_interval if successful else min(regular_interval, 900)
        logger.info("Nächster Jellyfin-Empfehlungslauf in %d Sekunden", interval)
        _recommender_wake_event.wait(interval)
        _recommender_wake_event.clear()


def stop_jellyfin_recommender() -> None:
    _recommender_stop_event.set()
    _recommender_wake_event.set()
    thread = backend_value("_recommender_thread")
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)


def _set_runtime_jellyfin_config(cfg: dict) -> None:
    """Wechselt Konfiguration und Cache als eine atomare Generation."""
    normalized_cfg = dict(cfg)
    normalized_cfg["cleanup_default"] = normalize_cleanup_mode(
        normalized_cfg.get("cleanup_default")
    )
    with state.jellyfin_cache_lock:
        state.jellyfin_cfg = normalized_cfg
        state.jellyfin_config_generation += 1
        state.jellyfin_movie_data_generation += 1
        state.jellyfin_episode_data_generation += 1
        state.jellyfin_library = None
        state.jellyfin_library_time = 0.0
        state.jellyfin_library_available = False
        state.jellyfin_library_retry_after = 0.0
        state.jellyfin_movie_identities = None
        state.jellyfin_movie_identities_time = 0.0
        state.jellyfin_movie_identities_available = False
        state.jellyfin_movie_identities_retry_after = 0.0
        state.jellyfin_episodes = None
        state.jellyfin_episodes_time = 0.0
        state.jellyfin_episodes_available = False
        state.jellyfin_episodes_retry_after = 0.0
        state.jellyfin_series = None
        state.jellyfin_series_time = 0.0
        state.jellyfin_series_available = False
        state.jellyfin_series_retry_after = 0.0
        state.jellyfin_targeted_episodes.clear()
        state.jellyfin_user_episodes = None
        state.jellyfin_user_episodes_time = 0.0
        state.jellyfin_user_episodes_available = False
        state.jellyfin_user_episodes_retry_after = 0.0
        with state.watchlist_lock:
            for entry in state.watchlist:
                entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
                entry["last_error"] = "Jellyfin-Konfiguration wird geprüft"


def get_tmdb_client() -> TMDBClient:
    return state.tmdb_client


def get_tmdb_series(title: str, tmdb_id="", force: bool = False) -> Optional[dict]:
    """Eine gespeicherte TMDB-ID bleibt autoritativ; Titelsuche nur initial."""
    client = get_tmdb_client()
    if tmdb_id:
        return client.series_by_id(tmdb_id, title, force=force)
    return client.series(title, force=force)


def _unreleased_episode_keys(
    tmdb_id, keys: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """(Staffel, Episode)-Paare aus ``keys``, die laut TMDB-Ausstrahlungsdatum
    noch nicht erschienen sind oder unbekannt sind.

    Liefert eine leere Menge, wenn TMDB nicht konfiguriert ist oder keine
    Staffeldaten liefert (fail-open: dann bleibt das bisherige Verhalten
    unverändert, statt fälschlich alles zu sperren).
    """
    client = get_tmdb_client()
    if not client.configured or not tmdb_id or not keys:
        return set()
    today = time.strftime("%Y-%m-%d", time.localtime())
    unreleased: set[tuple[int, int]] = set()
    for season_number in {season for season, _episode in keys}:
        air_dates = client.season_air_dates(tmdb_id, season_number)
        if air_dates is None:
            continue
        for season, episode in keys:
            if season != season_number:
                continue
            air_date = air_dates.get(episode)
            if not air_date or air_date > today:
                unreleased.add((season, episode))
    return unreleased


def _unreleased_episode_slugs(series: FilmpalastSeries, tmdb_id) -> set[str]:
    """Episoden, die laut TMDB-Ausstrahlungsdatum noch nicht erschienen sind.

    Providerunabhängig, da manche Anbieter geplante Episoden schon vor dem
    eigentlichen Release listen.
    """
    by_key = {
        (ep.season, ep.episode): ep.slug
        for season_number in series.season_numbers
        for ep in series.seasons.get(season_number, [])
    }
    unreleased_keys = _unreleased_episode_keys(tmdb_id, set(by_key))
    scheduled = {ep.slug for ep in series.all_episodes if not ep.is_released}
    return {by_key[key] for key in unreleased_keys} | scheduled


JELLYFIN_CACHE_TTL = 300  # Sekunden – wie lange die komplette Filmliste gecacht wird
JELLYFIN_ERROR_RETRY_SECONDS = 30
JELLYFIN_TARGETED_CACHE_TTL = 60
JELLYFIN_TARGETED_ERROR_RETRY_SECONDS = 15


def get_jellyfin_library(force: bool = False) -> Optional[List[dict]]:
    """Liefert alle Filme aus Jellyfin (gecacht), damit auch Neu/Top/Genre-Listen
    ohne einen Live-Request pro Aufruf auf Duplikate geprüft werden können."""
    with state.jellyfin_library_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_library is None
                or (now - state.jellyfin_library_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_library_retry_after:
                return state.jellyfin_library
            needs_fetch = needs_fetch or not state.jellyfin_library_available
            if not needs_fetch:
                return state.jellyfin_library
            state.jellyfin_movie_data_generation += 1
        fresh = jf_client.list_movies()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_library
            state.jellyfin_movie_data_generation += 1
            if fresh is not None:
                state.jellyfin_library = fresh
                state.jellyfin_library_time = time.time()
                state.jellyfin_library_available = True
                state.jellyfin_library_retry_after = 0.0
            else:
                state.jellyfin_library_available = False
                state.jellyfin_library_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_library


def get_jellyfin_movie_identities(force: bool = False) -> Optional[List[dict]]:
    """Kleiner, unabhängiger Index für interaktive Film-Badges."""
    with state.jellyfin_movie_identities_fetch_lock:
        with state.jellyfin_cache_lock:
            client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            if not client.configured:
                return None
            if not force and now < state.jellyfin_movie_identities_retry_after:
                return state.jellyfin_movie_identities
            needs_fetch = (
                force
                or state.jellyfin_movie_identities is None
                or not state.jellyfin_movie_identities_available
                or (now - state.jellyfin_movie_identities_time) > JELLYFIN_CACHE_TTL
            )
            if not needs_fetch:
                return state.jellyfin_movie_identities
        fresh = client.list_movie_identities()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_movie_identities
            if fresh is not None:
                state.jellyfin_movie_identities = fresh
                state.jellyfin_movie_identities_time = time.time()
                state.jellyfin_movie_identities_available = True
                state.jellyfin_movie_identities_retry_after = 0.0
            else:
                state.jellyfin_movie_identities_available = False
                state.jellyfin_movie_identities_retry_after = (
                    time.time() + JELLYFIN_ERROR_RETRY_SECONDS
                )
            return state.jellyfin_movie_identities


def get_jellyfin_episodes(force: bool = False) -> Optional[List[dict]]:
    """Liefert alle Serien-Episoden aus Jellyfin (gecacht) – damit die
    Watchlist-Prüfung weiß, ob eine neu gescrapete Episode tatsächlich
    noch fehlt oder bereits in der Bibliothek liegt."""
    with state.jellyfin_episodes_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_episodes is None
                or (now - state.jellyfin_episodes_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_episodes_retry_after:
                return state.jellyfin_episodes
            needs_fetch = needs_fetch or not state.jellyfin_episodes_available
            if not needs_fetch:
                return state.jellyfin_episodes
            state.jellyfin_episode_data_generation += 1
        fresh = jf_client.list_episodes()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_episodes
            state.jellyfin_episode_data_generation += 1
            if fresh is not None:
                state.jellyfin_episodes = fresh
                state.jellyfin_episodes_time = time.time()
                state.jellyfin_episodes_available = True
                state.jellyfin_episodes_retry_after = 0.0
            else:
                state.jellyfin_episodes_available = False
                state.jellyfin_episodes_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_episodes


def get_jellyfin_series(force: bool = False) -> Optional[List[dict]]:
    """Liefert Jellyfin-Serien inklusive Provider-IDs für stabiles Matching."""
    with state.jellyfin_series_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_series is None
                or (now - state.jellyfin_series_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_series_retry_after:
                return state.jellyfin_series
            needs_fetch = needs_fetch or not state.jellyfin_series_available
            if not needs_fetch:
                return state.jellyfin_series
            state.jellyfin_episode_data_generation += 1
        fresh = jf_client.list_series()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_series
            state.jellyfin_episode_data_generation += 1
            if fresh is not None:
                state.jellyfin_series = fresh
                state.jellyfin_series_time = time.time()
                state.jellyfin_series_available = True
                state.jellyfin_series_retry_after = 0.0
            else:
                state.jellyfin_series_available = False
                state.jellyfin_series_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_series


def get_jellyfin_targeted_episodes(
    series_ids: set[str], force: bool = False,
) -> tuple[Optional[List[dict]], bool, bool, float]:
    """Liefert Episoden nur für die eindeutig erkannte Jellyfin-Serie.

    Rückgabe: ``(items, live_available, stale, checked_at)``. Bei einem
    Netzwerkfehler bleibt ein letzter bekannter Stand sichtbar, wird aber als
    veraltet markiert und darf keine Downloadfreigabe vortäuschen.
    """
    clean_ids = tuple(sorted({str(value).strip() for value in series_ids if str(value).strip()}))
    if not clean_ids:
        return [], True, False, time.time()
    key = "|".join(clean_ids)

    def cached_result(now: float, allow_stale: bool = False):
        record = state.jellyfin_targeted_episodes.get(key)
        if not record:
            return None
        age = now - float(record.get("checked_at") or 0)
        if not force and age <= JELLYFIN_TARGETED_CACHE_TTL:
            return list(record.get("items") or []), True, False, float(record["checked_at"])
        if not force and now < float(record.get("retry_after") or 0):
            return (
                list(record.get("items") or []), False, True,
                float(record.get("checked_at") or 0),
            )
        if allow_stale:
            return (
                list(record.get("items") or []), False, True,
                float(record.get("checked_at") or 0),
            )
        return None

    with state.jellyfin_cache_lock:
        jf_client = get_jellyfin_client()
        generation = state.jellyfin_config_generation
        if not jf_client.configured:
            return None, False, False, 0.0
        cached = cached_result(time.time())
        if cached is not None:
            return cached

    with state.jellyfin_targeted_fetch_lock:
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return None, False, False, 0.0
            cached = cached_result(time.time())
            if cached is not None:
                return cached
        fresh: List[dict] = []
        succeeded = True
        for series_id in clean_ids:
            items = jf_client.list_episodes_for_series(series_id)
            if items is None:
                succeeded = False
                break
            fresh.extend(items)
        now = time.time()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return None, False, False, 0.0
            if succeeded:
                state.jellyfin_targeted_episodes[key] = {
                    "items": fresh,
                    "checked_at": now,
                    "retry_after": 0.0,
                }
                return list(fresh), True, False, now
            previous = state.jellyfin_targeted_episodes.get(key)
            if previous:
                previous["retry_after"] = now + JELLYFIN_TARGETED_ERROR_RETRY_SECONDS
                return cached_result(now, allow_stale=True)
            return None, False, False, 0.0


def _series_jellyfin_status(
    title: str,
    *,
    tmdb_id="",
    aliases=(),
    episodes: List[dict],
    force: bool = False,
) -> dict:
    """Schneller, eigenständiger Jellyfin-Status einer geöffneten Serie."""
    client = get_jellyfin_client()
    empty = {str(item.get("slug") or ""): False for item in episodes if item.get("slug")}
    if not client.configured:
        return {
            "configured": False, "available": True, "stale": False,
            "checked_at": 0.0, "episodes": empty, "count": 0,
        }
    series_items = get_jellyfin_series(force=force)
    with state.jellyfin_cache_lock:
        series_index_available = bool(
            series_items is not None and state.jellyfin_series_available
        )
    if not series_index_available:
        return {
            "configured": True, "available": False, "stale": False,
            "checked_at": 0.0, "episodes": empty, "count": 0,
        }
    series_ids = client.series_ids_for(
        title, tmdb_id=tmdb_id, aliases=aliases, items=series_items,
    )
    if series_ids is None:
        return {
            "configured": True, "available": False, "stale": False,
            "checked_at": time.time(), "episodes": empty, "count": 0,
        }
    targeted, live_available, stale, checked_at = get_jellyfin_targeted_episodes(
        series_ids, force=force,
    )
    existing = (
        client.episodes_for_series(
            title, items=targeted, aliases=aliases, series_ids=series_ids,
        )
        if targeted is not None else set()
    )
    statuses = {
        str(item.get("slug") or ""): (
            int(item.get("season") or 0), int(item.get("episode") or 0)
        ) in existing
        for item in episodes if item.get("slug")
    }
    return {
        "configured": True,
        "available": live_available,
        "stale": stale,
        "checked_at": checked_at,
        "episodes": statuses,
        "count": sum(statuses.values()),
    }


def get_jellyfin_user_episodes(force: bool = False) -> Optional[List[dict]]:
    """Liefert Episoden mit Gesehen-Status des konfigurierten Benutzers."""
    with state.jellyfin_user_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            user_id = state.jellyfin_cfg.get("user_id", "").strip()
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_user_episodes is None
                or (now - state.jellyfin_user_episodes_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured or not user_id:
                return None
            if not force and now < state.jellyfin_user_episodes_retry_after:
                return state.jellyfin_user_episodes
            needs_fetch = needs_fetch or not state.jellyfin_user_episodes_available
            if not needs_fetch:
                return state.jellyfin_user_episodes
            state.jellyfin_episode_data_generation += 1
        items = jf_client.list_episodes_with_user_data(user_id)
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_user_episodes
            state.jellyfin_episode_data_generation += 1
            if items is None:
                state.jellyfin_user_episodes_available = False
                state.jellyfin_user_episodes_retry_after = (
                    time.time() + JELLYFIN_ERROR_RETRY_SECONDS
                )
                return state.jellyfin_user_episodes
            state.jellyfin_user_episodes = items
            state.jellyfin_user_episodes_time = time.time()
            state.jellyfin_user_episodes_available = True
            state.jellyfin_user_episodes_retry_after = 0.0
            return state.jellyfin_user_episodes


_SERVICE_EXPORTS = (
    "get_fp_scraper",
    "get_sto_scraper",
    "get_moflix_scraper",
    "get_huhu_scraper",
    "get_mkissa_scraper",
    "get_aniworld_scraper",
    "get_jellyfin_client",
    "_build_recommender_config",
    "_run_recommender_once",
    "_recommender_interval_seconds",
    "jellyfin_recommender_loop",
    "stop_jellyfin_recommender",
    "_set_runtime_jellyfin_config",
    "get_tmdb_client",
    "get_tmdb_series",
    "_unreleased_episode_keys",
    "_unreleased_episode_slugs",
    "JELLYFIN_CACHE_TTL",
    "JELLYFIN_ERROR_RETRY_SECONDS",
    "JELLYFIN_TARGETED_CACHE_TTL",
    "JELLYFIN_TARGETED_ERROR_RETRY_SECONDS",
    "get_jellyfin_library",
    "get_jellyfin_movie_identities",
    "get_jellyfin_episodes",
    "get_jellyfin_series",
    "get_jellyfin_targeted_episodes",
    "_series_jellyfin_status",
    "get_jellyfin_user_episodes",
)
publish_service(globals(), _SERVICE_EXPORTS)
