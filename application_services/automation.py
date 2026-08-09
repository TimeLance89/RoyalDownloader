"""Scheduled library checks and automatic download services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# Automatische Bibliotheks-Prüfung (Benachrichtigungs-Glocke)
# ---------------------------------------------------------------------------
def is_within_download_window() -> bool:
    """True, wenn die aktuelle Uhrzeit im konfigurierten Download-Zeitfenster
    liegt. Ist kein Fenster gesetzt (start/end None), gilt: jederzeit. start>end
    bedeutet über Mitternacht (z.B. 1–7 Uhr = nachts)."""
    start = state.automation.get("dl_window_start")
    end = state.automation.get("dl_window_end")
    if start is None or end is None:
        return True
    now_h = time.localtime().tm_hour   # nutzt die Container-Zeitzone (TZ)
    if start == end:
        return True
    if start < end:
        return start <= now_h < end
    return now_h >= start or now_h < end   # Fenster über Mitternacht


def _watchlist_entry_for_episode(slug: str) -> dict | None:
    with state.watchlist_lock:
        return next(
            (
                entry
                for entry in state.watchlist
                if slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
            ),
            None,
        )


def _playable_episode_source(slug: str, primary):
    """Return a playable source or None while the episode has no release."""
    if primary is not None and getattr(primary, "hosters", None):
        return primary
    parsed = parse_episode_slug(slug)
    entry = _watchlist_entry_for_episode(slug)
    if not parsed or entry is None:
        return None
    _base_slug, season, episode = parsed
    fallbacks = find_episode_fallbacks(
        str(entry.get("title") or ""),
        season,
        episode,
        aliases=tuple(entry.get("aliases") or ()),
        source_slug=slug,
        limit=1,
    )
    return fallbacks[0] if fallbacks else None


def _auto_download_new_episodes():
    """Lädt alle als neu erkannten Episoden abonnierter Serien automatisch
    herunter (nutzt dieselbe Pipeline wie der manuelle Download inkl.
    konfigurierter Anbieter-Fallbacks). Neue Jobs werden auch
    während eines laufenden Downloads an dieselbe 2-Slot-Queue angehängt."""
    # Trigger nicht verwerfen: Ein direkt danach abgeschlossener Abo-/JF-Check
    # kann zusätzliche Slugs geliefert haben, die der erste Snapshot nicht sah.
    state.auto_download_lock.acquire()
    claimed: List[str] = []
    try:
        if not state.automation.get("auto_download"):
            return
        if not is_within_download_window():
            log("Auto-Download: außerhalb des Zeitfensters – warte.")
            broadcast({"type": "watchlist_update", **watchlist_payload()})
            return
        with state.watchlist_lock:
            pending = sorted(
                {
                    slug
                    for entry in state.watchlist
                    if not entry.get("last_error")
                    for slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
                },
                key=episode_sort_key,
            )
        if not pending:
            return

        prepared_slugs: List[str] = []
        for slug in pending:
            if not _watchlist_retry_allowed(slug):
                continue
            with state.watchlist_lock:
                if not any(
                    not entry.get("last_error")
                    and slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
                    for entry in state.watchlist
                ):
                    continue
            with state.queue_lifecycle_lock:
                physically_active = any(
                    slug in _job_queue_slugs(job) for job in state.dl_queue.active_jobs()
                )
                with state.queue_claim_lock:
                    with state.download_state_lock:
                        already_owned = (
                            slug in state.picked or slug in state.counted_queue_slugs
                        )
                    if physically_active or already_owned:
                        continue
                    state.picked.add(slug)
                    claimed.append(slug)
            try:
                movie = load_movie_for_slug(slug)
            except Exception as exc:
                log(f"Auto-Download: «{slug}» nicht ladbar: {exc}", "warn")
                movie = None
            movie = _playable_episode_source(slug, movie)
            if movie is None:
                with state.queue_claim_lock:
                    state.picked.discard(slug)
                claimed.remove(slug)
                with state.watchlist_lock:
                    entry = _watchlist_entry_for_episode(slug)
                    if entry is not None:
                        waiting = set(entry.get("waiting_release_slugs") or [])
                        waiting.add(slug)
                        entry["waiting_release_slugs"] = sorted(waiting)
                        failures = entry.get("failed_downloads")
                        if isinstance(failures, dict):
                            failures.pop(slug, None)
                log(
                    f"Auto-Download: «{slug}» ist gelistet, aber noch ohne "
                    "nutzbaren Release – wird weiter beobachtet."
                )
                continue

            with state.watchlist_lock:
                entry = _watchlist_entry_for_episode(slug)
                if entry is not None:
                    waiting = set(entry.get("waiting_release_slugs") or [])
                    waiting.discard(slug)
                    entry["waiting_release_slugs"] = sorted(waiting)

            already_available, reason = _content_already_available(movie, slug)
            if already_available:
                with state.queue_claim_lock:
                    state.picked.discard(slug)
                claimed.remove(slug)
                with state.watchlist_lock:
                    for entry in state.watchlist:
                        base_slug = entry.get("base_slug", "")
                        pending_for_entry = state.watchlist_new_slugs.get(base_slug, set())
                        if slug not in pending_for_entry:
                            continue
                        if _is_jellyfin_safety_block(reason):
                            entry["last_error"] = f"{reason} – Auto-Download pausiert"
                            continue
                        pending_for_entry.discard(slug)
                        failures = entry.get("failed_downloads")
                        if isinstance(failures, dict):
                            failures.pop(slug, None)
                        if not pending_for_entry:
                            state.watchlist_new_slugs.pop(base_slug, None)
                log(f"Auto-Download übersprungen: «{slug}» ist {reason}.")
                continue
            state.fp_movies[slug] = movie
            prepared_slugs.append(slug)
            with state.watchlist_lock:
                for entry in state.watchlist:
                    failures = entry.get("failed_downloads")
                    if isinstance(failures, dict):
                        failures.pop(slug, None)

        if not prepared_slugs:
            with state.watchlist_lock:
                _persist_watchlist_background()
            broadcast({"type": "watchlist_update", **watchlist_payload()})
            return

        with state.watchlist_lock:
            still_pending = {
                slug
                for entry in state.watchlist
                if not entry.get("last_error")
                for slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
            }
        withdrawn = set(prepared_slugs) - still_pending
        if withdrawn:
            with state.queue_claim_lock:
                state.picked.difference_update(withdrawn)
            prepared_slugs = [slug for slug in prepared_slugs if slug in still_pending]
        if not prepared_slugs:
            return

        if not _persist_new_queue_claims(prepared_slugs):
            log(
                "Auto-Download pausiert: Queue-Zustand konnte nicht gespeichert werden.",
                "warn",
            )
            return
        accepted = _enqueue_automatic_downloads(prepared_slugs, taste_source="watchlist")
        if len(accepted) != len(prepared_slugs):
            with state.queue_claim_lock:
                state.picked.difference_update(set(prepared_slugs) - accepted)
            _persist_queue_state()
        with state.watchlist_lock:
            _persist_watchlist_background()
        log(f"⬇ Auto-Download: {len(accepted)} neue Episode(n) eingereiht …")
        broadcast({"type": "watchlist_update", **watchlist_payload()})
    except Exception as exc:
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        with state.queue_claim_lock:
            state.picked.difference_update(slug for slug in claimed if slug not in counted)
        _persist_queue_state()
        log(f"Auto-Download konnte nicht eingeplant werden: {exc}", "err")
    finally:
        state.auto_download_lock.release()


WATCHLIST_JELLYFIN_RETRY_SECONDS = 15
WATCHLIST_QUICK_RETRY_ERRORS = (
    "Jellyfin nicht erreichbar",
    "Jellyfin-Serienindex nicht verfügbar",
    "Jellyfin-Benutzerstatus nicht verfügbar",
    "Jellyfin-Konfiguration wird geprüft",
    "Prüfung läuft",
)


def _watchlist_auto_check_once() -> tuple[int, int]:
    with state.watchlist_lock:
        entries = list(state.watchlist)
        before = {slug: set(eps) for slug, eps in state.watchlist_new_slugs.items()}
    if not entries:
        return 0, 0

    checked = check_watchlist_entries(entries, refresh_jellyfin=True)
    with state.watchlist_lock:
        found_new = any(
            state.watchlist_new_slugs.get(slug, set()) - before.get(slug, set())
            for slug in state.watchlist_new_slugs
        )
    broadcast({"type": "watchlist_update", **watchlist_payload()})
    if found_new:
        log("Neue Episode(n) in der Bibliothek verfügbar.")
    _auto_download_new_episodes()
    return checked, len(entries)


def _watchlist_auto_check_delay(checked: int, total: int, interval_min: int) -> int:
    if checked < total:
        with state.watchlist_lock:
            retry_jellyfin = any(
                any(
                    str(entry.get("last_error") or "").startswith(prefix)
                    for prefix in WATCHLIST_QUICK_RETRY_ERRORS
                )
                for entry in state.watchlist
            )
        if retry_jellyfin:
            return WATCHLIST_JELLYFIN_RETRY_SECONDS
    return max(5, int(interval_min)) * 60


def watchlist_auto_check_loop():
    """Prüft abonnierte Serien periodisch im Hintergrund auf neue Episoden,
    pusht das Ergebnis per WebSocket (Glocke) und lädt – falls Auto-Download
    aktiv ist und wir im Zeitfenster sind – die neuen Folgen direkt herunter.
    Das Intervall ist über die Automatik-Einstellungen konfigurierbar."""
    while True:
        interval_min = state.automation.get("check_interval_min", 30)
        checked = total = 0
        try:
            checked, total = _watchlist_auto_check_once()
        except Exception as exc:
            log(f"Automatische Bibliotheks-Prüfung fehlgeschlagen: {exc}", "warn")
        try:
            check_movie_subscriptions()
        except Exception as exc:
            log(f"Automatische Film-Abo-Prüfung fehlgeschlagen: {exc}", "warn")
        time.sleep(_watchlist_auto_check_delay(checked, total, interval_min))


_SERVICE_EXPORTS = (
    "is_within_download_window",
    "_playable_episode_source",
    "_auto_download_new_episodes",
    "WATCHLIST_JELLYFIN_RETRY_SECONDS",
    "WATCHLIST_QUICK_RETRY_ERRORS",
    "_watchlist_auto_check_once",
    "_watchlist_auto_check_delay",
    "watchlist_auto_check_loop",
)
publish_service(globals(), _SERVICE_EXPORTS)
