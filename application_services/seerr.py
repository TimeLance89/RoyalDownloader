"""Seerr request synchronization and media matching services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# Seerr-Anfragen (Moonfin/Fire TV -> Seerr -> Royal Downloader)
# ---------------------------------------------------------------------------
SEERR_MEDIA_AVAILABLE = 5
SEERR_SCAN_RETRY_SECONDS = 5 * 60


def configure_moonfin_seerr(seerr_url: str, enabled: bool) -> dict:
    """Konfiguriert Plugin 1.9.1 und aktuelle Versionen ohne andere Werte zu löschen."""
    jf_url = str(state.jellyfin_cfg.get("url") or "").strip().rstrip("/")
    api_key = str(state.jellyfin_cfg.get("api_key") or "").strip()
    user_id = str(state.jellyfin_cfg.get("user_id") or "").strip()
    if not jf_url or not api_key:
        return {"configured": False, "detail": "Jellyfin ist nicht konfiguriert."}
    session = requests.Session()
    headers = {"X-Emby-Token": api_key, "Accept": "application/json"}
    try:
        response = session.get(f"{jf_url}/Plugins", headers=headers, timeout=10)
        response.raise_for_status()
        plugins = response.json()
        plugin = next(
            (item for item in plugins if str(item.get("Name") or "").casefold() == "moonfin"),
            None,
        )
        if not plugin or not plugin.get("Id"):
            return {"configured": False, "detail": "Moonfin-Plugin ist nicht installiert."}
        plugin_id = plugin["Id"]
        config_url = f"{jf_url}/Plugins/{plugin_id}/Configuration"
        response = session.get(config_url, headers=headers, timeout=10)
        response.raise_for_status()
        plugin_config = response.json()
        if "SeerrEnabled" in plugin_config or "SeerrUrl" in plugin_config:
            plugin_config.update({
                "SeerrEnabled": bool(enabled),
                "SeerrUrl": seerr_url,
                "SeerrDisplayName": "Seerr",
            })
        else:
            plugin_config.update({
                "JellyseerrEnabled": bool(enabled),
                "JellyseerrUrl": seerr_url,
                "JellyseerrDisplayName": "Seerr",
            })
        # Benutzerprofil zuerst speichern. Das anschließende Admin-Config-POST
        # kann das Plugin kurz neu laden; umgekehrt wäre das Profil-POST racy.
        if user_id:
            settings_url = f"{jf_url}/Moonfin/Settings/{user_id}"
            response = session.get(settings_url, headers=headers, timeout=10)
            current = response.json() if response.status_code == 200 else {}
            settings = dict(current) if isinstance(current, dict) else {}
            settings["schemaVersion"] = 2
            settings["syncEnabled"] = True
            for profile_name in ("global", "tv"):
                profile = settings.get(profile_name)
                profile = dict(profile) if isinstance(profile, dict) else {}
                profile["jellyseerrEnabled"] = bool(enabled)
                settings[profile_name] = profile
            response = session.post(
                settings_url,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "settings": settings,
                    "clientId": "royal-downloader",
                    "mergeMode": "merge",
                },
                timeout=10,
            )
            response.raise_for_status()
        response = session.post(
            config_url, headers={**headers, "Content-Type": "application/json"},
            json=plugin_config, timeout=10,
        )
        response.raise_for_status()
        return {"configured": True, "detail": "Moonfin wurde konfiguriert."}
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {"configured": False, "detail": f"Moonfin-Konfiguration fehlgeschlagen: {exc}"}


def _seerr_client() -> SeerrClient:
    return SeerrClient(
        state.seerr_cfg.get("url", ""),
        state.seerr_cfg.get("api_key", ""),
    )


def _save_seerr_requests_locked() -> bool:
    snapshot = {key: dict(value) for key, value in state.seerr_requests.items()}
    return appconfig.save_seerr_requests(snapshot)


def _seerr_update_record(request_id, **updates) -> dict:
    key = str(request_id)
    with state.seerr_requests_lock:
        record = state.seerr_requests.setdefault(key, {"request_id": int(request_id)})
        record.update(updates)
        record["updated_at"] = time.time()
        _save_seerr_requests_locked()
        return dict(record)


def _seerr_mark_failure(request_id, message: str, status: str = "failed") -> None:
    key = str(request_id)
    with state.seerr_requests_lock:
        record = state.seerr_requests.setdefault(key, {"request_id": int(request_id)})
        attempts = int(record.get("attempts", 0) or 0) + 1
        retry_delay = min(6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)))
        if status == "needs_review":
            retry_delay = max(retry_delay, 24 * 60 * 60)
        record.update({
            "status": status,
            "message": str(message)[:400],
            "attempts": attempts,
            "next_retry": time.time() + retry_delay,
            "pending_slugs": [],
            "updated_at": time.time(),
        })
        _save_seerr_requests_locked()
    log(f"Seerr #{request_id}: {message}", "warn")


def _seerr_job_result(job: dict, slug: str, ok: bool, message: str, out_path: Path) -> None:
    request_id = str(job.get("request_id", ""))
    if not request_id:
        return
    with state.seerr_requests_lock:
        record = state.seerr_requests.get(request_id)
        if not record:
            return
        pending = [value for value in record.get("pending_slugs", []) if value != slug]
        completed = list(record.get("completed_slugs", []))
        failures = list(record.get("failures", []))
        if ok:
            if slug not in completed:
                completed.append(slug)
        else:
            failures.append({"slug": slug, "message": str(message)[:240]})
        record.update({
            "pending_slugs": pending,
            "completed_slugs": completed,
            "failures": failures[-50:],
            "updated_at": time.time(),
        })
        if not pending:
            if failures:
                record["status"] = "partial" if completed else "failed"
                attempts = int(record.get("attempts", 0) or 0) + 1
                record["attempts"] = attempts
                record["next_retry"] = time.time() + min(
                    6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)),
                )
                record["message"] = (
                    f"{len(completed)} erfolgreich, {len(failures)} fehlgeschlagen"
                    if completed else str(message)[:400]
                )
            else:
                record["status"] = "completed"
                record["message"] = "Download abgeschlossen; Seerr wartet auf den Jellyfin-Scan."
                record["next_retry"] = 0
        _save_seerr_requests_locked()
    if not record.get("pending_slugs"):
        log(
            f"Seerr #{request_id}: {record.get('status')} "
            f"({len(record.get('completed_slugs', []))} Download(s))"
        )


def _seerr_terminal_without_job(slug: str, ok: bool, message: str, out_path: Path) -> None:
    with state.queue_claim_lock:
        state.picked.discard(slug)
    _persist_queue_state()
    with state.seerr_jobs_lock:
        jobs = state.seerr_jobs.pop(slug, [])
    for job in jobs:
        _seerr_job_result(job, slug, ok, message, out_path)


def _seerr_register_request_jobs(request_id, items: dict, title: str, **record_values) -> None:
    pending_slugs = list(items)
    _seerr_update_record(
        request_id,
        status="queued",
        title=title,
        pending_slugs=pending_slugs,
        slugs=sorted(set(record_values.pop("slugs", [])) | set(pending_slugs)),
        items=items,
        failures=[],
        message=f"{len(pending_slugs)} Download(s) eingeplant.",
        **record_values,
    )
    with state.seerr_jobs_lock:
        for slug, item in items.items():
            job = {
                "request_id": str(request_id),
                "title": title,
                **item,
            }
            jobs = state.seerr_jobs.setdefault(slug, [])
            jobs[:] = [
                existing for existing in jobs
                if str(existing.get("request_id", "")) != str(request_id)
            ]
            jobs.append(job)


def _seerr_movie_title_key(value: str) -> str:
    """Normalisiert Quelltitel inklusive optional angehängtem Erscheinungsjahr."""
    title = clean_movie_title(str(value or "").strip())
    title = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", title).strip()
    return _norm_title(title)


def _seerr_movie_aliases(title: str, original_title: str) -> List[tuple[str, str]]:
    """Liefert nur Aliase, die von den überwiegend lateinischen Katalogen suchbar sind."""
    aliases: List[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_value in (title, original_title):
        value = " ".join(str(raw_value or "").split()).strip()
        key = _seerr_movie_title_key(value)
        # CJK-/sonstige Originaltitel wurden bisher zu einem leeren Schlüssel
        # und ließen dadurch beliebige Treffer wie exakte Matches aussehen.
        if not value or not key or key in seen:
            continue
        seen.add(key)
        aliases.append((value, key))
    return aliases


def _seerr_http_status(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    for value in (getattr(response, "status_code", None), getattr(exc, "code", None)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return 0


def _seerr_explicitly_non_german(movie: FilmpalastMovie) -> bool:
    """True, wenn jeder Hoster explizit oder über seinen Anbieter nichtdeutsch ist."""
    hosters = list(movie.hosters or [])
    return bool(hosters) and all(
        (
            language := _movie_content_language(
                movie,
                str(getattr(hoster, "language", "") or ""),
            )
        )
        and language != "de"
        for hoster in hosters
    )


def _seerr_find_movie_sources(metadata: dict, tmdb_id: int) -> List[tuple]:
    """Findet wenige, exakt passende und TMDB-bestätigte deutsche Filmquellen."""
    title = str(metadata.get("title") or "").strip()
    original_title = str(metadata.get("original_title") or "").strip()
    year = str(metadata.get("year") or "").strip()
    aliases = _seerr_movie_aliases(title, original_title)
    if not aliases:
        raise RuntimeError(f"Kein durchsuchbarer Titel für „{title or tmdb_id}“ vorhanden")

    movie_options: List[tuple] = []
    attempted_slugs: set[str] = set()
    seen_urls: set[str] = set()
    rate_limited = False
    non_german_found = False
    tmdb_client = get_tmdb_client()
    max_detail_requests = 8

    for query, query_key in aliases:
        candidates = []
        for candidate in search_movie_candidates(query):
            if not candidate.is_movie or candidate.slug in attempted_slugs:
                continue
            if _seerr_movie_title_key(candidate.title) != query_key:
                continue
            candidate_year = str(candidate.year or "").strip()
            if year and candidate_year and candidate_year != year:
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda candidate: (
            bool(year) and str(candidate.year or "").strip() != year,
            not bool(str(candidate.year or "").strip()),
            clean_movie_title(candidate.title).casefold(),
        ))

        for candidate in candidates:
            if len(attempted_slugs) >= max_detail_requests:
                break
            # Vor dem Netzaufruf markieren, damit derselbe Slug über einen
            # zweiten Alias nicht erneut geladen wird.
            attempted_slugs.add(candidate.slug)
            try:
                loaded = load_movie_for_slug(candidate.slug)
            except Exception as exc:
                status = _seerr_http_status(exc)
                rate_limited = rate_limited or status == 429
                suffix = f" (HTTP {status})" if status else f": {exc}"
                log(f"Seerr-Filmquelle übersprungen: {candidate.slug}{suffix}", "warn")
                continue
            if not loaded or not loaded.hosters:
                continue

            loaded_title = clean_movie_title(loaded.title)
            loaded_key = _seerr_movie_title_key(loaded_title)
            if loaded_key not in {key for _value, key in aliases}:
                continue
            loaded_year = str(loaded.year or candidate.year or "").strip()
            if year and loaded_year and loaded_year != year:
                continue
            try:
                summary = tmdb_client.movie_summary(loaded_title, loaded_year or year)
            except Exception as exc:
                status = _seerr_http_status(exc)
                rate_limited = rate_limited or status == 429
                log(f"TMDB-Prüfung für „{loaded_title}“ übersprungen: {exc}", "warn")
                continue
            if not summary or int(summary.get("tmdb_id") or 0) != int(tmdb_id):
                continue
            if _seerr_explicitly_non_german(loaded):
                non_german_found = True
                log(f"Seerr-Filmquelle ohne deutsche Tonspur übersprungen: {loaded_title}", "warn")
                continue
            if loaded.url in seen_urls:
                continue
            seen_urls.add(loaded.url)
            movie_options.append((candidate, loaded))

        # Der lokalisierte Titel hatte bestätigte Quellen. Den Originaltitel
        # nicht zusätzlich über alle vier Anbieter schicken.
        if movie_options:
            break
        if len(attempted_slugs) >= max_detail_requests:
            break

    if movie_options:
        movie_options.sort(key=lambda value: not any(
            bool(getattr(hoster, "is_de", False))
            for hoster in (value[1].hosters or [])
        ))
        return movie_options
    if rate_limited:
        raise RuntimeError("Filmquellen vorübergehend begrenzt (HTTP 429); neuer Versuch folgt")
    if non_german_found:
        raise RuntimeError(f"„{title}“ gefunden, aber derzeit ohne deutsche Tonspur")
    raise RuntimeError(f"Keine eindeutige Downloadquelle für „{title}“ gefunden")


def _seerr_process_movie(request: SeerrRequest, metadata: dict) -> None:
    request_id = request.request_id
    jf_client = get_jellyfin_client()
    jf_items = get_jellyfin_library(force=True)
    with state.jellyfin_cache_lock:
        library_available = state.jellyfin_library_available
    if not jf_client.configured or jf_items is None or not library_available:
        raise RuntimeError("Jellyfin ist für den sicheren Duplikat-Check nicht erreichbar")

    title = str(metadata.get("title") or "").strip()
    year = str(metadata.get("year") or "")
    if jf_client.match(title, year, items=jf_items, tmdb_id=request.tmdb_id):
        _seerr_update_record(
            request_id, status="available", title=title,
            message="Bereits in Jellyfin vorhanden.", next_retry=0,
        )
        return

    movie_options = _seerr_find_movie_sources(metadata, request.tmdb_id)

    chosen, movie = movie_options[0]
    fallbacks = [value for _candidate, value in movie_options[1:]]
    already_available, reason = _content_already_available(movie, chosen.slug)
    if already_available:
        if _is_jellyfin_safety_block(reason):
            raise RuntimeError(reason)
        _seerr_update_record(
            request_id, status="completed", title=title,
            message=f"Bereits {reason}.", next_retry=0,
        )
        return

    with state.queue_lifecycle_lock:
        active = any(chosen.slug in _job_queue_slugs(job) for job in state.dl_queue.active_jobs())
        with state.queue_claim_lock:
            with state.download_state_lock:
                already_queued = (
                    chosen.slug in state.picked
                    or chosen.slug in state.counted_queue_slugs
                    or active
                )
            if not already_queued:
                state.picked.add(chosen.slug)
    state.fp_movies[chosen.slug] = movie
    item = {
        "kind": "movie", "year": year,
        "tmdb_id": request.tmdb_id,
    }
    _seerr_register_request_jobs(
        request_id, {chosen.slug: item}, title,
        media_type="movie", tmdb_id=request.tmdb_id,
        seasons=[], is_4k=request.is_4k,
    )
    if not already_queued and not _persist_new_queue_claims({chosen.slug}):
        _seerr_terminal_without_job(
            chosen.slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
        )
        return
    if already_queued:
        log(f"Seerr #{request_id}: „{title}“ an laufenden Download angehängt.")
        return
    accepted = _enqueue_automatic_downloads(
        [chosen.slug], movie_fallbacks={chosen.slug: fallbacks}, taste_source="seerr",
    )
    if chosen.slug not in accepted:
        _seerr_terminal_without_job(
            chosen.slug, False, "Downloadstart fehlgeschlagen", Path(""),
        )


def _seerr_find_series(metadata: dict) -> Optional[FilmpalastSeries]:
    titles = list(dict.fromkeys(filter(None, (
        str(metadata.get("title") or "").strip(),
        str(metadata.get("original_title") or "").strip(),
    ))))
    wanted = {_norm_title(value) for value in titles if _norm_title(value)}
    matches: Dict[str, FilmpalastSeriesResult] = {}
    for query in titles:
        for candidate in search_series_candidates(query):
            if _norm_title(candidate.title) in wanted:
                matches.setdefault(candidate.sample_slug, candidate)
    if not matches:
        return None
    candidates = list(matches.values())
    year = str(metadata.get("year") or "")
    if year:
        same_year = [candidate for candidate in candidates if str(candidate.year or "") == year]
        if same_year:
            candidates = same_year
        else:
            unknown_year = [candidate for candidate in candidates if not candidate.year]
            if unknown_year:
                candidates = unknown_year
            else:
                raise RuntimeError(
                    "Serientreffer hat ein abweichendes Erscheinungsjahr und muss geprüft werden"
                )
    wanted_tmdb_id = str(metadata.get("tmdb_id") or "").strip()
    tmdb = get_tmdb_client()
    verified = [
        candidate for candidate in candidates
        if tmdb.series_matches_id(
            strip_source_suffix(candidate.title), wanted_tmdb_id, year,
        )
    ]
    if not verified:
        raise RuntimeError(
            "Serientreffer ist ohne bestätigte TMDB-ID mehrdeutig und muss geprüft werden"
        )
    # Mehrere bestätigte Treffer derselben TMDB-Serie sind Anbieter-Fallbacks;
    # search_series_candidates liefert sie bereits in Nutzerpriorität.
    return get_series_for_value(verified[0].sample_slug)


def _seerr_process_series(request: SeerrRequest, metadata: dict) -> None:
    request_id = request.request_id
    jf_client = get_jellyfin_client()
    if not jf_client.configured:
        raise RuntimeError("Jellyfin ist nicht konfiguriert")
    series = _seerr_find_series(metadata)
    if series is None or not series.all_episodes:
        raise RuntimeError(
            f"Keine eindeutige Downloadquelle für „{metadata.get('title') or request.tmdb_id}“ gefunden"
        )

    requested_seasons = set(request.seasons)
    unreleased_slugs = _unreleased_episode_slugs(series, request.tmdb_id)
    selected = [
        episode for episode in series.all_episodes
        if (not requested_seasons or episode.season in requested_seasons)
        and episode.slug not in unreleased_slugs
    ]
    if not selected:
        raise RuntimeError("Die angeforderten Staffeln sind beim Anbieter nicht vorhanden")

    downloaded = compute_downloaded_episodes(series)
    jf_episodes = get_jellyfin_episodes(force=True)
    jf_series = get_jellyfin_series(force=True)
    with state.jellyfin_cache_lock:
        jf_available = state.jellyfin_episodes_available and state.jellyfin_series_available
    if jf_episodes is None or jf_series is None or not jf_available:
        raise RuntimeError("Jellyfin ist für den sicheren Duplikat-Check nicht erreichbar")
    aliases = tuple(dict.fromkeys(filter(None, (
        series.title,
        metadata.get("title", ""),
        metadata.get("original_title", ""),
    ))))
    series_ids = jf_client.series_ids_for(
        series.title, tmdb_id=request.tmdb_id, aliases=aliases, items=jf_series,
    )
    if series_ids is None:
        raise RuntimeError("Jellyfin-Zuordnung der Serie ist mehrdeutig")
    missing = [
        episode for episode in selected
        if episode.slug not in downloaded
        and not jf_client.has_episode(
            series.title, episode.season, episode.episode,
            items=jf_episodes, aliases=aliases, series_ids=series_ids,
        )
    ]
    if not missing:
        pending_unreleased = sum(
            1 for episode in series.all_episodes
            if (not requested_seasons or episode.season in requested_seasons)
            and episode.slug in unreleased_slugs
        )
        if pending_unreleased:
            _seerr_update_record(
                request_id, status="queued", title=series.title,
                message=(
                    f"{pending_unreleased} Episode(n) noch nicht erschienen – "
                    "wird automatisch nachgeladen, sobald verfügbar."
                ),
                next_retry=0,
            )
        else:
            _seerr_update_record(
                request_id, status="available", title=series.title,
                message="Alle angeforderten Episoden sind bereits vorhanden.", next_retry=0,
            )
        return

    movies: Dict[str, FilmpalastMovie] = {}
    episode_items: Dict[str, dict] = {}
    for episode in missing:
        try:
            movie = load_movie_for_slug(episode.slug)
        except Exception as exc:
            movie = None
            log(f"Seerr-Serie: {episode.label} nicht direkt ladbar: {exc}", "warn")
        if not movie or not movie.hosters:
            movie = _episode_placeholder(episode.slug, series.title)
        movies[episode.slug] = movie
        episode_items[episode.slug] = {
            "kind": "series", "season": episode.season,
            "episode": episode.episode, "tmdb_id": request.tmdb_id,
        }

    candidate_slugs = set(movies)
    with state.queue_lifecycle_lock:
        active_slugs = {
            slug for job in state.dl_queue.active_jobs() for slug in _job_queue_slugs(job)
        }
        with state.queue_claim_lock:
            with state.download_state_lock:
                existing = candidate_slugs & (
                    set(state.picked) | set(state.counted_queue_slugs) | active_slugs
                )
                new_slugs = candidate_slugs - existing
            state.picked.update(new_slugs)
    tracked_slugs = existing | new_slugs
    for slug in tracked_slugs:
        state.fp_movies[slug] = movies[slug]
    items = {slug: episode_items[slug] for slug in tracked_slugs}
    _seerr_register_request_jobs(
        request_id, items, series.title,
        media_type="tv", tmdb_id=request.tmdb_id,
        seasons=list(request.seasons), is_4k=request.is_4k,
    )
    if new_slugs and not _persist_new_queue_claims(new_slugs):
        for slug in new_slugs:
            _seerr_terminal_without_job(
                slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
            )
        return
    if new_slugs:
        accepted = _enqueue_automatic_downloads(sorted(new_slugs), taste_source="seerr")
        for slug in new_slugs - set(accepted):
            _seerr_terminal_without_job(
                slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
    if existing:
        log(f"Seerr #{request_id}: {len(existing)} Episode(n) an laufende Downloads angehängt.")


def _seerr_retry_completed_scan(request: SeerrRequest, previous: dict) -> None:
    """Stößt den Jellyfin-Scan erneut an, bis Seerr das Medium als verfügbar meldet."""
    now = time.time()
    last_retry = float(previous.get("last_scan_retry", 0) or 0)
    if now - last_retry < SEERR_SCAN_RETRY_SECONDS:
        return
    with state.seerr_scan_retry_lock:
        if now - state.seerr_last_scan_retry < SEERR_SCAN_RETRY_SECONDS:
            return
        state.seerr_last_scan_retry = now
    jellyfin = get_jellyfin_client()
    started = bool(jellyfin.configured and jellyfin.refresh_library())
    message = (
        "Download abgeschlossen; Jellyfin-Scan erneut gestartet."
        if started
        else "Download abgeschlossen; Jellyfin-Scan konnte nicht gestartet werden."
    )
    _seerr_update_record(
        request.request_id,
        status="completed",
        last_scan_retry=now,
        message=message,
    )
    if not started:
        log(f"Seerr #{request.request_id}: {message}", "warn")


def _seerr_record_matches_request(record: dict, request: SeerrRequest) -> bool:
    required = {"media_type", "tmdb_id", "seasons", "is_4k"}
    if not required.issubset(record):
        return False
    try:
        stored_seasons = tuple(sorted(int(value) for value in record.get("seasons", [])))
    except (TypeError, ValueError, OverflowError):
        return False
    stored_4k = record.get("is_4k")
    if isinstance(stored_4k, str):
        stored_4k = stored_4k.strip().casefold() in {"1", "true", "yes", "on"}
    return (
        str(record.get("media_type") or "").casefold() == request.media_type
        and str(record.get("tmdb_id") or "") == str(request.tmdb_id)
        and stored_seasons == tuple(request.seasons)
        and bool(stored_4k) == request.is_4k
    )


def _seerr_reset_reused_request(request_id: str) -> None:
    """Entkoppelt lokalen Altzustand, wenn Seerr eine Request-ID neu verwendet."""
    with state.seerr_jobs_lock:
        for slug, jobs in list(state.seerr_jobs.items()):
            remaining = [
                job for job in jobs
                if str(job.get("request_id", "")) != request_id
            ]
            if remaining:
                state.seerr_jobs[slug] = remaining
            else:
                state.seerr_jobs.pop(slug, None)
    with state.seerr_requests_lock:
        state.seerr_requests.pop(request_id, None)
        _save_seerr_requests_locked()
    log(f"Seerr #{request_id}: geänderte Anfrage erkannt; Altzustand verworfen.")


def _seerr_process_request(request: SeerrRequest) -> None:
    request_id = str(request.request_id)
    with state.seerr_requests_lock:
        previous = dict(state.seerr_requests.get(request_id, {}))
    if previous and not _seerr_record_matches_request(previous, request):
        _seerr_reset_reused_request(request_id)
        previous = {}
    status = previous.get("status", "")
    if request.media_status == SEERR_MEDIA_AVAILABLE:
        if status != "available":
            _seerr_update_record(
                request.request_id, status="available", media_type=request.media_type,
                tmdb_id=request.tmdb_id, seasons=list(request.seasons),
                is_4k=request.is_4k, message="In Jellyfin verfügbar.", next_retry=0,
            )
        return
    if request.is_4k:
        if previous.get("seerr_declined"):
            return
        now = time.time()
        if status == "unsupported" and now < float(previous.get("next_retry", 0) or 0):
            return
        try:
            client = _seerr_client()
            declined = client.decline_request(request.request_id)
            decline_error = getattr(client, "last_error", "")
        except Exception as exc:
            declined = False
            decline_error = str(exc)
        message = (
            "4K-Anfrage in Seerr abgelehnt: Die Downloadquelle garantiert keine 4K-Qualität."
            if declined
            else (
                "4K wird nicht geladen; Seerr-Ablehnung wird erneut versucht"
                + (f": {decline_error}" if decline_error else ".")
            )
        )
        _seerr_update_record(
            request.request_id,
            status="unsupported",
            media_type=request.media_type,
            tmdb_id=request.tmdb_id,
            seasons=list(request.seasons),
            is_4k=True,
            seerr_declined=declined,
            message=message,
            next_retry=0 if declined else now + SEERR_SCAN_RETRY_SECONDS,
        )
        if not declined:
            log(f"Seerr #{request.request_id}: {message}", "warn")
        return
    if status == "completed":
        _seerr_retry_completed_scan(request, previous)
        return
    if status in ("available", "unsupported"):
        return
    if status == "queued":
        pending = set(previous.get("pending_slugs", []))
        with state.queue_claim_lock:
            active = pending & set(state.picked)
        if active:
            return
    if status in ("failed", "partial", "needs_review"):
        if time.time() < float(previous.get("next_retry", 0) or 0):
            return

    _seerr_update_record(
        request.request_id,
        status="resolving",
        media_type=request.media_type,
        tmdb_id=request.tmdb_id,
        seasons=list(request.seasons),
        is_4k=request.is_4k,
        message="Quelle und Jellyfin-Bestand werden geprüft.",
        pending_slugs=[],
    )
    try:
        tmdb = get_tmdb_client()
        if not tmdb.configured:
            raise RuntimeError("TMDB ist nicht konfiguriert")
        if request.media_type == "movie":
            metadata = tmdb.movie_by_id(request.tmdb_id)
            if not metadata:
                raise RuntimeError(f"TMDB-Film {request.tmdb_id} wurde nicht gefunden")
            _seerr_process_movie(request, metadata)
        else:
            metadata = tmdb.series_by_id(request.tmdb_id)
            if not metadata:
                raise RuntimeError(f"TMDB-Serie {request.tmdb_id} wurde nicht gefunden")
            _seerr_process_series(request, metadata)
    except Exception as exc:
        detail = str(exc).casefold()
        kind = (
            "needs_review"
            if "mehrdeutig" in detail or "abweichendes erscheinungsjahr" in detail
            else "failed"
        )
        _seerr_mark_failure(request.request_id, str(exc), kind)


def _hydrate_seerr_jobs() -> None:
    """Verknüpft persistierte Seerr-Wünsche wieder mit der Queue."""
    stale = []
    with state.seerr_requests_lock:
        records = [(key, dict(value)) for key, value in state.seerr_requests.items()]
    with state.queue_claim_lock:
        picked = set(state.picked)
    with state.seerr_jobs_lock:
        for request_id, record in records:
            if record.get("status") != "queued":
                continue
            pending = set(record.get("pending_slugs", []))
            active = pending & picked
            item_map = record.get("items") if isinstance(record.get("items"), dict) else {}
            for slug in active:
                item = item_map.get(slug) if isinstance(item_map.get(slug), dict) else {}
                job = {
                    "request_id": request_id,
                    "title": record.get("title", ""),
                    **item,
                }
                jobs = state.seerr_jobs.setdefault(slug, [])
                if not any(
                    str(existing.get("request_id", "")) == str(request_id)
                    for existing in jobs
                ):
                    jobs.append(job)
            if pending and not active:
                stale.append(request_id)
    for request_id in stale:
        _seerr_mark_failure(request_id, "Offene Queue-Zuordnung nach Neustart verloren")


def seerr_poll_once() -> dict:
    if not state.seerr_poll_lock.acquire(blocking=False):
        return {"ok": False, "detail": "Seerr-Abgleich läuft bereits."}
    try:
        state.seerr_last_poll = time.time()
        cfg = dict(state.seerr_cfg)
        client = _seerr_client()
        if not cfg.get("enabled"):
            return {"ok": False, "detail": "Seerr-Integration ist deaktiviert."}
        if not client.configured:
            state.seerr_last_error = "Seerr-URL oder API-Schlüssel fehlt."
            return {"ok": False, "detail": state.seerr_last_error}
        if not client.test_connection():
            state.seerr_last_error = (
                getattr(client, "last_error", "")
                or "Seerr ist nicht erreichbar oder der API-Schlüssel ist ungültig."
            )
            return {"ok": False, "detail": state.seerr_last_error}
        requests = client.approved_requests()
        if getattr(client, "last_error", ""):
            state.seerr_last_error = client.last_error
            return {"ok": False, "detail": state.seerr_last_error}
        state.seerr_last_success = time.time()
        state.seerr_last_error = ""
        for request in requests:
            _seerr_process_request(request)
        if requests:
            log(f"Seerr-Abgleich: {len(requests)} genehmigte Anfrage(n) geprüft.")
        return {"ok": True, "requests": len(requests)}
    except Exception as exc:
        state.seerr_last_error = str(exc)[:300]
        log(f"Seerr-Abgleich fehlgeschlagen: {exc}", "warn")
        return {"ok": False, "detail": state.seerr_last_error}
    finally:
        state.seerr_poll_lock.release()


def seerr_poll_loop() -> None:
    _hydrate_seerr_jobs()
    while not _seerr_stop_event.is_set():
        if state.seerr_cfg.get("enabled"):
            seerr_poll_once()
        interval = max(15, int(state.seerr_cfg.get("poll_interval_seconds", 60) or 60))
        _seerr_wake_event.wait(interval)
        _seerr_wake_event.clear()


_SERVICE_EXPORTS = (
    "SEERR_MEDIA_AVAILABLE",
    "SEERR_SCAN_RETRY_SECONDS",
    "configure_moonfin_seerr",
    "_seerr_client",
    "_save_seerr_requests_locked",
    "_seerr_update_record",
    "_seerr_mark_failure",
    "_seerr_job_result",
    "_seerr_terminal_without_job",
    "_seerr_register_request_jobs",
    "_seerr_movie_title_key",
    "_seerr_movie_aliases",
    "_seerr_http_status",
    "_seerr_explicitly_non_german",
    "_seerr_find_movie_sources",
    "_seerr_process_movie",
    "_seerr_find_series",
    "_seerr_process_series",
    "_seerr_retry_completed_scan",
    "_seerr_record_matches_request",
    "_seerr_reset_reused_request",
    "_seerr_process_request",
    "_hydrate_seerr_jobs",
    "seerr_poll_once",
    "seerr_poll_loop",
)
publish_service(globals(), _SERVICE_EXPORTS)
