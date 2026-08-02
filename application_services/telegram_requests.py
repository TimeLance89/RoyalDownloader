"""Telegram request selection, pagination, and completion services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# Telegram-Filmwünsche
# ---------------------------------------------------------------------------
TELEGRAM_JELLYFIN_WAIT_SECONDS = 30 * 60
TELEGRAM_SERIES_CHOICE_TTL_SECONDS = 10 * 60
TELEGRAM_SERIES_LOADING_TTL_SECONDS = 30 * 60
TELEGRAM_SERIES_PAGE_SIZE = 6
TELEGRAM_SERIES_MAX_PENDING = 20


def _telegram_send(chat_id: str, text: str):
    bot = backend_value("_telegram_bot")
    if bot is not None:
        bot.send(chat_id, text)


def _rank_telegram_series_results(
    query: str, results: List[FilmpalastSeriesResult],
) -> List[FilmpalastSeriesResult]:
    wanted = _norm_title(query)
    unique: Dict[str, FilmpalastSeriesResult] = {}
    for result in results:
        key = result.base_slug or result.sample_slug
        if key and key not in unique:
            unique[key] = result
    ranked = sorted(
        unique.values(),
        key=lambda result: (
            _norm_title(result.title) != wanted,
            wanted not in _norm_title(result.title),
            abs(len(_norm_title(result.title)) - len(wanted)),
            not _norm_title(result.title).startswith(wanted),
            clean_movie_title(result.title).casefold(),
        ),
    )
    # Identische Titel verschiedener Anbieter sind keine Auswahlvarianten. Der
    # erste Treffer folgt der Nutzerpriorität; weitere Quellen bleiben Fallbacks.
    deduped: List[FilmpalastSeriesResult] = []
    seen_titles: set[str] = set()
    for result in ranked:
        title_key = _norm_title(result.title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        deduped.append(result)
    return deduped


def _prune_telegram_series_choices_locked(
    now: float, reserve_slot: bool = False,
) -> None:
    expired = [
        token for token, entry in state.telegram_series_choices.items()
        if float(entry.get("expires_at", 0)) <= now
    ]
    for token in expired:
        state.telegram_series_choices.pop(token, None)
    limit = TELEGRAM_SERIES_MAX_PENDING - (1 if reserve_slot else 0)
    while len(state.telegram_series_choices) > limit:
        oldest = min(
            state.telegram_series_choices,
            key=lambda token: float(
                state.telegram_series_choices[token].get("created_at", 0),
            ),
        )
        state.telegram_series_choices.pop(oldest, None)


def _telegram_series_choice_markup(token: str, index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Diese Serie auswählen",
        "callback_data": f"sr:{token}:{index}",
    }]]}


def _telegram_series_next_markup(token: str, next_index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Weitere Treffer anzeigen",
        "callback_data": f"srn:{token}:{next_index}",
    }]]}


def _telegram_movie_choice_markup(token: str, index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Diesen Film auswählen",
        "callback_data": f"mr:{token}:{index}",
    }]]}


def _telegram_movie_next_markup(token: str, next_index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Weitere Treffer anzeigen",
        "callback_data": f"mrn:{token}:{next_index}",
    }]]}


def _send_telegram_series_choice_page_locked(token: str, entry: dict) -> bool:
    bot = backend_value("_telegram_bot")
    if bot is None:
        return False
    chat_id = entry["chat_id"]
    candidates = entry["candidates"]
    start = int(entry.get("next_index", 0))
    end = min(start + TELEGRAM_SERIES_PAGE_SIZE, len(candidates))
    sent_message_ids = []
    sent_candidate_count = 0

    for index in range(start, end):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is not entry:
                break
        candidate = candidates[index]
        title = clean_movie_title(candidate.title) or candidate.title
        caption = f"{index + 1}. {title}"
        if candidate.year:
            caption += f" ({candidate.year})"
        caption = caption[:1024]
        markup = _telegram_series_choice_markup(token, index)
        message_id = None
        cover_data = _fetch_cover_data(candidate.cover_url) if candidate.cover_url else None
        if cover_data:
            content, content_type = cover_data
            message_id = bot.send_photo(
                chat_id, content, caption, markup, content_type,
            )
        if message_id is None and candidate.cover_url:
            message_id = bot.send_photo(
                chat_id, candidate.cover_url, caption, markup,
            )
        if message_id is None:
            message_id = bot.send_message(
                chat_id, f"🖼️ {caption}\n(Cover nicht verfügbar)", markup,
            )
        if message_id is not None:
            sent_message_ids.append(message_id)
            sent_candidate_count += 1

    with state.telegram_choices_lock:
        current = state.telegram_series_choices.get(token)
    if current is not entry:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False

    if sent_candidate_count and end < len(candidates):
        remaining = len(candidates) - end
        message_id = bot.send_message(
            chat_id,
            f"Noch {remaining} Treffer.",
            _telegram_series_next_markup(token, end),
        )
        if message_id is not None:
            sent_message_ids.append(message_id)

    with state.telegram_choices_lock:
        if state.telegram_series_choices.get(token) is not entry:
            stale = True
        else:
            stale = False
            entry["message_ids"].extend(sent_message_ids)
            entry["next_index"] = end if sent_candidate_count else start
            entry["ready"] = True
            entry["expires_at"] = (
                time.monotonic() + TELEGRAM_SERIES_CHOICE_TTL_SECONDS
            )
    if stale:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False
    return bool(sent_candidate_count)


def _publish_telegram_series_choices_locked(
    chat_id: str,
    request: dict,
    results: List[FilmpalastSeriesResult],
) -> None:
    candidates = list(results)
    if not candidates or backend_value("_telegram_bot") is None:
        _telegram_send(chat_id, "❌ Telegram-Auswahl konnte nicht erstellt werden.")
        return

    now = time.monotonic()
    token = secrets.token_urlsafe(9)
    entry = {
        "kind": "series",
        "chat_id": chat_id,
        "request": dict(request),
        "candidates": candidates,
        "created_at": now,
        "expires_at": now + TELEGRAM_SERIES_LOADING_TTL_SECONDS,
        "message_ids": [],
        "next_index": 0,
        "ready": False,
    }
    old_message_ids = []
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        for old_token, old_entry in list(state.telegram_series_choices.items()):
            if old_entry.get("chat_id") == chat_id:
                old_message_ids.extend(old_entry.get("message_ids", []))
                state.telegram_series_choices.pop(old_token, None)
        _prune_telegram_series_choices_locked(now, reserve_slot=True)
        state.telegram_series_choices[token] = entry
    if old_message_ids:
        threading.Thread(
            target=_clear_telegram_choice_keyboards,
            args=(chat_id, old_message_ids),
            daemon=True,
        ).start()

    _telegram_send(
        chat_id,
        f"🔎 {len(results)} Serien gefunden. Bitte die richtige auswählen:",
    )
    if not _send_telegram_series_choice_page_locked(token, entry):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is entry:
                state.telegram_series_choices.pop(token, None)
        _telegram_send(chat_id, "❌ Treffer konnten nicht an Telegram gesendet werden.")


def _publish_telegram_series_choices(
    chat_id: str,
    request: dict,
    results: List[FilmpalastSeriesResult],
) -> None:
    with state.telegram_choices_publish_lock:
        _publish_telegram_series_choices_locked(chat_id, request, results)


def _consume_telegram_series_choice(
    chat_id: str, token: str, index: int,
) -> tuple[str, Optional[dict], Optional[FilmpalastSeriesResult]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None, None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None, None
        if entry.get("kind", "series") != "series":
            return "invalid", None, None
        if not entry.get("ready"):
            return "loading", None, None
        candidates = entry.get("candidates") or []
        if index < 0 or index >= len(candidates):
            return "invalid", None, None
        state.telegram_series_choices.pop(token, None)
        return "ok", entry, candidates[index]


def _prepare_telegram_series_next_page(
    chat_id: str, token: str, next_index: int,
) -> tuple[str, Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None
        if entry.get("kind", "series") != "series":
            return "invalid", None
        if not entry.get("ready"):
            return "loading", None
        candidates = entry.get("candidates") or []
        if next_index != entry.get("next_index") or next_index >= len(candidates):
            return "invalid", None
        entry["ready"] = False
        entry["expires_at"] = now + TELEGRAM_SERIES_LOADING_TTL_SECONDS
        return "ok", entry


def _build_telegram_movie_options(
    query: str, results: List[FilmpalastSearchResult],
) -> List[dict]:
    """Lädt Film-Treffer und bündelt identische Titel/Jahre als Fallbacks."""
    grouped: Dict[tuple, dict] = {}
    seen_urls: set[str] = set()
    for candidate in _telegram_best_result(query, results):
        if not candidate.is_movie:
            continue
        try:
            loaded = load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"Telegram-Filmtreffer nicht ladbar ({candidate.slug}): {exc}", "warn")
            continue
        if not loaded or not loaded.hosters or loaded.url in seen_urls:
            continue
        seen_urls.add(loaded.url)
        title = clean_movie_title(loaded.title) or clean_movie_title(candidate.title)
        year = str(loaded.year or candidate.year or "")
        key = (_norm_title(title), year)
        option = grouped.get(key)
        if option is None:
            grouped[key] = {
                "result": candidate,
                "movie": loaded,
                "fallback_movies": [],
                "title": title,
                "year": year,
                "cover_url": loaded.cover_url,
            }
        else:
            option["fallback_movies"].append(loaded)
            if not option.get("cover_url") and loaded.cover_url:
                option["cover_url"] = loaded.cover_url
    return list(grouped.values())


def _filter_existing_telegram_movie_options(
    options: List[dict],
) -> tuple[Optional[List[dict]], List[dict], str]:
    """Entfernt vorhandene Filme, bevor Telegram Download-Buttons anzeigt."""
    jf_items = get_jellyfin_library(force=True)
    with state.jellyfin_cache_lock:
        library_available = state.jellyfin_library_available
    if jf_items is None or not library_available:
        return None, [], "Jellyfin ist nicht erreichbar"

    downloadable = []
    existing = []
    for option in options:
        movie = option["movie"]
        result = option["result"]
        already_available, reason = _content_already_available(movie, result.slug)
        if already_available:
            if _is_jellyfin_safety_block(reason):
                return None, existing, reason
            existing.append(option)
        else:
            downloadable.append(option)
    return downloadable, existing, ""


def _send_telegram_movie_choice_page_locked(token: str, entry: dict) -> bool:
    bot = backend_value("_telegram_bot")
    if bot is None:
        return False
    chat_id = entry["chat_id"]
    candidates = entry["candidates"]
    start = int(entry.get("next_index", 0))
    end = min(start + TELEGRAM_SERIES_PAGE_SIZE, len(candidates))
    sent_message_ids = []
    sent_candidate_count = 0

    for index in range(start, end):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is not entry:
                break
        option = candidates[index]
        caption = f"{index + 1}. {option['title']}"
        if option.get("year"):
            caption += f" ({option['year']})"
        source_count = 1 + len(option.get("fallback_movies", []))
        if source_count > 1:
            caption += f" · {source_count} Quellen"
        markup = _telegram_movie_choice_markup(token, index)
        message_id = None
        cover_url = str(option.get("cover_url") or "")
        cover_data = _fetch_cover_data(cover_url) if cover_url else None
        if cover_data:
            content, content_type = cover_data
            message_id = bot.send_photo(chat_id, content, caption[:1024], markup, content_type)
        if message_id is None and cover_url:
            message_id = bot.send_photo(chat_id, cover_url, caption[:1024], markup)
        if message_id is None:
            message_id = bot.send_message(
                chat_id, f"🖼️ {caption}\n(Cover nicht verfügbar)", markup,
            )
        if message_id is not None:
            sent_message_ids.append(message_id)
            sent_candidate_count += 1

    with state.telegram_choices_lock:
        current = state.telegram_series_choices.get(token)
    if current is not entry:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False

    if sent_candidate_count and end < len(candidates):
        remaining = len(candidates) - end
        message_id = bot.send_message(
            chat_id,
            f"Noch {remaining} Treffer.",
            _telegram_movie_next_markup(token, end),
        )
        if message_id is not None:
            sent_message_ids.append(message_id)

    with state.telegram_choices_lock:
        if state.telegram_series_choices.get(token) is not entry:
            stale = True
        else:
            stale = False
            entry["message_ids"].extend(sent_message_ids)
            entry["next_index"] = end if sent_candidate_count else start
            entry["ready"] = True
            entry["expires_at"] = time.monotonic() + TELEGRAM_SERIES_CHOICE_TTL_SECONDS
    if stale:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False
    return bool(sent_candidate_count)


def _publish_telegram_movie_choices(
    chat_id: str, query: str, options: List[dict],
) -> None:
    with state.telegram_choices_publish_lock:
        if not options or backend_value("_telegram_bot") is None:
            _telegram_send(chat_id, "❌ Telegram-Auswahl konnte nicht erstellt werden.")
            return
        now = time.monotonic()
        token = secrets.token_urlsafe(9)
        entry = {
            "kind": "movie",
            "chat_id": chat_id,
            "query": query,
            "candidates": list(options),
            "created_at": now,
            "expires_at": now + TELEGRAM_SERIES_LOADING_TTL_SECONDS,
            "message_ids": [],
            "next_index": 0,
            "ready": False,
        }
        old_message_ids = []
        with state.telegram_choices_lock:
            _prune_telegram_series_choices_locked(now)
            for old_token, old_entry in list(state.telegram_series_choices.items()):
                if old_entry.get("chat_id") == chat_id:
                    old_message_ids.extend(old_entry.get("message_ids", []))
                    state.telegram_series_choices.pop(old_token, None)
            _prune_telegram_series_choices_locked(now, reserve_slot=True)
            state.telegram_series_choices[token] = entry
        if old_message_ids:
            threading.Thread(
                target=_clear_telegram_choice_keyboards,
                args=(chat_id, old_message_ids),
                daemon=True,
            ).start()
        _telegram_send(
            chat_id,
            f"🔎 {len(options)} Filme gefunden. Bitte den richtigen auswählen:",
        )
        if not _send_telegram_movie_choice_page_locked(token, entry):
            with state.telegram_choices_lock:
                if state.telegram_series_choices.get(token) is entry:
                    state.telegram_series_choices.pop(token, None)
            _telegram_send(chat_id, "❌ Treffer konnten nicht an Telegram gesendet werden.")


def _consume_telegram_movie_choice(
    chat_id: str, token: str, index: int,
) -> tuple[str, Optional[dict], Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None, None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None, None
        if entry.get("kind") != "movie":
            return "invalid", None, None
        if not entry.get("ready"):
            return "loading", None, None
        candidates = entry.get("candidates") or []
        if index < 0 or index >= len(candidates):
            return "invalid", None, None
        state.telegram_series_choices.pop(token, None)
        return "ok", entry, candidates[index]


def _prepare_telegram_movie_next_page(
    chat_id: str, token: str, next_index: int,
) -> tuple[str, Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None
        if entry.get("kind") != "movie":
            return "invalid", None
        if not entry.get("ready"):
            return "loading", None
        candidates = entry.get("candidates") or []
        if next_index != entry.get("next_index") or next_index >= len(candidates):
            return "invalid", None
        entry["ready"] = False
        entry["expires_at"] = now + TELEGRAM_SERIES_LOADING_TTL_SECONDS
        return "ok", entry


def _telegram_finish_job(job: dict, ok: bool, message: str, out_path: Path):
    chat_id = job["chat_id"]
    title = job["title"]
    year = job.get("year", "")
    if not ok:
        _telegram_send(chat_id, f"❌ Download von „{title}“ fehlgeschlagen: {message}")
        return

    jf_client = get_jellyfin_client()
    with state.jellyfin_cache_lock:
        jellyfin_generation = state.jellyfin_config_generation
    if not jf_client.configured:
        _telegram_send(chat_id, f"✅ „{title}“ wurde geladen: {out_path}\nJellyfin ist nicht konfiguriert.")
        return

    log(f"Telegram: Jellyfin-Scan für «{title}» gestartet.")
    jf_client.refresh_library()
    deadline = time.monotonic() + TELEGRAM_JELLYFIN_WAIT_SECONDS
    while time.monotonic() < deadline:
        items = get_jellyfin_library(force=True)
        with state.jellyfin_cache_lock:
            data_generation = state.jellyfin_movie_data_generation
            library_available = state.jellyfin_library_available
            current_generation = state.jellyfin_config_generation
        if current_generation != jellyfin_generation:
            jellyfin_generation = current_generation
            jf_client = get_jellyfin_client()
            if not jf_client.configured:
                _telegram_send(
                    chat_id,
                    f"✅ „{title}“ wurde geladen: {out_path}\nJellyfin ist nicht konfiguriert.",
                )
                return
            jf_client.refresh_library()
        if items is None or not library_available:
            time.sleep(15)
            continue
        if jf_client.match(
            title, year, items=items, tmdb_id=job.get("tmdb_id", ""),
        ):
            with state.jellyfin_cache_lock:
                stale = (
                    jellyfin_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_movie_data_generation
                )
            if stale:
                continue
            _telegram_send(chat_id, f"✅ „{title}“ ist jetzt in Jellyfin verfügbar.")
            return
        time.sleep(15)

    _telegram_send(
        chat_id,
        f"⚠️ „{title}“ wurde nach {out_path} geladen, ist aber nach 30 Minuten noch nicht in Jellyfin erschienen.",
    )


def _telegram_series_job_result(job: dict, slug: str, ok: bool, message: str, out_path: Path):
    """Sammelt Einzelergebnisse einer Telegram-Serienanfrage."""
    finished_group = None
    with state.telegram_jobs_lock:
        group = state.telegram_series_requests.get(job.get("request_id", ""))
        if not group:
            return
        group["pending_slugs"].discard(slug)
        label = f"S{job['season']:02d}E{job['episode']:02d}"
        if ok:
            group["completed"].append({
                "season": job["season"], "episode": job["episode"],
                "label": label, "path": str(out_path),
            })
        else:
            group["failed"].append(f"{label}: {message}")
        if not group["pending_slugs"]:
            finished_group = state.telegram_series_requests.pop(job["request_id"], None)
    if finished_group:
        threading.Thread(
            target=_telegram_finish_series_request,
            args=(finished_group,),
            daemon=True,
        ).start()


def _telegram_terminal_without_job(slug: str, ok: bool, message: str, out_path: Path):
    """Beendet Telegram-Tracking, wenn kein DownloadJob erzeugt wurde."""
    with state.queue_claim_lock:
        state.picked.discard(slug)
    _persist_queue_state()
    with state.telegram_jobs_lock:
        job = state.telegram_jobs.pop(slug, None)
    if not job:
        return
    if job.get("kind") == "series":
        _telegram_series_job_result(job, slug, ok, message, out_path)
    elif ok:
        threading.Thread(
            target=_telegram_finish_job,
            args=(job, True, message, out_path),
            daemon=True,
        ).start()
    else:
        _telegram_send(job["chat_id"], f"❌ Download von „{job['title']}“ fehlgeschlagen: {message}")


def _telegram_finish_series_request(group: dict):
    chat_id = group["chat_id"]
    title = group["title"]
    completed = group["completed"]
    failed = group["failed"]
    if not completed:
        detail = f"\n{failed[0]}" if failed else ""
        _telegram_send(chat_id, f"❌ Für „{title}“ konnte keine Episode geladen werden.{detail}")
        return

    jf_client = get_jellyfin_client()
    with state.jellyfin_cache_lock:
        jellyfin_generation = state.jellyfin_config_generation
    if not jf_client.configured:
        suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
        _telegram_send(chat_id, f"✅ {len(completed)} Episode(n) von „{title}“ geladen{suffix}.")
        return

    log(f"Telegram: Jellyfin-Scan für Serie «{title}» gestartet.")
    jf_client.refresh_library()
    deadline = time.monotonic() + TELEGRAM_JELLYFIN_WAIT_SECONDS
    while time.monotonic() < deadline:
        items = get_jellyfin_episodes(force=True)
        series_items = get_jellyfin_series(force=True)
        with state.jellyfin_cache_lock:
            data_generation = state.jellyfin_episode_data_generation
            current_generation = state.jellyfin_config_generation
            episodes_available = state.jellyfin_episodes_available
            series_available = state.jellyfin_series_available
        if current_generation != jellyfin_generation:
            jellyfin_generation = current_generation
            jf_client = get_jellyfin_client()
            if not jf_client.configured:
                suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
                _telegram_send(
                    chat_id,
                    f"✅ {len(completed)} Episode(n) von „{title}“ geladen{suffix}. "
                    "Jellyfin ist nicht konfiguriert.",
                )
                return
            jf_client.refresh_library()
        if (
            items is None or series_items is None
            or not episodes_available
            or not series_available
        ):
            time.sleep(15)
            continue
        series_ids = jf_client.series_ids_for(
            title,
            tmdb_id=group.get("tmdb_id", ""),
            aliases=group.get("aliases", ()),
            items=series_items,
        )
        if series_ids is None:
            time.sleep(15)
            continue
        if all(
            jf_client.has_episode(
                title, item["season"], item["episode"], items=items,
                aliases=group.get("aliases", ()), series_ids=series_ids,
            )
            for item in completed
        ):
            with state.jellyfin_cache_lock:
                stale = (
                    jellyfin_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_episode_data_generation
                )
            if stale:
                continue
            suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
            _telegram_send(
                chat_id,
                f"✅ „{title}“: {len(completed)} Episode(n) sind jetzt in Jellyfin verfügbar{suffix}.",
            )
            return
        time.sleep(15)

    suffix = f" {len(failed)} Download(s) sind fehlgeschlagen." if failed else ""
    _telegram_send(
        chat_id,
        f"⚠️ {len(completed)} Episode(n) von „{title}“ wurden geladen, sind aber nach 30 Minuten noch nicht vollständig in Jellyfin erschienen.{suffix}",
    )


_SERVICE_EXPORTS = (
    "TELEGRAM_JELLYFIN_WAIT_SECONDS",
    "TELEGRAM_SERIES_CHOICE_TTL_SECONDS",
    "TELEGRAM_SERIES_LOADING_TTL_SECONDS",
    "TELEGRAM_SERIES_PAGE_SIZE",
    "TELEGRAM_SERIES_MAX_PENDING",
    "_telegram_send",
    "_rank_telegram_series_results",
    "_prune_telegram_series_choices_locked",
    "_telegram_series_choice_markup",
    "_telegram_series_next_markup",
    "_telegram_movie_choice_markup",
    "_telegram_movie_next_markup",
    "_send_telegram_series_choice_page_locked",
    "_publish_telegram_series_choices_locked",
    "_publish_telegram_series_choices",
    "_consume_telegram_series_choice",
    "_prepare_telegram_series_next_page",
    "_build_telegram_movie_options",
    "_filter_existing_telegram_movie_options",
    "_send_telegram_movie_choice_page_locked",
    "_publish_telegram_movie_choices",
    "_consume_telegram_movie_choice",
    "_prepare_telegram_movie_next_page",
    "_telegram_finish_job",
    "_telegram_series_job_result",
    "_telegram_terminal_without_job",
    "_telegram_finish_series_request",
)
publish_service(globals(), _SERVICE_EXPORTS)
