"""Telegram command parsing, execution, and callback services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


def _parse_telegram_series_request(text: str) -> Optional[dict]:
    if re.match(r"^/film(?:\s|$)", text.strip(), flags=re.IGNORECASE):
        return None
    value = re.sub(r"^/serie\s+", "", text.strip(), flags=re.IGNORECASE)
    match = re.match(
        r"^(?P<title>.+?)\s+(?:(?P<all>alles)|staffel\s*0*(?P<season>\d+)"
        r"(?:\s*(?:ep|e|episode|folge)\s*0*(?P<episode>\d+))?)\s*$",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    title = match.group("title").strip().strip('"„“')
    if not title:
        return None
    if match.group("all"):
        return {"title": title, "mode": "all", "season": None, "episode": None}
    season = int(match.group("season"))
    episode = int(match.group("episode")) if match.group("episode") else None
    return {
        "title": title,
        "mode": "episode" if episode is not None else "season",
        "season": season,
        "episode": episode,
    }


def _telegram_series_scope_label(request: dict) -> str:
    if request["mode"] == "all":
        return "alle fehlenden Episoden"
    if request["mode"] == "season":
        return f"Staffel {request['season']}"
    return f"Staffel {request['season']} Episode {request['episode']}"


def _telegram_best_result(query: str, results: List[FilmpalastSearchResult]) -> List[FilmpalastSearchResult]:
    wanted = _norm_title(query)
    return sorted(
        results,
        key=lambda result: (
            _norm_title(result.title) != wanted,
            wanted not in _norm_title(result.title),
            strip_source_suffix(result.title).casefold(),
        ),
    )


def _format_storage_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024 or unit == "PiB":
            return f"{size:.0f} {unit}" if unit in ("B", "KiB", "MiB") else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"


def _telegram_storage_text() -> str:
    lines = ["💾 NAS-Speicher"]
    seen_volumes = {}
    for label, raw_path in (("Filme", state.save_path), ("Serien", state.series_path)):
        path = Path(raw_path)
        try:
            usage = shutil.disk_usage(path)
            device = os.stat(path).st_dev
            if device in seen_volumes:
                lines.append(f"{label}: gemeinsames Volume mit {seen_volumes[device]} ({path})")
                continue
            seen_volumes[device] = label
            percent = (usage.used / usage.total * 100) if usage.total else 0
            lines.append(
                f"{label} ({path})\n"
                f"  {_format_storage_size(usage.free)} frei von {_format_storage_size(usage.total)} · {percent:.1f}% belegt"
            )
        except OSError as exc:
            lines.append(f"{label} ({path}): nicht erreichbar ({exc})")
    return "\n".join(lines)


def _telegram_paths_text() -> str:
    lines = ["📁 Speicherpfade"]
    for label, raw_path in (("Filme", state.save_path), ("Serien", state.series_path)):
        path = Path(raw_path)
        status = "erreichbar" if path.is_dir() else "nicht erreichbar"
        lines.append(f"{label}: {path} · {status}")
    return "\n".join(lines)


def _telegram_watchlist_text() -> str:
    if not state.watchlist:
        return "📺 Keine Serien abonniert."
    lines = [f"📺 Abonnierte Serien: {len(state.watchlist)}"]
    for entry in state.watchlist[:25]:
        new_count = len(state.watchlist_new_slugs.get(entry["base_slug"], set()))
        suffix = f" · {new_count} neu" if new_count else ""
        lines.append(f"• {entry['title']}{suffix}")
    if len(state.watchlist) > 25:
        lines.append(f"… und {len(state.watchlist) - 25} weitere")
    return "\n".join(lines)


def _telegram_help_text() -> str:
    return (
        "Royal Downloader\n"
        "Filmtitel – Film prüfen und herunterladen\n"
        "/film Filmtitel – Film ausdrücklich auswählen\n"
        "Serientitel ALLES\n"
        "Serientitel Staffel 2\n"
        "Serientitel Staffel 2 EP 5\n"
        "Mehrere Film- und Serientreffer werden mit Cover zur Auswahl angezeigt.\n"
        "/status – laufende Downloads\n"
        "/speicher – freier NAS-Speicher\n"
        "/pfade – Film- und Serienpfad\n"
        "/abos – abonnierte Serien\n"
        "/jellyfin – Bibliotheksstatus\n"
        "/hilfe – diese Übersicht"
    )


def _run_telegram_series_request(
    chat_id: str,
    request: dict,
    series_value: str,
    wait_for_lock: bool = False,
):
    if not state.telegram_request_lock.acquire(blocking=wait_for_lock):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return

        scope_label = _telegram_series_scope_label(request)
        _telegram_send(chat_id, f"🔎 Lade Serie „{request['title']}“ · {scope_label} …")
        series = get_series_for_value(series_value)
        if series is None or not series.all_episodes:
            _telegram_send(chat_id, f"❌ Serie „{request['title']}“ nicht gefunden.")
            return

        selected = list(series.all_episodes)
        if request["mode"] in ("season", "episode"):
            selected = [ep for ep in selected if ep.season == request["season"]]
        if request["mode"] == "episode":
            selected = [ep for ep in selected if ep.episode == request["episode"]]
        if not selected:
            _telegram_send(chat_id, f"❌ „{series.title}“ enthält {scope_label} nicht.")
            return

        downloaded = compute_downloaded_episodes(series)
        jf_episodes = get_jellyfin_episodes(force=True)
        jf_series = get_jellyfin_series(force=True)
        with state.jellyfin_cache_lock:
            jf_available = (
                state.jellyfin_episodes_available and state.jellyfin_series_available
            )
        if jf_episodes is None or jf_series is None or not jf_available:
            _telegram_send(chat_id, "Jellyfin ist nicht erreichbar. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        try:
            aliases, series_ids, tmdb_id = _episode_jellyfin_identity(
                series.base_slug, series.title, jf_client, jf_series,
            )
        except RuntimeError as exc:
            _telegram_send(chat_id, f"{exc}. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        missing = [
            ep for ep in selected
            if ep.slug not in downloaded
            and not jf_client.has_episode(
                series.title, ep.season, ep.episode, items=jf_episodes,
                aliases=aliases, series_ids=series_ids,
            )
        ]
        if not missing:
            _telegram_send(chat_id, f"✅ „{series.title}“ · {scope_label} ist bereits vollständig vorhanden.")
            return

        _telegram_send(chat_id, f"⬇️ {len(missing)} fehlende Episode(n) werden vorbereitet …")
        jobs: List[tuple] = []
        initial_failures: List[str] = []
        episode_by_slug = {ep.slug: ep for ep in missing}
        for ep in missing:
            try:
                movie = load_movie_for_slug(ep.slug)
            except Exception as exc:
                movie = None
                log(f"Telegram-Serie: {ep.label} nicht ladbar: {exc}", "warn")
            if not movie or not movie.hosters:
                movie = _episode_placeholder(ep.slug, series.title)
                log(
                    f"Telegram-Serie: {ep.label} wird trotz blockierter "
                    "Episodenseite fuer Fallback/Retry eingeplant.",
                    "warn",
                )
            already_available, reason = _content_already_available(movie, ep.slug)
            if already_available:
                initial_failures.append(f"{ep.label}: {reason}")
                continue
            state.fp_movies[ep.slug] = movie
            jobs.append((movie, ep.slug))

        if not jobs:
            _telegram_send(
                chat_id,
                f"❌ Für „{series.title}“ konnte keine der {len(missing)} fehlenden Episoden gestartet werden.",
            )
            return

        request_id = f"{chat_id}:{time.time_ns()}"
        candidate_slugs = {slug for _movie, slug in jobs}
        with state.queue_lifecycle_lock:
            active_slugs = {
                slug for job in state.dl_queue.active_jobs() for slug in _job_queue_slugs(job)
            }
            with state.queue_claim_lock:
                with state.download_state_lock:
                    pending_slugs = {
                        slug for slug in candidate_slugs
                        if slug not in state.picked
                        and slug not in state.counted_queue_slugs
                        and slug not in active_slugs
                    }
                state.picked.update(pending_slugs)
        jobs = [(movie, slug) for movie, slug in jobs if slug in pending_slugs]
        if not jobs:
            _telegram_send(chat_id, "Alle fehlenden Episoden sind bereits eingeplant.")
            return
        group = {
            "chat_id": chat_id,
            "title": series.title,
            "scope_label": scope_label,
            "pending_slugs": set(pending_slugs),
            "completed": [],
            "failed": list(initial_failures),
            "aliases": list(aliases),
            "tmdb_id": tmdb_id,
        }
        with state.telegram_jobs_lock:
            state.telegram_series_requests[request_id] = group
            for _movie, slug in jobs:
                ep = episode_by_slug[slug]
                state.telegram_jobs[slug] = {
                    "kind": "series",
                    "request_id": request_id,
                    "chat_id": chat_id,
                    "title": series.title,
                    "season": ep.season,
                    "episode": ep.episode,
                }

        if not _persist_new_queue_claims(pending_slugs):
            for slug in pending_slugs:
                _telegram_terminal_without_job(
                    slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
                )
            return
        _telegram_send(chat_id, f"▶️ „{series.title}“ · {scope_label}: {len(jobs)} Download(s) starten.")

        try:
            accepted = _enqueue_automatic_downloads(list(pending_slugs), taste_source="telegram")
        except Exception:
            for slug in pending_slugs:
                _telegram_terminal_without_job(slug, False, "Downloadstart fehlgeschlagen", Path(""))
            raise
        for slug in pending_slugs - set(accepted):
            _telegram_terminal_without_job(slug, False, "kein Stream startbar", Path(""))
    except Exception as exc:
        log(f"Telegram-Serienwunsch fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Serienwunsch fehlgeschlagen: {exc}")
    finally:
        state.telegram_request_lock.release()


def _handle_telegram_series_request(chat_id: str, request: dict):
    title = str(request.get("title") or "").strip()
    if (
        title.startswith((
            SERIENSTREAM_PREFIX, HUHU_PREFIX, MOFLIX_PREFIX, EINSCHALTEN_PREFIX,
            KINOX_PREFIX, KINOGER_PREFIX, MEGAKINO_PREFIX, XCINE_PREFIX,
        ))
        or title.startswith("http://")
        or title.startswith("https://")
    ):
        _run_telegram_series_request(chat_id, request, title)
        return

    if not state.telegram_request_lock.acquire(blocking=False):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        if not get_jellyfin_client().configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return
        scope_label = _telegram_series_scope_label(request)
        _telegram_send(chat_id, f"🔎 Suche Serie „{title}“ · {scope_label} …")
        results = _rank_telegram_series_results(title, search_series_candidates(title))
        if not results:
            _telegram_send(chat_id, f"❌ Serie „{title}“ nicht gefunden.")
            return
        if len(results) > 1:
            _publish_telegram_series_choices(chat_id, request, results)
            return
        selected_value = results[0].sample_slug
    except Exception as exc:
        log(f"Telegram-Seriensuche fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Seriensuche fehlgeschlagen: {exc}")
        return
    finally:
        state.telegram_request_lock.release()

    _run_telegram_series_request(chat_id, request, selected_value)


def _run_telegram_movie_request(
    chat_id: str,
    query: str,
    option: dict,
    wait_for_lock: bool = False,
):
    if not state.telegram_request_lock.acquire(blocking=wait_for_lock):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return

        movie = option["movie"]
        chosen_result = option["result"]
        fallback_movies = list(option.get("fallback_movies", []))
        title = str(option.get("title") or clean_movie_title(movie.title)).strip()
        year = str(option.get("year") or movie.year or chosen_result.year or "")
        _telegram_send(chat_id, f"🔎 Prüfe „{title}“{f' ({year})' if year else ''} …")

        jf_items = get_jellyfin_library(force=True)
        if jf_items is None or not state.jellyfin_library_available:
            _telegram_send(chat_id, "Jellyfin ist nicht erreichbar. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        tmdb = get_tmdb_client().movie_summary(title, year)
        if jf_client.match(
            title, year, items=jf_items, tmdb_id=(tmdb or {}).get("tmdb_id", ""),
        ):
            _telegram_send(chat_id, f"✅ „{title}“ ist bereits in Jellyfin vorhanden.")
            return
        already_available, reason = _content_already_available(movie, chosen_result.slug)
        if already_available:
            _telegram_send(chat_id, f"Download nicht gestartet: „{title}“ ist {reason}.")
            return

        with state.queue_lifecycle_lock:
            physically_active = any(
                chosen_result.slug in _job_queue_slugs(job)
                for job in state.dl_queue.active_jobs()
            )
            with state.queue_claim_lock:
                with state.download_state_lock:
                    already_queued = (
                        chosen_result.slug in state.picked
                        or chosen_result.slug in state.counted_queue_slugs
                        or physically_active
                    )
                if not already_queued:
                    state.picked.add(chosen_result.slug)
        if already_queued:
            _telegram_send(chat_id, f"„{title}“ ist bereits eingeplant.")
            return

        state.fp_movies[chosen_result.slug] = movie
        if not _persist_new_queue_claims({chosen_result.slug}):
            _telegram_send(
                chat_id,
                "❌ Download nicht gestartet: Queue-Zustand konnte nicht gespeichert werden.",
            )
            return
        with state.telegram_jobs_lock:
            state.telegram_jobs[chosen_result.slug] = {
                "chat_id": chat_id,
                "query": query,
                "title": title,
                "year": year,
                "tmdb_id": (tmdb or {}).get("tmdb_id", ""),
            }

        source_count = 1 + len(fallback_movies)
        source_note = f" · {source_count} Filmquellen" if source_count > 1 else ""
        _telegram_send(
            chat_id,
            f"⬇️ Gefunden: „{title}“{f' ({year})' if year else ''}{source_note}. Download startet.",
        )
        try:
            accepted = _enqueue_automatic_downloads(
                [chosen_result.slug],
                movie_fallbacks={chosen_result.slug: fallback_movies},
                taste_source="telegram",
            )
        except Exception:
            _telegram_terminal_without_job(
                chosen_result.slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
            raise
        if chosen_result.slug not in accepted:
            _telegram_terminal_without_job(
                chosen_result.slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
    except Exception as exc:
        log(f"Telegram-Filmwunsch fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Filmwunsch fehlgeschlagen: {exc}")
    finally:
        state.telegram_request_lock.release()


def _handle_telegram_movie_request(chat_id: str, query: str):
    if not state.telegram_request_lock.acquire(blocking=False):
        _telegram_send(chat_id, "Ein anderer Telegram-Filmwunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    selected = None
    try:
        if not get_jellyfin_client().configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return
        _telegram_send(chat_id, f"🔎 Suche Film „{query}“ …")
        results = search_movie_candidates(query)
        if not results:
            _telegram_send(chat_id, f"❌ Kein Film zu „{query}“ gefunden.")
            return
        options = _build_telegram_movie_options(query, results)
        if not options:
            _telegram_send(
                chat_id,
                f"❌ „{query}“ wurde gefunden, aber kein funktionierender Hoster ist verfügbar.",
            )
            return
        requires_selection = len(options) > 1
        options, existing_options, check_error = _filter_existing_telegram_movie_options(options)
        if options is None:
            _telegram_send(
                chat_id,
                f"{check_error}. Download wurde zum Duplikatschutz nicht angeboten.",
            )
            return
        if not options:
            _telegram_send(chat_id, f"✅ „{query}“ ist bereits vorhanden.")
            return
        if existing_options:
            count = len(existing_options)
            message = (
                "✅ 1 bereits vorhandener Treffer wird nicht zum Download angeboten."
                if count == 1
                else f"✅ {count} bereits vorhandene Treffer werden nicht zum Download angeboten."
            )
            _telegram_send(chat_id, message)
        if requires_selection or len(options) > 1:
            _publish_telegram_movie_choices(chat_id, query, options)
            return
        selected = options[0]
    except Exception as exc:
        log(f"Telegram-Filmsuche fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Filmsuche fehlgeschlagen: {exc}")
        return
    finally:
        state.telegram_request_lock.release()

    _run_telegram_movie_request(chat_id, query, selected)


def _clear_telegram_choice_keyboards(chat_id: str, message_ids: List[int]) -> None:
    bot = backend_value("_telegram_bot")
    if bot is None:
        return
    for message_id in message_ids:
        bot.clear_inline_keyboard(chat_id, message_id)


def handle_telegram_callback(
    chat_id: str, callback_query_id: str, data: str, sender_name: str = "",
):
    bot = backend_value("_telegram_bot")
    if bot is None:
        return
    allowed_chat = str(state.telegram_cfg.get("chat_id", "")).strip()
    if not allowed_chat or chat_id != allowed_chat:
        bot.answer_callback(callback_query_id, "Nicht erlaubt.")
        log(f"Telegram-Callback von nicht erlaubter Chat-ID {chat_id} verworfen.", "warn")
        return

    movie_next_match = re.fullmatch(r"mrn:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if movie_next_match:
        token, raw_index = movie_next_match.groups()
        status, entry = _prepare_telegram_movie_next_page(chat_id, token, int(raw_index))
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None:
            bot.answer_callback(callback_query_id, "Seite abgelaufen oder bereits geladen.")
            return
        bot.answer_callback(callback_query_id, "Weitere Treffer werden geladen.")
        with state.telegram_choices_publish_lock:
            if not _send_telegram_movie_choice_page_locked(token, entry):
                _telegram_send(chat_id, "❌ Weitere Treffer konnten nicht gesendet werden.")
        return

    movie_match = re.fullmatch(r"mr:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if movie_match:
        token, raw_index = movie_match.groups()
        status, entry, option = _consume_telegram_movie_choice(
            chat_id, token, int(raw_index),
        )
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None or option is None:
            bot.answer_callback(callback_query_id, "Auswahl abgelaufen oder bereits verwendet.")
            return
        title = str(option.get("title") or "Film")
        bot.answer_callback(callback_query_id, f"Ausgewählt: {title}")
        threading.Thread(
            target=_clear_telegram_choice_keyboards,
            args=(chat_id, list(entry.get("message_ids", []))),
            daemon=True,
        ).start()
        _telegram_send(chat_id, f"✅ Ausgewählt: „{title}“.")
        _run_telegram_movie_request(
            chat_id, entry["query"], option, wait_for_lock=True,
        )
        return

    next_match = re.fullmatch(r"srn:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if next_match:
        token, raw_index = next_match.groups()
        status, entry = _prepare_telegram_series_next_page(
            chat_id, token, int(raw_index),
        )
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None:
            bot.answer_callback(callback_query_id, "Seite abgelaufen oder bereits geladen.")
            return
        bot.answer_callback(callback_query_id, "Weitere Treffer werden geladen.")
        with state.telegram_choices_publish_lock:
            if not _send_telegram_series_choice_page_locked(token, entry):
                _telegram_send(chat_id, "❌ Weitere Treffer konnten nicht gesendet werden.")
        return

    match = re.fullmatch(r"sr:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if not match:
        bot.answer_callback(callback_query_id, "Unbekannte Auswahl.")
        return
    token, raw_index = match.groups()
    status, entry, candidate = _consume_telegram_series_choice(
        chat_id, token, int(raw_index),
    )
    if status == "loading":
        bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
        return
    if status == "forbidden":
        bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
        return
    if status != "ok" or entry is None or candidate is None:
        bot.answer_callback(callback_query_id, "Auswahl abgelaufen oder bereits verwendet.")
        return

    title = strip_source_suffix(candidate.title).strip() or candidate.title
    bot.answer_callback(callback_query_id, f"Ausgewählt: {title}")
    threading.Thread(
        target=_clear_telegram_choice_keyboards,
        args=(chat_id, list(entry.get("message_ids", []))),
        daemon=True,
    ).start()
    _telegram_send(chat_id, f"✅ Ausgewählt: „{title}“.")
    _run_telegram_series_request(
        chat_id,
        entry["request"],
        candidate.sample_slug,
        wait_for_lock=True,
    )


def handle_telegram_message(chat_id: str, text: str, sender_name: str = ""):
    cfg = state.telegram_cfg
    allowed_chat = str(cfg.get("chat_id", "")).strip()

    # Sicherer Einrichtungsmodus: Ohne Whitelist werden keine Downloads erlaubt,
    # der Bot verrät dem Absender lediglich dessen Chat-ID.
    if not allowed_chat:
        _telegram_send(
            chat_id,
            f"Deine Chat-ID ist {chat_id}. Trage sie in Royal Downloader → Einstellungen → Telegram ein.",
        )
        return
    if chat_id != allowed_chat:
        log(f"Telegram-Zugriff von nicht erlaubter Chat-ID {chat_id} verworfen.", "warn")
        return

    command = text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    if command in ("/start", "/help", "/hilfe"):
        _telegram_send(chat_id, _telegram_help_text())
        return
    if command == "/status":
        active = state.dl_queue.active_count()
        pending = state.dl_queue.pending_count()
        with state.telegram_jobs_lock:
            titles = sorted({job["title"] for job in state.telegram_jobs.values()})
        detail = f"\nTelegram: {', '.join(titles)}" if titles else ""
        _telegram_send(chat_id, f"⬇️ Downloader: {active} aktiv, {pending} wartend.{detail}")
        return
    if command in ("/speicher", "/storage", "/disk"):
        _telegram_send(chat_id, _telegram_storage_text())
        return
    if command == "/pfade":
        _telegram_send(chat_id, _telegram_paths_text())
        return
    if command in ("/abos", "/serien"):
        _telegram_send(chat_id, _telegram_watchlist_text())
        return
    if command == "/jellyfin":
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin ist nicht konfiguriert.")
            return
        movies = jf_client.list_movies()
        episodes = jf_client.list_episodes()
        if movies is None or episodes is None:
            _telegram_send(chat_id, "⚠️ Jellyfin ist derzeit nicht erreichbar.")
            return
        _telegram_send(
            chat_id,
            f"🎞️ Jellyfin\n{len(movies)} Filme · {len(episodes)} Episoden\n{jf_client.base_url}",
        )
        return

    series_request = _parse_telegram_series_request(text)
    if series_request:
        _handle_telegram_series_request(chat_id, series_request)
        return
    if command == "/serie":
        _telegram_send(
            chat_id,
            "Format: /serie The Rookie ALLES · /serie The Rookie Staffel 8 · /serie The Rookie Staffel 8 EP 3",
        )
        return

    query = re.sub(r"^/film\s+", "", text, flags=re.IGNORECASE).strip()
    if not query or query.startswith("/"):
        _telegram_send(chat_id, "Sende einen Filmtitel oder nutze /status.")
        return

    _handle_telegram_movie_request(chat_id, query)


_SERVICE_EXPORTS = (
    "_parse_telegram_series_request",
    "_telegram_series_scope_label",
    "_telegram_best_result",
    "_format_storage_size",
    "_telegram_storage_text",
    "_telegram_paths_text",
    "_telegram_watchlist_text",
    "_telegram_help_text",
    "_run_telegram_series_request",
    "_handle_telegram_series_request",
    "_run_telegram_movie_request",
    "_handle_telegram_movie_request",
    "_clear_telegram_choice_keyboards",
    "handle_telegram_callback",
    "handle_telegram_message",
)
publish_service(globals(), _SERVICE_EXPORTS)
