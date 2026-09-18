"""Queue execution, existing-media checks, and download scheduling services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


def _existing_valid_movie_path(out_root: Path, movie: FilmpalastMovie) -> Optional[Path]:
    """Findet eine bereits vollständig geladene Filmdatei dieses Titels."""
    titles = [clean_movie_title(movie.title)]
    if movie.title not in titles:
        titles.append(movie.title)
    checked: set = set()
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    for title in titles:
        expected = out_root / build_movie_filename(title, movie.year)
        try:
            candidates = expected.parent.glob(expected.stem + ".*")
            for candidate in candidates:
                if candidate in checked or candidate.suffix.casefold() not in video_suffixes:
                    continue
                checked.add(candidate)
                valid, detail = validate_media_file(candidate)
                if valid:
                    log(f"  Bereits vollständig vorhanden: {candidate.name} ({detail})")
                    return candidate
                log(f"  Vorhandene Datei ist ungültig und wird ersetzt: {candidate.name} ({detail})", "warn")
        except OSError as exc:
            log(f"  Vorhandene Filmdatei konnte nicht geprüft werden: {exc}", "warn")
    return None


def _movie_subscription_download_finished(
    movie_slug: str, out_path: Path, quality: str,
) -> None:
    """Bucht ein erfolgreiches Upgrade und entfernt erst danach die alte Datei."""
    changed = False
    subscription = None
    old_media_path = ""
    with state.movie_subscriptions_lock:
        subscription = next(
            (
                entry for entry in state.movie_subscriptions
                if entry.get("pending_slug") == movie_slug
                or entry.get("source_slug") == movie_slug
            ),
            None,
        )
        if subscription is None:
            return
        rank = movie_quality_rank(quality)
        subscription["current_quality_rank"] = max(
            int(subscription.get("current_quality_rank") or 0), rank,
        )
        subscription["current_quality"] = quality or (
            f"{rank}p" if rank else "Qualität unbekannt"
        )
        subscription["pending_slug"] = ""
        subscription["last_error"] = ""
        subscription["upgrade_available_rank"] = 0
        subscription["upgrade_available_quality"] = ""
        subscription["last_upgraded"] = time.time()
        old_media_path = str(subscription.get("existing_path") or "")
        changed = True
        _persist_movie_subscriptions_background()

    # DownloadJob hat die neue Datei bereits atomar committed. Bei abweichender
    # Container-Endung bleibt die alte Datei daneben liegen; nur dann bereinigen.
    try:
        candidates = [
            path for path in out_path.parent.glob(out_path.stem + ".*")
            if path.suffix.casefold() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
            and path.is_file()
        ]
        valid_candidates = [
            path for path in candidates if validate_media_file(path)[0]
        ]
        if valid_candidates:
            newest = max(valid_candidates, key=lambda path: path.stat().st_mtime_ns)
            old_path = Path(old_media_path)
            if old_path.is_absolute():
                root = Path(state.save_path).expanduser().resolve(strict=False)
                resolved_old = old_path.expanduser().resolve(strict=False)
                try:
                    resolved_old.relative_to(root)
                    old_is_safe = True
                except ValueError:
                    old_is_safe = False
                if old_is_safe and resolved_old != newest.resolve(strict=False):
                    resolved_old.unlink(missing_ok=True)
                    log(f"Qualitäts-Upgrade: alte Filmdatei gelöscht: {resolved_old.name}")
            for candidate in candidates:
                if candidate != newest:
                    candidate.unlink(missing_ok=True)
                    log(f"Qualitäts-Upgrade: alte Filmdatei gelöscht: {candidate.name}")
    except OSError as exc:
        log(f"Qualitäts-Upgrade: alte Filmdatei konnte nicht bereinigt werden: {exc}", "warn")
    if changed:
        broadcast({"type": "movie_subscriptions_update", **movie_subscriptions_payload()})


def _movie_subscription_download_failed(movie_slug: str, message: str) -> None:
    changed = False
    with state.movie_subscriptions_lock:
        for entry in state.movie_subscriptions:
            if entry.get("pending_slug") != movie_slug:
                continue
            entry["pending_slug"] = ""
            entry["last_error"] = "" if message == "Abgebrochen" else str(message)[:240]
            entry["last_checked"] = time.time()
            changed = True
        if changed:
            _persist_movie_subscriptions_background()
    if changed:
        broadcast({"type": "movie_subscriptions_update", **movie_subscriptions_payload()})


def _existing_valid_episode_path(series_title: str, season: int, episode: int) -> Optional[Path]:
    expected = series_episode_out_path(series_title, season, episode)
    if not expected.parent.exists():
        return None
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    for candidate in expected.parent.glob(expected.stem + ".*"):
        if candidate.suffix.casefold() not in video_suffixes:
            continue
        valid, detail = _valid_media_cached(candidate)
        if valid:
            return candidate
        log(f"  Vorhandene Episode ist ungültig und wird ersetzt: {candidate.name} ({detail})", "warn")
    return None


def _episode_jellyfin_identity(
    base_slug: str,
    series_title: str,
    jf_client: JellyfinClient,
    jf_series: Optional[List[dict]],
) -> tuple[tuple[str, ...], set[str], str]:
    """Ermittelt eine eindeutige Serienidentität; Mehrdeutigkeit blockiert."""
    with state.watchlist_lock:
        stored = watchlist_lookup(base_slug)
        entry = dict(stored) if stored else {}
    tmdb_id = str(entry.get("tmdb_id") or "")
    aliases = list(dict.fromkeys(filter(None, (
        series_title,
        entry.get("title", ""),
        *(entry.get("aliases") or []),
    ))))
    tmdb = get_tmdb_series(series_title, tmdb_id)
    if tmdb:
        tmdb_id = str(tmdb_id or tmdb.get("tmdb_id") or "")
        aliases = list(dict.fromkeys(filter(None, (
            *aliases,
            tmdb.get("title", ""),
            tmdb.get("original_title", ""),
        ))))
    series_ids = jf_client.series_ids_for(
        series_title, tmdb_id=tmdb_id, aliases=aliases, items=jf_series,
    )
    if series_ids is None:
        raise RuntimeError("Jellyfin-Zuordnung mehrdeutig")
    return tuple(aliases), series_ids, tmdb_id


def _is_jellyfin_safety_block(reason: str) -> bool:
    return str(reason or "").startswith("Jellyfin")


def _content_already_available(movie: FilmpalastMovie, slug: str) -> tuple[bool, str]:
    """Serverseitiger Duplikatschutz für manuelle und automatische Queue-Adds."""
    episode_info = parse_episode_slug(slug)
    jf_client = get_jellyfin_client()
    if episode_info:
        series_title = strip_episode_suffix(movie.title) or movie.title
        if _existing_valid_episode_path(series_title, episode_info[1], episode_info[2]):
            return True, "lokal vorhanden"
        if jf_client.configured:
            jf_series = get_jellyfin_series()
            with state.jellyfin_cache_lock:
                config_generation = state.jellyfin_config_generation
                data_generation = state.jellyfin_episode_data_generation
                series_available = state.jellyfin_series_available
            if jf_series is None or not series_available:
                return True, "Jellyfin-Serienindex nicht verfügbar"
            try:
                aliases, series_ids, _tmdb_id = _episode_jellyfin_identity(
                    episode_info[0], series_title, jf_client, jf_series,
                )
            except RuntimeError as exc:
                return True, str(exc)
            items, live_available, _stale, _checked_at = get_jellyfin_targeted_episodes(
                series_ids,
            )
            if items is None or not live_available:
                return True, "Jellyfin nicht erreichbar"
            with state.jellyfin_cache_lock:
                if (
                    config_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_episode_data_generation
                ):
                    return True, "Jellyfin-Daten werden gerade aktualisiert"
            if jf_client.has_episode(
                series_title, episode_info[1], episode_info[2], items=items,
                aliases=aliases, series_ids=series_ids,
            ):
                return True, "in Jellyfin vorhanden"
        return False, ""

    if _existing_valid_movie_path(Path(state.save_path), movie) is not None:
        return True, "lokal vorhanden"
    if jf_client.configured:
        items = get_jellyfin_library()
        with state.jellyfin_cache_lock:
            config_generation = state.jellyfin_config_generation
            data_generation = state.jellyfin_movie_data_generation
            library_available = state.jellyfin_library_available
        if items is None or not library_available:
            return True, "Jellyfin nicht erreichbar"
        title = clean_movie_title(movie.title)
        tmdb = get_tmdb_client().movie_summary(title, movie.year)
        with state.jellyfin_cache_lock:
            if (
                config_generation != state.jellyfin_config_generation
                or data_generation != state.jellyfin_movie_data_generation
            ):
                return True, "Jellyfin-Daten werden gerade aktualisiert"
        if jf_client.match(
            title, movie.year, items=items, tmdb_id=(tmdb or {}).get("tmdb_id", ""),
        ):
            return True, "in Jellyfin vorhanden"
    return False, ""


def run_download_queue(
    jobs: List[tuple],
    out_root: Path,
    movie_fallbacks: Optional[Dict[str, List[FilmpalastMovie]]] = None,
    start_queue: bool = True,
    cancelled: Optional[Callable[[], bool]] = None,
):
    """jobs: Liste von (movie, slug)-Paaren. Der slug ist der Queue-Schlüssel
    (z.B. 'serienstream:the-last-of-us-s01e01') – daraus wird die Serie/Staffel/
    Episode erkannt. Wichtig: NICHT aus movie.url ableiten, denn bei s.to/moflix
    ist das letzte URL-Segment 'episode-1'/'1' und würde die Serie fälschlich als
    Film in den Wurzelordner legen.

    SerienStream-Episoden werden erst hier unmittelbar vor der Verarbeitung
    geladen. Provider-Sperren lassen ihren logischen Queue-Claim offen."""
    out_root.mkdir(parents=True, exist_ok=True)
    unsupported_domains: set = set()
    gated_jobs: List[tuple] = []   # (movie, slug) die am Captcha-Gate hingen
    queued_slugs: set = set()

    for movie, movie_slug in jobs:
        if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
            continue
        log(f"─── {movie.title} ───")

        # Bereits vorhandene Episode NICHT erneut auflösen/laden. Spart /r?t=-
        # Requests (wichtig fürs Gate) und macht das erneute Anstoßen nach einem
        # Captcha-Cooldown praktikabel: nur die noch fehlenden Folgen werden
        # verarbeitet statt der ganzen Staffel.
        ep_info = parse_episode_slug(movie_slug)
        if ep_info:
            # Originalen Serientitel EIN EINZIGES MAL festhalten (vor einem
            # etwaigen Hoster-Refresh oder Fallback), damit der "schon
            # vorhanden?"-Check und der tatsächliche Zielordner garantiert
            # denselben Serien-/Staffel-Ordner verwenden. Würde man den Titel
            # später aus einem inzwischen ersetzten movie-Objekt neu ableiten,
            # könnte eine leicht abweichende Anbieter-Formatierung die Episode
            # in einem zweiten, abweichenden Ordner landen lassen.
            orig_series_title = strip_episode_suffix(movie.title) or movie.title
            existing_file = _existing_valid_episode_path(orig_series_title, ep_info[1], ep_info[2])
            if existing_file is not None:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(True, "bereits vorhanden", movie.title, existing_file, slug=movie_slug)
                continue

            # Konnte bereits die Episodenseite während der Vorbereitung nicht
            # geladen werden, bleibt der logische Job trotzdem erhalten. Vor
            # jedem Versuch die gewählte Quelle erneut laden; danach folgen die
            # Katalog-Fallbacks und bei Serienstream gegebenenfalls Cooldowns.
            primary_unavailable = False
            if not movie.hosters:
                refreshed_movie = None
                is_sto = provider_for_value(movie_slug) == "serienstream"
                if is_sto and not state.provider_health.request_allowed("serienstream"):
                    log(
                        f"SerienStream befindet sich im Cooldown – Episode "
                        f"S{ep_info[1]:02d}E{ep_info[2]:02d} bleibt vorgemerkt."
                    )
                else:
                    try:
                        refreshed_movie = load_movie_for_slug(movie_slug)
                    except ProviderBlockedError as exc:
                        _mark_serienstream_blocked(exc.reason, str(exc))
                        log(f"  Episodenseite blockiert: {exc}", "warn")
                    except Exception as exc:
                        log(f"  Episodenseite noch nicht ladbar: {exc}", "warn")
                        if is_sto:
                            _mark_serienstream_blocked("provider_error", str(exc))
                if refreshed_movie and refreshed_movie.hosters:
                    movie = refreshed_movie
                    state.fp_movies[movie_slug] = refreshed_movie
                elif movie_slug.startswith(SERIENSTREAM_PREFIX):
                    primary_unavailable = True
        else:
            primary_unavailable = False
            existing_movie = (
                None
                if bool(getattr(movie, "_allow_quality_upgrade", False))
                else _existing_valid_movie_path(out_root, movie)
            )
            if existing_movie is not None:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(True, "bereits vorhanden", movie.title, existing_movie, slug=movie_slug)
                continue

        source_movies = [movie]
        seen_source_urls = {movie.url}
        known_fallbacks = (movie_fallbacks or {}).get(movie_slug, [])
        for fallback_movie in known_fallbacks:
            if fallback_movie.url in seen_source_urls:
                continue
            source_movies.append(fallback_movie)
            seen_source_urls.add(fallback_movie.url)
        # Ein leerer, früher aufgebauter Episoden-Fallback-Eintrag beweist
        # nicht, dass alle Anbieter im jetzigen Moment erfolglos sind. Gerade
        # bei einer späteren SerienStream-Sperre muss die exakte Laufzeitsuche
        # (Moflix/Huhu/weitere) noch einmal stattfinden dürfen. Erst dieser
        # Lauf markiert die Suche für den aktuellen Versuch als vollständig.
        source_fallbacks_loaded = [
            movie_fallbacks is not None and movie_slug in movie_fallbacks
            if not ep_info else False
        ]
        # Gilt für den kompletten Versuch dieses Slugs, quellenübergreifend:
        # ein Embed ohne Stream-URL bleibt für diesen Lauf ausgeschlossen.
        barren_hoster_urls: set = set()
        # Watchlist-Einträge behalten ihren ursprünglichen Katalog-Slug. Wurde
        # später eine andere Primärquelle konfiguriert, laden wir deren Treffer
        # vorab und sortieren die tatsächlich nutzbaren Quellen neu.
        if (
            ep_info
            and provider_for_value(movie_slug) != provider_priority("series")[0]
            and not source_fallbacks_loaded[0]
        ):
            source_fallbacks_loaded[0] = True
            alternatives = find_episode_fallbacks(
                orig_series_title,
                ep_info[1],
                ep_info[2],
                aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                source_slug=movie_slug,
            )
            for candidate in alternatives:
                if candidate.url not in seen_source_urls:
                    source_movies.append(candidate)
                    seen_source_urls.add(candidate.url)
        if ep_info:
            source_movies = _ordered_episode_sources(source_movies)
            movie = source_movies[0]
        source_index = 0

        with state.hoster_extract_lock:
            result = _extract_from_movie(
                movie, unsupported_domains, barren_hoster_urls=barren_hoster_urls,
            )
        if primary_unavailable:
            # Eine temporaer nicht lesbare s.to-Episodenseite wird wie das
            # Redirect-Gate behandelt und nicht sofort terminal gezaehlt.
            if state.provider_health.request_allowed("serienstream"):
                _mark_serienstream_blocked(
                    "provider_error", "SerienStream-Episodenseite nicht ladbar",
                )
            result.gated = True
        gate_seen = [bool(result.gated)]

        # Scheitert bereits die Extraktion/Probe, denselben Inhalt sofort beim
        # ersten exakten Katalog-Fallback versuchen. Das gilt nicht nur bei Captcha.
        if not result.stream_info:
            if not source_fallbacks_loaded[0]:
                if ep_info:
                    alternatives = find_episode_fallbacks(
                        orig_series_title,
                        ep_info[1],
                        ep_info[2],
                        aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                        source_slug=movie_slug,
                        limit=1,
                    )
                    source_movies.extend(
                        candidate for candidate in alternatives
                        if candidate.url not in {m.url for m in source_movies}
                    )
                    # Ein erster exakter Treffer wird sofort versucht. Erst
                    # wenn dessen Extraktion oder Download scheitert, werden
                    # die übrigen Kataloge geladen.
                    source_fallbacks_loaded[0] = not bool(alternatives)
                else:
                    source_fallbacks_loaded[0] = True
                    source_movies.extend(find_movie_source_fallbacks(
                        source_movies[0], movie_slug, {m.url for m in source_movies},
                    ))
            next_index = 1
            while next_index < len(source_movies):
                next_movie = source_movies[next_index]
                log(f"  Wechsle Quelle: {strip_source_suffix(next_movie.title)}", "warn")
                with state.hoster_extract_lock:
                    source_result = _extract_from_movie(
                        next_movie,
                        unsupported_domains,
                        barren_hoster_urls=barren_hoster_urls,
                    )
                gate_seen[0] = gate_seen[0] or bool(source_result.gated)
                next_index += 1
                if not source_result.stream_info:
                    continue
                movie = next_movie
                result = source_result
                source_index = next_index - 1
                break

            # Der schnellste Katalogtreffer hatte zwar Hoster, ließ sich aber
            # nicht extrahieren. Jetzt erst die restlichen Provider laden und
            # in derselben Vorbereitung weiterprobieren.
            if ep_info and not result.stream_info and not source_fallbacks_loaded[0]:
                source_fallbacks_loaded[0] = True
                tried_providers = {
                    _movie_provider(candidate, movie_slug)
                    for candidate in source_movies
                }
                tried_providers.discard("")
                alternatives = find_episode_fallbacks(
                    orig_series_title,
                    ep_info[1],
                    ep_info[2],
                    aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                    source_slug=movie_slug,
                    excluded_providers=tried_providers,
                )
                known_urls = {candidate.url for candidate in source_movies}
                source_movies.extend(
                    candidate for candidate in alternatives
                    if candidate.url not in known_urls
                )
                while next_index < len(source_movies):
                    next_movie = source_movies[next_index]
                    log(
                        f"  Wechsle Quelle: {strip_source_suffix(next_movie.title)}",
                        "warn",
                    )
                    with state.hoster_extract_lock:
                        source_result = _extract_from_movie(
                            next_movie,
                            unsupported_domains,
                            barren_hoster_urls=barren_hoster_urls,
                        )
                    gate_seen[0] = gate_seen[0] or bool(source_result.gated)
                    next_index += 1
                    if not source_result.stream_info:
                        continue
                    movie = next_movie
                    result = source_result
                    source_index = next_index - 1
                    break

        if not result.stream_info:
            if gate_seen[0]:
                # s.to-Gate aktiv UND kein Fallback nutzbar – bis zur nächsten
                # Provider-Probe zurückstellen (NICHT als erledigt zählen).
                gated_jobs.append((source_movies[0], movie_slug))
                log("  Zurückgestellt – serienstream Captcha-Gate aktiv (Fallback erfolglos)", "warn")
            else:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(False, "kein Hoster extrahierbar", movie.title, Path(""), slug=movie_slug)
            continue

        # Episode vs. Film aus dem Queue-Slug erkennen (NICHT aus movie.url –
        # s.to/moflix haben dort 'episode-1'/'1' als letztes Segment).
        episode_info = parse_episode_slug(movie_slug)
        if episode_info:
            _base_slug, season, episode = episode_info
            out_path = series_episode_out_path(orig_series_title, season, episode)
        else:
            primary_movie = source_movies[0]
            out_path = out_root / build_movie_filename(
                clean_movie_title(primary_movie.title), primary_movie.year,
            )

        enqueued = _enqueue_hoster_attempt(
            movie=movie,
            movie_slug=movie_slug,
            out_path=out_path,
            result=result,
            unsupported_domains=unsupported_domains,
            failed_hoster_urls=set(),
            attempt_errors=[],
            source_movies=source_movies,
            source_index=source_index,
            source_fallbacks_loaded=source_fallbacks_loaded,
            refreshed_hoster_urls=set(),
            barren_hoster_urls=barren_hoster_urls,
            cancelled=cancelled,
            gate_seen=gate_seen,
            gate_retry=lambda primary=source_movies[0], slug=movie_slug: _defer_provider_episode(
                primary, slug, out_root, movie_fallbacks,
            ),
        )
        if enqueued:
            queued_slugs.add(movie_slug)

    # Am Captcha-Gate hängengebliebene Episoden zentral sammeln. Das gilt auch
    # für einen einzelnen Vorbereitungsjob ohne Erfolg.
    if gated_jobs:
        deferred = 0
        for gated_movie, gated_slug in gated_jobs:
            if (cancelled and cancelled()) or not _queue_slug_claimed(gated_slug):
                continue
            if _defer_provider_episode(
                gated_movie, gated_slug, out_root, movie_fallbacks,
            ):
                deferred += 1
                queued_slugs.add(gated_slug)
                continue
            # Ein zurückgestellter Provider-Job ist nie ein terminaler Fehler.
        if deferred:
            log(
                f"⏳ {deferred} Episode(n) warten auf die nächste einzelne "
                f"SerienStream-Probe."
            )

    # Erst nach der Gate-Entscheidung starten. on_queue_done sieht dadurch
    # entweder den wartenden Provider-Job oder einen terminalen Versuch.
    if start_queue:
        log("─── Starte Queue (max. 2 parallel) ───")
        state.dl_queue.start()

    # Telegram benötigt die konkreten Slugs, um bei Mehrfachanfragen sofort zu
    # erkennen, welche Episoden tatsächlich gestartet/zurückgestellt wurden.
    return queued_slugs


_SERVICE_EXPORTS = (
    "_existing_valid_movie_path",
    "_movie_subscription_download_finished",
    "_movie_subscription_download_failed",
    "_existing_valid_episode_path",
    "_episode_jellyfin_identity",
    "_is_jellyfin_safety_block",
    "_content_already_available",
    "run_download_queue",
)
publish_service(globals(), _SERVICE_EXPORTS)
