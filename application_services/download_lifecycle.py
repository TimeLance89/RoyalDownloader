"""Download completion, provider health, and fallback lifecycle services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# Download-Pipeline (1:1 aus main.py._build_and_start_queue portiert)
# ---------------------------------------------------------------------------
def on_job_progress(
    pct: float,
    msg: str,
    label: str,
    *,
    slug: str = "",
    job_id: str = "",
    attempt_id: str = "",
    downloaded_bytes: int = 0,
    total_bytes=None,
    speed_bps: float = 0.0,
    eta_seconds=None,
):
    payload = {"type": "progress", "label": label, "msg": msg}
    if slug:
        current = _queue_job_for_slug(slug)
        if not current or (
            job_id and current.get("job_id") != job_id
        ) or (
            attempt_id and current.get("attempt_id") != attempt_id
        ) or current.get("status") == "cancelling":
            return False
        now = time.monotonic()
        with state.queue_claim_lock:
            last_persisted = float(state.queue_job_persist_times.get(slug) or 0)
            should_persist = pct >= 100 or now - last_persisted >= 1.0
            if should_persist:
                state.queue_job_persist_times[slug] = now
        logical = _update_queue_job(
            slug,
            persist=False,
            expected_job_id=job_id,
            expected_attempt_id=attempt_id,
            status="downloading",
            progress=max(0.0, pct) if pct >= 0 else None,
            downloaded_bytes=max(0, int(downloaded_bytes or 0)),
            total_bytes=total_bytes,
            speed_bps=max(0.0, float(speed_bps or 0)),
            eta_seconds=eta_seconds,
        )
        if should_persist:
            _persist_queue_state()
        if logical:
            payload["job"] = logical
            job_id = logical["job_id"]
    if job_id:
        payload["job_id"] = job_id
    if attempt_id:
        payload["attempt_id"] = attempt_id
    if slug:
        payload["slug"] = slug
    if pct >= 0:
        payload["pct"] = pct
    broadcast(payload)
    return True


def _failure_record(previous, message: str) -> dict:
    attempts = int(previous.get("attempts", 0)) if isinstance(previous, dict) else 0
    attempts += 1
    retry_delay = min(6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)))
    return {
        "message": str(message)[:240],
        "attempts": attempts,
        "next_retry": time.time() + retry_delay,
    }


def _watchlist_retry_allowed(slug: str) -> bool:
    with state.watchlist_lock:
        for entry in state.watchlist:
            failure = (entry.get("failed_downloads") or {}).get(slug)
            if isinstance(failure, dict):
                return time.time() >= float(failure.get("next_retry", 0) or 0)
    return True


def on_job_done(
    ok: bool,
    msg: str,
    label: str,
    out_path: Path,
    hoster_url: str = "",
    slug: str = "",
    job_id: str = "",
    attempt_id: str = "",
):
    # Der Counter-Eintrag ist das einmalige Abschlusstoken. Entfernen/Abbruch
    # kann es vor einem verspäteten Callback konsumieren; dieser wird dann
    # vollständig ignoriert und kann done/total nicht mehr verfälschen.
    with state.queue_claim_lock:
        current = _queue_job_for_slug(slug) if slug else None
        if slug and (
            current is None
            or (job_id and current.get("job_id") != job_id)
            or (attempt_id and current.get("attempt_id") != attempt_id)
        ):
            return False
        if current and current.get("status") == "cancelling":
            ok, msg = False, "Abgebrochen"
        with state.download_state_lock:
            if slug and slug not in state.counted_queue_slugs:
                return False
            if slug:
                state.provider_waiting_jobs.pop(slug, None)
            if ok and slug:
                state.done_slugs.add(slug)
            state.done_jobs += 1
            if slug:
                state.counted_queue_slugs.discard(slug)
                state.picked.discard(slug)
            done_jobs = state.done_jobs
            total_jobs = state.total_jobs
            successful_jobs = len(state.done_slugs)
            failed_jobs = max(0, done_jobs - successful_jobs)
    if hoster_url:
        state.hoster_intel.record_download(hoster_url, ok)
    if ok:
        log(f"Fertig: {label} -> {out_path}")
    else:
        log(f"Fehler {label}: {msg}", "err")
    terminal_job = None
    if slug:
        # `picked` bildet ausschließlich noch offene Warteschlangen-Einträge ab.
        # Erst hier entfernen: Laufzeit-Fallbacks erreichen diese Funktion erst
        # nach Erfolg oder nachdem wirklich alle Anbieter ausgeschöpft sind.
        terminal_job = _terminal_queue_job(
            slug,
            "completed" if ok else ("cancelled" if msg == "Abgebrochen" else "failed"),
            error="" if ok else msg,
            final_path=str(out_path) if ok else "",
            persist=False,
            expected_job_id=job_id,
            expected_attempt_id=attempt_id,
        )
        _persist_queue_state()
        watchlist_changed = False
        with state.watchlist_lock:
            for entry in state.watchlist:
                base_slug = entry.get("base_slug", "")
                pending = state.watchlist_new_slugs.get(base_slug, set())
                failures = entry.get("failed_downloads")
                if not isinstance(failures, dict):
                    failures = {}
                    entry["failed_downloads"] = failures
                if slug not in pending and slug not in failures:
                    continue
                if ok:
                    pending.discard(slug)
                    failures.pop(slug, None)
                    if not pending:
                        state.watchlist_new_slugs.pop(base_slug, None)
                elif msg != "Abgebrochen":
                    failures[slug] = _failure_record(failures.get(slug), msg)
                else:
                    failures.pop(slug, None)
                watchlist_changed = True
            if watchlist_changed:
                _persist_watchlist_background()
        if watchlist_changed:
            broadcast({"type": "watchlist_update", **watchlist_payload()})
        if not ok and not parse_episode_slug(slug):
            _movie_subscription_download_failed(slug, msg)
        with state.telegram_jobs_lock:
            telegram_job = state.telegram_jobs.pop(slug, None)
        if telegram_job:
            if telegram_job.get("kind") == "series":
                _telegram_series_job_result(telegram_job, slug, ok, msg, out_path)
            else:
                threading.Thread(
                    target=_telegram_finish_job,
                    args=(telegram_job, ok, msg, out_path),
                    daemon=True,
                ).start()
        with state.seerr_jobs_lock:
            seerr_jobs = state.seerr_jobs.pop(slug, [])
        for seerr_job in seerr_jobs:
            _seerr_job_result(seerr_job, slug, ok, msg, out_path)
    broadcast({
        "type": "job_done", "ok": ok, "label": label, "slug": slug, "msg": msg,
        "job_id": (terminal_job or {}).get("job_id", ""),
        "attempt_id": (terminal_job or {}).get("attempt_id", attempt_id),
        "job": terminal_job,
        "done_jobs": done_jobs, "total_jobs": total_jobs,
        "successful_jobs": successful_jobs, "failed_jobs": failed_jobs,
        "active": state.dl_queue.active_count(), "pending": state.dl_queue.pending_count(),
    })
    return True


def _refresh_jellyfin_after_download_once():
    """Scan anstoßen und den UI-Cache während des Jellyfin-Imports erneuern."""
    if not state.jellyfin_refresh_lock.acquire(blocking=False):
        log("Jellyfin-Aktualisierung läuft bereits.")
        return
    try:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            user_id = state.jellyfin_cfg.get("user_id", "").strip()
        if not jf_client.configured:
            return
        if not jf_client.refresh_library():
            log("Jellyfin-Bibliotheksscan konnte nicht gestartet werden.", "warn")
            return
        log("Jellyfin-Bibliotheksscan gestartet.")
        started = time.monotonic()
        for deadline in (5, 15, 30, 60, 120):
            time.sleep(max(0.0, deadline - (time.monotonic() - started)))
            withdrawn_slugs: set[str] = set()
            with state.jellyfin_cache_lock:
                if generation != state.jellyfin_config_generation:
                    log("Jellyfin-Aktualisierung verworfen: Konfiguration wurde geändert.", "warn")
                    return

            get_jellyfin_library(force=True)
            # Der globale Bestand und der benutzerspezifische Gesehen-Status
            # dürfen sich nicht gegenseitig überschreiben.
            get_jellyfin_episodes(force=True)
            get_jellyfin_series(force=True)
            if user_id:
                get_jellyfin_user_episodes(force=True)
            with state.jellyfin_cache_lock:
                # Ein Bibliotheksscan kann die Episoden jeder einzelnen Serie
                # verändert haben. Detail-Caches werden deshalb atomar
                # verworfen und beim nächsten Öffnen gezielt neu aufgebaut.
                state.jellyfin_targeted_episodes.clear()
                if generation != state.jellyfin_config_generation:
                    log("Jellyfin-Aktualisierung verworfen: Konfiguration wurde geändert.", "warn")
                    return
                global_episodes = state.jellyfin_episodes
                global_series = state.jellyfin_series
                global_available = state.jellyfin_episodes_available
                global_series_available = state.jellyfin_series_available
                user_episodes = state.jellyfin_user_episodes if user_id else None
                user_available = state.jellyfin_user_episodes_available if user_id else False
                data_generation = state.jellyfin_episode_data_generation

            # NAS-Scan/Policy außerhalb des Watchlist-Locks berechnen. Sonst
            # blockieren Bell, Abo-Aktionen und fertige Download-Callbacks.
            with state.watchlist_lock:
                snapshots = []
                for entry in state.watchlist:
                    entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
                    entry["last_error"] = "Prüfung läuft – Auto-Download pausiert"
                    snapshots.append((
                        entry,
                        dict(entry),
                        state.series_cache.get(entry["base_slug"]),
                        entry["check_generation"],
                    ))
            calculated_updates = []
            for entry, snapshot, series, revision in snapshots:
                needs_user = normalize_watch_mode(snapshot.get("download_mode")) == WATCH_MODE_NEXT_SEASON
                if global_episodes is None or not global_available:
                    calculated_updates.append((entry, revision, None, "Jellyfin nicht erreichbar – Auto-Download pausiert"))
                elif global_series is None or not global_series_available:
                    calculated_updates.append((entry, revision, None, "Jellyfin-Serienindex nicht verfügbar"))
                elif needs_user and (not user_id or user_episodes is None or not user_available):
                    calculated_updates.append((entry, revision, None, "Jellyfin-Benutzerstatus nicht verfügbar"))
                elif series is not None:
                    try:
                        calculated = _calculate_watchlist_entry_state(
                            snapshot, series, jf_client, global_episodes, user_episodes,
                            global_series,
                        )
                        calculated_updates.append((entry, revision, calculated, ""))
                    except Exception as exc:
                        calculated_updates.append((entry, revision, None, str(exc)[:240]))
            with state.jellyfin_cache_lock:
                data_is_current = (
                    generation == state.jellyfin_config_generation
                    and data_generation == state.jellyfin_episode_data_generation
                )
                with state.watchlist_lock:
                    if data_is_current:
                        for entry, revision, calculated, error in calculated_updates:
                            if not any(current is entry for current in state.watchlist):
                                continue
                            if int(entry.get("check_generation", 0)) != revision:
                                continue
                            if error:
                                entry["last_checked"] = time.time()
                                entry["last_error"] = error
                            elif calculated is not None:
                                withdrawn_slugs.update(
                                    _apply_watchlist_entry_state(entry, calculated)
                                )
                    _persist_watchlist_background()
            if withdrawn_slugs:
                _cancel_withdrawn_watchlist_slugs(
                    withdrawn_slugs,
                    "In Jellyfin vorhanden oder nicht mehr Teil der Abo-Regel",
                )
            broadcast({"type": "jellyfin_update", **watchlist_payload()})
    finally:
        state.jellyfin_refresh_lock.release()


def refresh_jellyfin_after_download():
    """Fasst parallele Scan-Anforderungen zusammen, ohne eine zu verlieren."""
    with state.jellyfin_refresh_request_lock:
        state.jellyfin_refresh_pending = True
        if state.jellyfin_refresh_running:
            log("Jellyfin-Aktualisierung wurde vorgemerkt.")
            return
        state.jellyfin_refresh_running = True
    try:
        while True:
            with state.jellyfin_refresh_request_lock:
                state.jellyfin_refresh_pending = False
            _refresh_jellyfin_after_download_once()
            with state.jellyfin_refresh_request_lock:
                if state.jellyfin_refresh_pending:
                    continue
                state.jellyfin_refresh_running = False
                return
    except Exception:
        with state.jellyfin_refresh_request_lock:
            state.jellyfin_refresh_running = False
        raise


def on_queue_done():
    with state.queue_lifecycle_lock:
        _on_queue_done_locked()


def _reconcile_idle_queue_state_locked() -> int:
    """Beendet verwaiste Zaehltoken und entfernt alte Gate-Sperrmarker."""
    if (
        state.dl_queue.active_count()
        or state.dl_queue.pending_count()
        or state.queue_prepare_lock.locked()
    ):
        return 0

    with state.queue_claim_lock:
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        claimed = set(state.picked)
        valid_retries = set(state.provider_waiting_jobs) & counted & claimed
        for slug in set(state.provider_waiting_jobs) - valid_retries:
            state.provider_waiting_jobs.pop(slug, None)
        orphaned = counted - valid_retries
        restart_retry_worker = bool(valid_retries) and not state.provider_retry_worker_running

    if restart_retry_worker:
        _ensure_provider_retry_worker()

    for slug in sorted(orphaned):
        movie = state.fp_movies.get(slug)
        label = movie.title if movie is not None else slug
        on_job_done(
            False,
            "Downloadvorbereitung ohne Abschluss beendet",
            label,
            Path(""),
            slug=slug,
        )
    return len(orphaned)


def _on_queue_done_locked():
    # Ein alter Scheduler kann auslaufen, während bereits ein neuer
    # Vorbereitungsjob eingereiht wurde. Dann gehört dieses Done-Ereignis noch
    # nicht zum tatsächlichen Ende der gemeinsamen Auto-Queue.
    if state.dl_queue.active_count() or state.dl_queue.pending_count():
        return
    _reconcile_idle_queue_state_locked()
    # Während eines Provider-Cooldowns noch nicht „fertig" melden: Die offenen
    # Claims werden nach einer einzelnen erfolgreichen Probe fortgesetzt.
    if state.provider_waiting_jobs:
        log("Downloadlauf pausiert – Episoden warten auf den SerienStream-Provider.")
        return
    if state.voe_pool is not None:
        log("Schließe Browser-Pool …")
        try:
            state.voe_pool.close()
        except Exception as exc:
            log(f"Browser-Close Fehler: {exc}", "warn")
        finally:
            state.voe_pool = None
    if state.embed_pool is not None:
        log("Schließe Embed-Pool …")
        try:
            state.embed_pool.close()
        except Exception as exc:
            log(f"Embed-Close Fehler: {exc}", "warn")
        finally:
            state.embed_pool = None
    successful_jobs = len(state.done_slugs)
    failed_jobs = max(0, state.done_jobs - successful_jobs)
    log(f"Downloadlauf beendet: {successful_jobs} erfolgreich, {failed_jobs} fehlgeschlagen.")
    if successful_jobs:
        threading.Thread(target=refresh_jellyfin_after_download, daemon=True).start()
    broadcast({
        "type": "queue_done",
        "done_jobs": state.done_jobs,
        "total_jobs": state.total_jobs,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
    })
    _updater_wake_event.set()


state.dl_queue.on_queue_done = on_queue_done


def _pause_downloads_for_update_restart() -> int:
    """Stoppt die physische Queue, ohne ihre persistenten Claims zu verlieren."""
    with state.queue_lifecycle_lock:
        with state.queue_claim_lock:
            preserved = set(state.picked)
            with state.download_state_lock:
                previous_counted = set(state.counted_queue_slugs)
                # Abbruch-Callbacks dürfen die gespeicherten Slugs nicht als
                # fachlich abgeschlossen verbuchen.
                state.counted_queue_slugs.clear()
            previous_waiting = dict(state.provider_waiting_jobs)
            state.provider_waiting_jobs.clear()
            if not _persist_queue_state():
                with state.download_state_lock:
                    state.counted_queue_slugs.update(previous_counted)
                state.provider_waiting_jobs.update(previous_waiting)
                raise RuntimeError(
                    "Queue-Zustand konnte vor dem Update nicht gesichert werden."
                )
        state.dl_queue.cancel_all()

    # Laufende yt-dlp-Prozesse und Browser-Tabs möglichst sauber beenden, bevor
    # execv den Server ersetzt. Nach spätestens 20 Sekunden übernimmt der
    # Prozessneustart; die Queue-Claims sind zu diesem Zeitpunkt bereits sicher.
    deadline = time.monotonic() + 20
    while state.dl_queue.active_count() and time.monotonic() < deadline:
        time.sleep(0.1)

    if state.hoster_extract_lock.acquire(timeout=10):
        try:
            for attr in ("voe_pool", "embed_pool"):
                pool = getattr(state, attr)
                if pool is None:
                    continue
                try:
                    pool.close()
                except Exception as exc:
                    log(f"Browser-Close vor Update fehlgeschlagen: {exc}", "warn")
                finally:
                    setattr(state, attr, None)
        finally:
            state.hoster_extract_lock.release()
    return len(preserved)


def _canonical_hoster_name(provider_name: str, resolved_url: str) -> str:
    """Bestimmt den Extraktor-Zweig (voe/doodstream/…) aus Provider-Label +
    aufgelöster Domain. VOE nutzt rotierende Mirror-Domains, daher zählt hier
    zuerst das Label."""
    p = (provider_name or "").lower()
    dom = urlparse(resolved_url or "").netloc.lower()
    if "voe" in p or "voe" in dom:
        return "voe"
    if "dood" in p or any(k in dom for k in ("dood", "vide0", "d000d", "d0o0d", "dooood", "ds2play")):
        return "doodstream"
    if "vidara" in p or any(key in dom for key in (
        "vidara", "vidmatrix", "vidchamp", "vidachamp", "vidavaca",
        "viewdara", "thebesthost",
    )):
        return "vidara"
    if "vidsonic" in p or "vidsonic" in dom:
        return "vidsonic"
    if "firestream" in p or "firestream" in dom:
        return "firestream"
    if (
        "fsst" in p or "vidhide" in p or "embed4me" in p or "seekplays" in p
        or any(key in dom for key in (
            "fsst", "incvideo", "kinoger.be", "embed4me", "seekplays",
        ))
    ):
        return "kinoger"
    return p


def _mark_serienstream_blocked(reason: str, error: str = "") -> dict:
    current = state.provider_health.status("serienstream")
    if current["state"] == COOLDOWN and current["remaining_seconds"] > 0:
        return current
    updated = state.provider_health.mark_blocked("serienstream", reason, error)
    minutes = max(1, int((updated["next_probe_at"] - time.time() + 59) // 60))
    label = "erneut blockiert" if int(updated["failure_count"]) > 1 else "Gate erkannt"
    log(f"SerienStream-{label} – Provider für {minutes} Minuten pausiert.", "warn")
    broadcast({"type": "provider_status", "provider": serienstream_provider_status()})
    return updated


def _probe_serienstream_once(item: Optional[dict]) -> bool:
    """Führt genau einen kontrollierten SerienStream-Netzwerkrequest aus."""
    try:
        sto = get_sto_scraper()
        if item is not None:
            movie = item["movie"]
            redirect = next(
                (hoster for hoster in movie.hosters if sto.is_redirect_url(hoster.url)),
                None,
            )
            if redirect is not None:
                with state.sto_lock:
                    sto.reset_gate()
                    target = sto.resolve_play_url(redirect.url, referer=movie.url)
                    if target:
                        state.resolved_link_cache.put(redirect.url, target)
                if not target:
                    _mark_serienstream_blocked(
                        sto.last_block_reason or "captcha_gate", "Provider-Probe blockiert",
                    )
                    return False
                # Das erfolgreiche Probe-Ergebnis wiederverwenden, ohne die
                # Quell-URL im Movie zu verlieren. Ein Download-Retry kann den
                # Cache dadurch gezielt verwerfen und genau einmal neu auflösen.
                item["probe_verified_redirect"] = True
                state.fp_movies[item["slug"]] = movie
                return True
            with state.sto_lock:
                sto.reset_gate()
                movie = _apply_provider_metadata(
                    sto.get_movie(item["slug"]), "serienstream",
                )
            if movie and movie.hosters:
                item["movie"] = movie
                state.fp_movies[item["slug"]] = movie
                return True
            raise RuntimeError("Episodenseite lieferte keine Hoster")
        with state.sto_lock:
            sto.reset_gate()
            html = sto.session.get("https://serienstream.to/", fast=True)
        if not html:
            raise RuntimeError("Leere Provider-Antwort")
        return True
    except ProviderBlockedError as exc:
        _mark_serienstream_blocked(exc.reason, str(exc))
    except Exception as exc:
        _mark_serienstream_blocked("probe_failed", str(exc))
    return False


def _resume_waiting_provider_jobs(first_item: Optional[dict] = None) -> None:
    preferred = first_item
    while state.provider_health.request_allowed("serienstream"):
        with state.queue_claim_lock:
            item = preferred
            preferred = None
            if item is None:
                item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return
            slug = item["slug"]
            state.provider_waiting_jobs.pop(slug, None)
            claimed = slug in state.picked and slug in state.counted_queue_slugs
        if not claimed:
            continue
        try:
            with state.queue_prepare_lock:
                run_download_queue(
                    [(item["movie"], slug)],
                    item["out_root"],
                    movie_fallbacks=item["movie_fallbacks"],
                )
        except Exception as exc:
            log(f"Provider-Retry für «{slug}» fehlgeschlagen: {exc}", "warn")
            _mark_serienstream_blocked("probe_failed", str(exc))
            _defer_provider_episode(
                item["movie"], slug, item["out_root"], item["movie_fallbacks"],
            )
            return


def _execute_provider_probe(item: Optional[dict]) -> None:
    log("SerienStream-Probe gestartet.")
    with state.queue_prepare_lock:
        successful = _probe_serienstream_once(item)
    if not successful:
        return
    state.provider_health.mark_success(
        "serienstream",
        reset_failures=bool(item and item.pop("probe_verified_redirect", False)),
    )
    log("SerienStream-Probe erfolgreich – Provider wieder verfügbar.")
    broadcast({"type": "provider_status", "provider": serienstream_provider_status()})
    _resume_waiting_provider_jobs(item)


def _retry_one_waiting_fallback() -> bool:
    """Prüft genau eine wartende Episode erneut ausschließlich bei Fallbacks.

    SerienStream bleibt dabei im Cooldown und wird von ``run_download_queue``
    nicht angefragt. Das verhindert, dass ein kurzer Huhu-/Moflix-Aussetzer eine
    Episode unnötig bis zur deutlich späteren SerienStream-Probe festhält.
    """
    if not state.queue_prepare_lock.acquire(blocking=False):
        return False
    item = None
    slug = ""
    try:
        if state.provider_health.status("serienstream")["state"] != COOLDOWN:
            return False
        with state.queue_claim_lock:
            item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return False
            slug = item["slug"]
            state.provider_waiting_jobs.pop(slug, None)
            if slug not in state.picked or slug not in state.counted_queue_slugs:
                return False
            state.preparing_queue_slugs.add(slug)
            _update_queue_job(slug, persist=False, status="preparing")
        parsed = parse_episode_slug(slug)
        label = (
            f"S{parsed[1]:02d}E{parsed[2]:02d}" if parsed else slug
        )
        log(f"Fallback wird kontrolliert erneut geprüft: {label}.")
        broadcast({"type": "queue_update", "queue": build_queue_payload()})
        run_download_queue(
            [(item["movie"], slug)],
            item["out_root"],
            movie_fallbacks=item["movie_fallbacks"],
        )
        return True
    except Exception as exc:
        log(f"Fallback-Wiederholung für «{slug}» fehlgeschlagen: {exc}", "warn")
        if item is not None and slug:
            _defer_provider_episode(
                item["movie"], slug, item["out_root"], item["movie_fallbacks"],
            )
        return True
    finally:
        if slug:
            with state.queue_claim_lock:
                state.preparing_queue_slugs.discard(slug)
            broadcast({"type": "queue_update", "queue": build_queue_payload()})
        state.queue_prepare_lock.release()


def _provider_retry_worker() -> None:
    next_fallback_retry = time.monotonic() + appconfig.SERIES_FALLBACK_RETRY_SECONDS
    try:
        while True:
            with state.queue_claim_lock:
                item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return
            status = state.provider_health.status("serienstream")
            if status["state"] == HEALTHY:
                _resume_waiting_provider_jobs()
                continue
            if status["state"] == PROBING:
                state.provider_retry_wake_event.wait(1)
                state.provider_retry_wake_event.clear()
                continue
            if status["remaining_seconds"] > 0:
                delay = max(0.0, next_fallback_retry - time.monotonic())
                if delay <= 0:
                    if _retry_one_waiting_fallback():
                        next_fallback_retry = (
                            time.monotonic() + appconfig.SERIES_FALLBACK_RETRY_SECONDS
                        )
                    else:
                        # Eine normale Episodenvorbereitung hat Vorrang. Kurz
                        # danach erneut versuchen, ohne im Sekundentakt zu loggen.
                        next_fallback_retry = time.monotonic() + 5
                    continue
                state.provider_retry_wake_event.wait(min(
                    30, status["remaining_seconds"], delay,
                ))
                state.provider_retry_wake_event.clear()
                continue
            if state.provider_health.begin_probe("serienstream"):
                _execute_provider_probe(item)
            else:
                state.provider_retry_wake_event.wait(1)
                state.provider_retry_wake_event.clear()
    finally:
        with state.queue_claim_lock:
            state.provider_retry_worker_running = False
            restart = bool(state.provider_waiting_jobs)
        if restart:
            _ensure_provider_retry_worker()


def _ensure_provider_retry_worker() -> None:
    with state.queue_claim_lock:
        if state.provider_retry_worker_running or not state.provider_waiting_jobs:
            return
        state.provider_retry_worker_running = True
    threading.Thread(target=_provider_retry_worker, daemon=True).start()


def _defer_provider_episode(
    movie: FilmpalastMovie,
    slug: str,
    out_root: Path,
    movie_fallbacks: Optional[Dict[str, List[FilmpalastMovie]]] = None,
) -> bool:
    """Behält eine Episode bis zur nächsten einzelnen Provider-Probe offen."""
    with state.queue_claim_lock:
        if slug not in state.picked or slug not in state.counted_queue_slugs:
            return False
        state.provider_waiting_jobs[slug] = {
            "movie": movie,
            "slug": slug,
            "out_root": Path(out_root),
            "movie_fallbacks": movie_fallbacks,
        }
        _update_queue_job(
            slug,
            persist=False,
            status="waiting_provider",
            next_retry_at=state.provider_health.next_probe_at("serienstream"),
        )
    _persist_queue_state()
    broadcast({"type": "queue_update", "queue": build_queue_payload()})
    _ensure_provider_retry_worker()
    return True


def _episode_fallback_aliases(movie_slug: str, title: str) -> tuple[str, ...]:
    """Liefert alternative Katalogtitel fuer eine Episode.

    serienstream zeigt haeufig den deutschen Titel, waehrend ein Backup den
    Originaltitel fuehrt. Der Serien-Slug, Watchlist-Aliase und TMDB schliessen
    diese Luecke, ohne unscharfe Episodenmatches zuzulassen.
    """
    values: List[str] = []
    parsed = parse_episode_slug(movie_slug)
    base_slug = parsed[0] if parsed else movie_slug
    slug_title = _series_search_title(base_slug)
    if slug_title:
        values.append(slug_title)

    tmdb_id = ""
    with state.watchlist_lock:
        entry = watchlist_lookup(base_slug)
        if entry:
            tmdb_id = str(entry.get("tmdb_id") or "")
            values.append(str(entry.get("title") or ""))
            values.extend(str(value or "") for value in entry.get("aliases") or [])
    try:
        tmdb = get_tmdb_series(title, tmdb_id)
    except Exception as exc:
        log(f"  TMDB-Aliase fuer Serien-Fallback nicht ladbar: {exc}", "warn")
        tmdb = None
    if tmdb:
        values.extend((
            str(tmdb.get("title") or ""),
            str(tmdb.get("original_title") or ""),
        ))

    seen = {_norm_title(title)}
    aliases: List[str] = []
    for value in values:
        value = " ".join(value.split()).strip()
        key = _norm_title(value)
        if not key or key in seen:
            continue
        seen.add(key)
        aliases.append(value)
    return tuple(aliases)


def _fallback_get_series(
    provider: str, title: str, tmdb_id: str = "",
) -> Optional[FilmpalastSeries]:
    """Sucht die Serie «title» beim Fallback-Anbieter per Titel-Match und lädt sie.
    Ergebnis (auch None) wird pro Download-Lauf gecacht, damit nicht jede Episode
    denselben Anbieter erneut durchsucht."""
    exact_tmdb_id = str(tmdb_id or "").strip() if provider == "huhu" else ""
    if exact_tmdb_id and not exact_tmdb_id.isdigit():
        exact_tmdb_id = ""
    key = (
        f"{provider}:tmdb:{exact_tmdb_id}"
        if exact_tmdb_id else f"{provider}:{_norm_title(title)}"
    )
    now = time.time()
    with state.fallback_series_cache_lock:
        provider_error = state.fallback_provider_errors.get(provider)
        if provider_error and provider_error[0] > now:
            return None
        state.fallback_provider_errors.pop(provider, None)
        cached = state.fallback_series_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        state.fallback_series_cache.pop(key, None)
    series: Optional[FilmpalastSeries] = None
    matched = False
    try:
        if exact_tmdb_id:
            matched = True
            series = _load_series_for_provider(
                provider, f"{HUHU_PREFIX}{exact_tmdb_id}:tmdb",
            )
        else:
            results = _search_series_for_provider(provider, title)
            wanted = _norm_title(title)
            best = next(
                (result for result in results if _norm_title(result.title) == wanted),
                None,
            )
            matched = best is not None
            series = _load_series_for_provider(provider, best.sample_slug) if best else None
    except Exception as exc:
        label = PROVIDER_LABELS.get(provider, provider)
        log(f"  {label}-Fallback-Suche vorübergehend nicht erreichbar: {exc}", "warn")
        # Netzwerk-/Cloudflare-Fehler sind kein bestaetigtes "nicht vorhanden".
        # Nur eine kurze providerweite Sperre verhindert, dass derselbe Fehler
        # fuer jeden Alias und jede Episode sofort erneut ausgelöst wird.
        with state.fallback_series_cache_lock:
            state.fallback_provider_errors[provider] = (
                now + appconfig.SERIES_PROVIDER_TRANSIENT_ERROR_TTL_SECONDS,
                str(exc),
            )
        return None
    with state.fallback_series_cache_lock:
        state.fallback_provider_errors.pop(provider, None)
    if series and not series.seasons:
        return None
    if matched and series is None:
        # Treffer vorhanden, Detailseite aber temporaer nicht ladbar.
        return None
    with state.fallback_series_cache_lock:
        state.fallback_series_cache[key] = (
            now + appconfig.SERIES_PROVIDER_FALLBACK_CACHE_TTL_SECONDS,
            series,
        )
    return series


# Nur als überschreibbarer Kompatibilitätspunkt für bestehende Integrationen;
# None bedeutet: immer die live konfigurierte Reihenfolge verwenden.
SERIES_FALLBACK_PROVIDERS: Optional[tuple[str, ...]] = None


def find_episode_fallbacks(
    title: str,
    season: int,
    episode: int,
    aliases: tuple[str, ...] = (),
    source_slug: str = "",
    excluded_providers: Optional[set[str]] = None,
    limit: int = 0,
) -> List[FilmpalastMovie]:
    """Lädt dieselbe Episode bei allen passenden Fallback-Katalogen.

    ``limit=1`` startet den ersten exakten Treffer sofort. Weitere Kataloge
    werden erst bei einem Laufzeitfehler dieses Treffers nachgeladen; so hält
    ein langsamer oder gesperrter späterer Anbieter den Download nicht auf.
    """
    movies: List[FilmpalastMovie] = []
    seen_urls: set[str] = set()
    search_titles: List[str] = []
    seen_titles: set[str] = set()
    for candidate in (title, *aliases):
        candidate = " ".join(str(candidate or "").split()).strip()
        key = _norm_title(candidate)
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        search_titles.append(candidate)

    source_provider = provider_for_value(source_slug) if source_slug else ""
    skipped_providers = {
        str(provider or "").strip().casefold()
        for provider in (excluded_providers or set())
        if str(provider or "").strip()
    }
    tmdb_id = ""
    parsed_source = parse_episode_slug(source_slug)
    source_base_slug = parsed_source[0] if parsed_source else source_slug
    with state.watchlist_lock:
        watch_entry = watchlist_lookup(source_base_slug)
        if watch_entry:
            tmdb_id = str(watch_entry.get("tmdb_id") or "").strip()
    fallback_providers = backend_value("SERIES_FALLBACK_PROVIDERS") or tuple(
        provider_priority("series")
    )
    searched_labels = [
        PROVIDER_LABELS.get(provider, provider)
        for provider in fallback_providers
        if provider != source_provider
    ]
    if searched_labels:
        log(
            f"  Fallback-Suche S{season:02d}E{episode:02d}: "
            + " → ".join(searched_labels)
        )
    for provider in fallback_providers:
        if provider == source_provider or provider in skipped_providers:
            continue
        series = None
        for search_title in search_titles:
            series = _fallback_get_series(provider, search_title, tmdb_id=tmdb_id)
            if series:
                break
        if not series:
            continue
        ep = next((e for e in series.seasons.get(season, []) if e.episode == episode), None)
        if not ep:
            label = PROVIDER_LABELS.get(provider, provider)
            log(f"  {label}: S{season:02d}E{episode:02d} nicht im Katalog", "warn")
            continue
        label = PROVIDER_LABELS.get(provider, provider)
        log(f"  → Fallback {label}: S{season:02d}E{episode:02d} gefunden, lade Hoster …")
        try:
            movie = load_movie_for_slug(ep.slug)
        except Exception as exc:
            log(f"  {label}-Fallback Laden fehlgeschlagen: {exc}", "warn")
            movie = None
        if movie and movie.hosters and movie.url not in seen_urls:
            seen_urls.add(movie.url)
            movies.append(movie)
            if limit > 0 and len(movies) >= limit:
                break
            continue
        log(f"  {label}: keine nutzbaren Hoster für die Episode", "warn")
    return movies


_SERVICE_EXPORTS = (
    "on_job_progress",
    "_failure_record",
    "_watchlist_retry_allowed",
    "on_job_done",
    "_refresh_jellyfin_after_download_once",
    "refresh_jellyfin_after_download",
    "on_queue_done",
    "_reconcile_idle_queue_state_locked",
    "_on_queue_done_locked",
    "_pause_downloads_for_update_restart",
    "_canonical_hoster_name",
    "_mark_serienstream_blocked",
    "_probe_serienstream_once",
    "_resume_waiting_provider_jobs",
    "_execute_provider_probe",
    "_retry_one_waiting_fallback",
    "_provider_retry_worker",
    "_ensure_provider_retry_worker",
    "_defer_provider_episode",
    "_episode_fallback_aliases",
    "_fallback_get_series",
    "SERIES_FALLBACK_PROVIDERS",
    "find_episode_fallbacks",
)
publish_service(globals(), _SERVICE_EXPORTS)
