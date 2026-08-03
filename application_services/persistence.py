"""Persistent snapshots, queue identity, and client payload services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


def queue_group_name(slug: str) -> str:
    parsed = parse_episode_slug(slug)
    if not parsed:
        return "Filme"
    movie = state.fp_movies.get(slug)
    if movie and movie.title:
        stripped = strip_episode_suffix(movie.title)
        if stripped:
            return stripped
    return parsed[0]


def queue_content_key(slug: str, movie: Optional[FilmpalastMovie] = None) -> str:
    """Provider-unabhängiger Schlüssel gegen doppelte logische Downloads."""
    movie = movie or state.fp_movies.get(slug)
    if movie is None:
        return ""
    parsed = parse_episode_slug(slug)
    if parsed:
        base_slug, season, episode = parsed
        title = strip_episode_suffix(movie.title) or movie.title
        with state.watchlist_lock:
            entry = watchlist_lookup(base_slug)
            tmdb_id = str((entry or {}).get("tmdb_id") or "")
        if not tmdb_id:
            tmdb = get_tmdb_series(title)
            tmdb_id = str((tmdb or {}).get("tmdb_id") or "")
        identity = f"tmdb:{tmdb_id}" if tmdb_id else f"title:{_norm_title(title)}"
        return f"series:{identity}:s{season}:e{episode}"
    title = clean_movie_title(movie.title)
    tmdb = get_tmdb_client().movie_summary(title, movie.year)
    tmdb_id = str((tmdb or {}).get("tmdb_id") or "")
    identity = f"tmdb:{tmdb_id}" if tmdb_id else f"title:{_norm_title(title)}:{movie.year or ''}"
    return f"movie:{identity}"


def episode_sort_key(slug: str):
    parsed = parse_episode_slug(slug)
    return (parsed[1], parsed[2]) if parsed else (0, 0)


PERSISTENCE_RETRY_DELAYS = (1, 5, 15, 30, 60)


def _persistence_saver(resource: str):
    return {
        "queue": appconfig.save_queue,
        "watchlist": appconfig.save_watchlist,
        "movie_subscriptions": appconfig.save_movie_subscriptions,
    }[resource]


def _persistence_status(resource: str) -> dict:
    with state.persistence_status_lock:
        error = dict(state.persistence_errors.get(resource) or {})
        pending = resource in state.persistence_pending
    return {
        "ok": not error,
        "pending_retry": pending,
        "attempts": int(error.get("attempts") or 0),
        "last_failed_at": float(error.get("last_failed_at") or 0),
        "next_retry_at": float(error.get("next_retry_at") or 0),
    }


def _mark_persistence_success(resource: str) -> None:
    with state.persistence_status_lock:
        state.persistence_pending.pop(resource, None)
        state.persistence_errors.pop(resource, None)


def _mark_persistence_failure(resource: str, *, pending: bool) -> None:
    now = time.time()
    with state.persistence_status_lock:
        previous = state.persistence_errors.get(resource) or {}
        attempts = int(previous.get("attempts") or 0) + 1
        delay = PERSISTENCE_RETRY_DELAYS[
            min(attempts - 1, len(PERSISTENCE_RETRY_DELAYS) - 1)
        ] if pending else 0
        state.persistence_errors[resource] = {
            "attempts": attempts,
            "last_failed_at": now,
            "next_retry_at": now + delay if pending else 0,
        }


def _write_persistent_snapshot(resource: str, snapshot) -> bool:
    with state.persistence_write_locks[resource]:
        try:
            saved = bool(_persistence_saver(resource)(snapshot))
        except Exception as exc:
            log(f"{resource}: Persistenzfehler: {exc}", "warn")
            saved = False
    if saved:
        _mark_persistence_success(resource)
    return saved


def _retry_persistence_once(resource: str) -> bool:
    with state.persistence_status_lock:
        pending = state.persistence_pending.get(resource)
        if pending is None:
            return True
        generation = int(pending["generation"])
        snapshot = deepcopy(pending["snapshot"])
    with state.persistence_write_locks[resource]:
        # Ein neuerer API-/Worker-Commit darf nie durch einen alten Retry
        # überschrieben werden.
        with state.persistence_status_lock:
            current = state.persistence_pending.get(resource)
            if current is None or int(current["generation"]) != generation:
                return False
        try:
            saved = bool(_persistence_saver(resource)(snapshot))
        except Exception as exc:
            log(f"{resource}: Persistenz-Retry fehlgeschlagen: {exc}", "warn")
            saved = False
    if saved:
        with state.persistence_status_lock:
            current = state.persistence_pending.get(resource)
            if current is not None and int(current["generation"]) == generation:
                state.persistence_pending.pop(resource, None)
                state.persistence_errors.pop(resource, None)
        return True
    _mark_persistence_failure(resource, pending=True)
    return False


def _persistence_retry_loop(resource: str) -> None:
    try:
        while True:
            with state.persistence_status_lock:
                pending = state.persistence_pending.get(resource)
                if pending is None:
                    return
                retry_at = float(
                    (state.persistence_errors.get(resource) or {}).get("next_retry_at")
                    or time.time()
                )
            time.sleep(max(0.05, retry_at - time.time()))
            _retry_persistence_once(resource)
    finally:
        with state.persistence_status_lock:
            state.persistence_retrying.discard(resource)
            restart = resource in state.persistence_pending
            if restart:
                state.persistence_retrying.add(resource)
        if restart:
            threading.Thread(
                target=_persistence_retry_loop,
                args=(resource,),
                name=f"persistence-retry-{resource}",
                daemon=True,
            ).start()


def _schedule_persistence_retry(resource: str, snapshot) -> None:
    with state.persistence_status_lock:
        generation = int(state.persistence_generations.get(resource) or 0) + 1
        state.persistence_generations[resource] = generation
        state.persistence_pending[resource] = {
            "generation": generation,
            "snapshot": deepcopy(snapshot),
        }
        should_start = resource not in state.persistence_retrying
        if should_start:
            state.persistence_retrying.add(resource)
    _mark_persistence_failure(resource, pending=True)
    if should_start:
        threading.Thread(
            target=_persistence_retry_loop,
            args=(resource,),
            name=f"persistence-retry-{resource}",
            daemon=True,
        ).start()


def _persist_background_snapshot(resource: str, snapshot) -> bool:
    if _write_persistent_snapshot(resource, snapshot):
        return True
    _schedule_persistence_retry(resource, snapshot)
    log(
        f"{resource}: Zustand konnte nicht gespeichert werden; Retry vorgemerkt.",
        "warn",
    )
    return False


def _persistence_unavailable(resource: str) -> HTTPException:
    _mark_persistence_failure(resource, pending=False)
    return HTTPException(
        503,
        detail={
            "code": "state_persistence_failed",
            "resource": resource,
            "message": "Die Änderung konnte nicht dauerhaft gespeichert werden.",
        },
        headers={"Retry-After": "5"},
    )


def _require_persistent_snapshot(resource: str, snapshot) -> None:
    if not _write_persistent_snapshot(resource, snapshot):
        raise _persistence_unavailable(resource)


def _persist_watchlist_background() -> bool:
    with state.watchlist_lock:
        snapshot = deepcopy(state.watchlist)
    return _persist_background_snapshot("watchlist", snapshot)


def _persist_movie_subscriptions_background() -> bool:
    with state.movie_subscriptions_lock:
        snapshot = deepcopy(state.movie_subscriptions)
    return _persist_background_snapshot("movie_subscriptions", snapshot)


def _persist_queue_state() -> bool:
    with state.queue_claim_lock:
        snapshot = _queue_state_snapshot()
    # File I/O is deliberately outside the queue lock. Monotonic snapshot
    # revisions prevent a delayed older writer from replacing newer state.
    return _persist_background_snapshot("queue", snapshot)


def _queue_state_snapshot(
    *,
    active_jobs: Optional[List[dict]] = None,
    history: Optional[List[dict]] = None,
) -> dict:
    """Return one transaction containing active jobs and terminal history."""
    with state.queue_claim_lock:
        state.queue_persistence_revision = int(state.queue_persistence_revision) + 1
        if active_jobs is None:
            active_jobs = [
                job for job in state.queue_jobs.values()
                if job.get("slug") in state.picked
            ]
        if history is None:
            history = state.queue_history
        return {
            "schema_version": 2,
            "revision": state.queue_persistence_revision,
            "jobs": deepcopy(active_jobs),
            "history": deepcopy(list(history)[:HISTORY_LIMIT]),
        }


def _queue_job_for_slug(slug: str) -> Optional[dict]:
    with state.queue_claim_lock:
        job_id = state.queue_job_by_slug.get(str(slug))
        return state.queue_jobs.get(job_id) if job_id else None


def _queue_job_for_id(job_id: str, *, include_history: bool = False) -> Optional[dict]:
    with state.queue_claim_lock:
        job = state.queue_jobs.get(str(job_id))
        if job is not None or not include_history:
            return job
        return next(
            (item for item in state.queue_history if item.get("job_id") == str(job_id)),
            None,
        )


def _ensure_queue_job(slug: str, movie=None, *, job_id: str = "") -> dict:
    """Create a logical identity once; provider/hoster retries reuse it."""
    slug = str(slug)
    with state.queue_claim_lock:
        existing_id = state.queue_job_by_slug.get(slug)
        if existing_id and existing_id in state.queue_jobs:
            job = state.queue_jobs[existing_id]
            if movie is not None and (
                not job.get("title") or job.get("title") == slug
            ):
                job["title"] = str(getattr(movie, "title", "") or slug)
            return job
        job = new_job(
            slug,
            job_id=job_id or None,
            title=str(getattr(movie, "title", "") or slug),
        )
        state.queue_jobs[job["job_id"]] = job
        state.queue_job_by_slug[slug] = job["job_id"]
        return job


def _update_queue_job(slug: str, *, persist: bool = True, **changes) -> Optional[dict]:
    with state.queue_claim_lock:
        job = _queue_job_for_slug(slug)
        if job is None:
            job = _ensure_queue_job(slug, state.fp_movies.get(slug))
        for key, value in changes.items():
            if key in job and value is not None:
                job[key] = value
        snapshot = deepcopy(job)
    if persist and not _persist_queue_state():
        log(f"Queue-Job {job['job_id']} konnte nicht gespeichert werden.", "warn")
    return snapshot


def _terminal_queue_job(
    slug: str,
    status: str,
    *,
    error: str = "",
    final_path: str = "",
    persist: bool = True,
) -> Optional[dict]:
    with state.queue_claim_lock:
        job_id = state.queue_job_by_slug.pop(str(slug), "")
        job = state.queue_jobs.pop(job_id, None) if job_id else None
        state.queue_job_persist_times.pop(str(slug), None)
        if job is None:
            return None
        job["status"] = status
        job["completed_at"] = time.time()
        job["error"] = str(error or "")[:500]
        job["final_path"] = str(final_path or "")
        if status == "completed":
            job["progress"] = 100.0
        state.queue_history = [
            item for item in state.queue_history if item.get("job_id") != job_id
        ]
        state.queue_history.insert(0, job)
        del state.queue_history[HISTORY_LIMIT:]
        snapshot = deepcopy(job)
    if persist and not _persist_queue_state():
        log(f"Terminaler Queue-Job {job_id} konnte nicht gespeichert werden.", "warn")
    return snapshot


def _queue_terminal_snapshot(
    slug: str,
    status: str,
    *,
    error: str = "",
    final_path: str = "",
) -> tuple[dict, Optional[dict]]:
    """Build a durable terminal transition before worker state is changed."""
    with state.queue_claim_lock:
        job = _queue_job_for_slug(slug)
        if job is None:
            return _queue_state_snapshot(), None
        terminal = deepcopy(job)
        terminal.update({
            "status": status,
            "completed_at": time.time(),
            "error": str(error or "")[:500],
            "final_path": str(final_path or ""),
        })
        if status == "completed":
            terminal["progress"] = 100.0
        active = [
            deepcopy(item) for item in state.queue_jobs.values()
            if item.get("job_id") != terminal["job_id"]
        ]
        history = [terminal] + [
            deepcopy(item) for item in state.queue_history
            if item.get("job_id") != terminal["job_id"]
        ]
        return _queue_state_snapshot(active_jobs=active, history=history), terminal


def _apply_terminal_queue_job(terminal: dict) -> None:
    with state.queue_claim_lock:
        job_id = str(terminal.get("job_id") or "")
        slug = str(terminal.get("slug") or "")
        state.queue_jobs.pop(job_id, None)
        if state.queue_job_by_slug.get(slug) == job_id:
            state.queue_job_by_slug.pop(slug, None)
        state.queue_job_persist_times.pop(slug, None)
        state.queue_history = [
            deepcopy(terminal),
            *(
                item for item in state.queue_history
                if item.get("job_id") != job_id
            ),
        ][:HISTORY_LIMIT]


def _retry_queue_job(job_id: str) -> Optional[dict]:
    """Move one failed/cancelled history record back to the active queue."""
    with state.queue_claim_lock:
        index = next(
            (i for i, item in enumerate(state.queue_history) if item.get("job_id") == job_id),
            None,
        )
        if index is None:
            return None
        job = state.queue_history[index]
        if job.get("status") not in {"failed", "cancelled"}:
            return None
        slug = str(job.get("slug") or "")
        if not slug or slug in state.queue_job_by_slug:
            return None
        state.queue_history.pop(index)
        job.update({
            "status": "queued",
            "started_at": 0.0,
            "completed_at": 0.0,
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "speed_bps": 0.0,
            "eta_seconds": None,
            "error": "",
            "next_retry_at": 0.0,
            "final_path": "",
        })
        state.queue_jobs[job_id] = job
        state.queue_job_by_slug[slug] = job_id
        state.picked.add(slug)
        return deepcopy(job)


def queue_jobs_payload() -> dict:
    with state.queue_claim_lock:
        jobs = deepcopy([
            job for job in state.queue_jobs.values()
            if job.get("slug") in state.picked
        ])
    return {"count": len(jobs), "jobs": jobs}


def queue_history_payload() -> dict:
    with state.queue_claim_lock:
        history = deepcopy(state.queue_history)
    return {"count": len(history), "limit": HISTORY_LIMIT, "jobs": history}


def _persist_new_queue_claims(slugs) -> bool:
    """Persistiert neue Claims oder gibt sie frei, bevor Jobs starten dürfen."""
    claimed = set(slugs)
    if not claimed or _persist_queue_state():
        return True
    with state.queue_claim_lock:
        state.picked.difference_update(claimed)
        state.preparing_queue_slugs.difference_update(claimed)
        for slug in claimed:
            state.provider_waiting_jobs.pop(slug, None)
            job_id = state.queue_job_by_slug.pop(slug, "")
            if job_id:
                state.queue_jobs.pop(job_id, None)
    # Der erste Fehlversuch enthielt noch die neuen Claims. Der Retry-Snapshot
    # muss deshalb sofort durch den zurückgerollten Zustand ersetzt werden.
    _persist_queue_state()
    return False


def _queue_slug_claimed(slug: str) -> bool:
    with state.queue_claim_lock:
        return slug in state.picked


def serienstream_provider_status() -> dict:
    active_jobs = state.dl_queue.active_jobs()
    pending_jobs = (
        state.dl_queue.pending_jobs()
        if hasattr(state.dl_queue, "pending_jobs") else []
    )
    active_download_slugs = {
        slug
        for job in active_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    pending_download_slugs = {
        slug
        for job in pending_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    download_slugs = active_download_slugs | pending_download_slugs
    with state.queue_claim_lock:
        claimed = set(state.picked)
        waiting_slugs = set(state.provider_waiting_jobs) & claimed
        preparing_slugs = set(state.preparing_queue_slugs) & claimed
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        fallback_slugs = {
            slug for slug in claimed & counted
            if slug not in waiting_slugs
            and slug not in download_slugs
            and parse_episode_slug(slug) is not None
            and provider_for_value(slug) == "serienstream"
        }
    status = state.provider_health.status(
        "serienstream", waiting_episode_count=len(waiting_slugs),
    )
    status["fallback_episode_count"] = len(fallback_slugs)
    status["checking_episode_count"] = len(fallback_slugs & preparing_slugs)
    status["queued_fallback_episode_count"] = len(fallback_slugs - preparing_slugs)
    status["active_fallback_download_count"] = sum(
        parse_episode_slug(slug) is not None
        and provider_for_value(slug) == "serienstream"
        for slug in active_download_slugs & claimed
    )
    status["ready_fallback_download_count"] = sum(
        parse_episode_slug(slug) is not None
        and provider_for_value(slug) == "serienstream"
        for slug in pending_download_slugs & claimed
    )
    status["cached_redirect_count"] = state.resolved_link_cache.count()
    return status


def build_queue_payload() -> dict:
    with state.queue_claim_lock:
        slugs = [
            job["slug"] for job in state.queue_jobs.values()
            if job.get("slug") in state.picked
        ]
        slugs.extend(sorted(set(state.picked) - set(slugs)))
        jobs_snapshot = deepcopy([
            job for job in state.queue_jobs.values()
            if job.get("slug") in state.picked
        ])
    if not slugs:
        return {
            "count": 0,
            "jobs": [],
            "groups": [],
            "providers": {"serienstream": serienstream_provider_status()},
            "persistence": _persistence_status("queue"),
            "activity": {
                "active_preparations": 0,
                "pending_preparations": 0,
                "active_downloads": state.dl_queue.active_count(),
                "pending_downloads": 0,
            },
        }
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for slug in slugs:
        groups.setdefault(queue_group_name(slug), []).append(slug)
    active_jobs = state.dl_queue.active_jobs()
    pending_jobs = (
        state.dl_queue.pending_jobs()
        if hasattr(state.dl_queue, "pending_jobs") else []
    )
    active_download_slugs = {
        slug
        for job in active_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    pending_download_slugs = {
        slug
        for job in pending_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    with state.queue_claim_lock:
        preparing_slugs = set(state.preparing_queue_slugs)
    result_groups = []
    provider_status = serienstream_provider_status()
    serienstream_paused = provider_status.get("state") != HEALTHY
    for name, gslugs in groups.items():
        items = []
        for slug in gslugs:
            movie = state.fp_movies.get(slug)
            title = movie.title if movie else slug
            label = state.hoster_intel.best_label(movie.hosters) if movie and movie.hosters else "—"
            provider = _movie_provider(movie, slug)
            waiting_provider = slug in state.provider_waiting_jobs
            preparing_source = (
                not waiting_provider
                and slug in preparing_slugs
                and slug in state.counted_queue_slugs
            )
            checking_fallback = (
                serienstream_paused
                and preparing_source
                and parse_episode_slug(slug) is not None
                and provider_for_value(slug) == "serienstream"
            )
            queued_fallback = (
                serienstream_paused
                and not waiting_provider
                and not checking_fallback
                and slug not in active_download_slugs
                and slug not in pending_download_slugs
                and parse_episode_slug(slug) is not None
                and provider_for_value(slug) == "serienstream"
                and slug in state.counted_queue_slugs
            )
            logical_job = _queue_job_for_slug(slug) or {}
            derived_status = (
                "downloading" if slug in active_download_slugs
                else "queued" if slug in pending_download_slugs
                else "waiting_provider" if waiting_provider
                else "preparing" if (checking_fallback or preparing_source)
                else "queued"
            )
            items.append({
                **deepcopy(logical_job),
                "slug": slug, "title": title, "hoster_label": label,
                "provider": provider,
                "content_language": _movie_content_language(movie, fallback=slug),
                "done": slug in state.done_slugs,
                "job_status": derived_status,
                "status": (
                    "downloading" if slug in active_download_slugs
                    else "download_ready" if slug in pending_download_slugs
                    else "waiting_provider" if waiting_provider
                    else "checking_fallback" if checking_fallback
                    else "preparing_source" if preparing_source
                    else "queued_fallback" if queued_fallback
                    else "waiting"
                ),
                "next_probe_at": (
                    state.provider_health.next_probe_at("serienstream")
                    if waiting_provider else 0
                ),
            })
        result_groups.append({"name": name, "items": items})
    return {
        "count": len(slugs),
        "jobs": jobs_snapshot,
        "groups": result_groups,
        "providers": {"serienstream": provider_status},
        "persistence": _persistence_status("queue"),
        "activity": {
            # Auch der separate kontrollierte Fallback-Retry ist eine aktive
            # Vorbereitung, obwohl er nicht als DownloadQueue-Job läuft.
            "active_preparations": len(preparing_slugs & set(slugs)),
            "pending_preparations": sum(
                bool(getattr(job, "is_preparation_job", False)) for job in pending_jobs
            ),
            "active_downloads": len(active_download_slugs),
            "pending_downloads": len(pending_download_slugs),
        },
    }


def watchlist_payload() -> dict:
    items = []
    with state.queue_claim_lock, state.watchlist_lock:
        for w in state.watchlist:
            pending = set(state.watchlist_new_slugs.get(w["base_slug"], set()))
            queued_count = len(pending & state.picked)
            failures = w.get("failed_downloads") if isinstance(w.get("failed_downloads"), dict) else {}
            failed_count = len(set(failures) & pending)
            mode = normalize_watch_mode(w.get("download_mode"))
            cleanup_mode = normalize_cleanup_mode(w.get("cleanup_mode"))
            error = str(w.get("last_error") or "")
            if error:
                status = "blocked"
            elif failed_count:
                status = "failed"
            elif queued_count:
                status = "queued"
            elif pending and state.automation.get("auto_download") and not is_within_download_window():
                status = "waiting_window"
            elif pending:
                status = "missing"
            else:
                status = "current"
            items.append({
                **w,
                "download_mode": mode,
                "download_mode_label": WATCH_MODE_LABELS[mode],
                "cleanup_mode": cleanup_mode,
                "cleanup_mode_label": CLEANUP_MODE_LABELS[cleanup_mode],
                "cleanup_mode_ready": (
                    cleanup_mode == CLEANUP_MODE_KEEP
                    or bool(
                        state.jellyfin_cfg.get("url", "").strip()
                        and state.jellyfin_cfg.get("api_key", "").strip()
                        and state.jellyfin_cfg.get("user_id", "").strip()
                        and state.jellyfin_user_episodes_available
                        and not str(w.get("cleanup_last_error") or "")
                    )
                ),
                "download_mode_ready": (
                    mode != WATCH_MODE_NEXT_SEASON
                    or bool(
                        state.jellyfin_cfg.get("url", "").strip()
                        and state.jellyfin_cfg.get("api_key", "").strip()
                        and state.jellyfin_cfg.get("user_id", "").strip()
                        and state.jellyfin_user_episodes_available
                        and not error
                    )
                ),
                "new_count": len(pending),
                "queued_count": queued_count,
                "failed_count": failed_count,
                "status": status,
            })
    return {
        "watchlist": items,
        "persistence": _persistence_status("watchlist"),
    }


def hydrate_watchlist_artwork() -> None:
    """Ergänzt Bilder alter Abo-Einträge unabhängig von Jellyfin-Prüfungen."""
    if not get_tmdb_client().configured:
        return
    with state.watchlist_lock:
        missing = [
            {
                "base_slug": str(entry.get("base_slug") or ""),
                "title": str(entry.get("title") or ""),
                "tmdb_id": entry.get("tmdb_id") or "",
            }
            for entry in state.watchlist
            if not entry.get("backdrop_url") or not entry.get("cover_url")
        ]
    if not missing:
        return

    artwork = {}
    for item in missing:
        metadata = get_tmdb_series(item["title"], item["tmdb_id"])
        if not metadata:
            continue
        artwork[item["base_slug"]] = {
            "tmdb_id": metadata.get("tmdb_id"),
            "cover_url": metadata.get("cover_url") or "",
            "backdrop_url": metadata.get("backdrop_url") or "",
        }

    changed = False
    with state.watchlist_lock:
        for entry in state.watchlist:
            images = artwork.get(str(entry.get("base_slug") or ""))
            if not images:
                continue
            for field in ("tmdb_id", "cover_url", "backdrop_url"):
                if not entry.get(field) and images.get(field):
                    entry[field] = images[field]
                    changed = True
        if changed:
            _persist_watchlist_background()


_SERVICE_EXPORTS = (
    "queue_group_name",
    "queue_content_key",
    "episode_sort_key",
    "PERSISTENCE_RETRY_DELAYS",
    "_persistence_saver",
    "_persistence_status",
    "_mark_persistence_success",
    "_mark_persistence_failure",
    "_write_persistent_snapshot",
    "_retry_persistence_once",
    "_persistence_retry_loop",
    "_schedule_persistence_retry",
    "_persist_background_snapshot",
    "_persistence_unavailable",
    "_require_persistent_snapshot",
    "_persist_watchlist_background",
    "_persist_movie_subscriptions_background",
    "_persist_queue_state",
    "_queue_state_snapshot",
    "_queue_job_for_slug",
    "_queue_job_for_id",
    "_ensure_queue_job",
    "_update_queue_job",
    "_terminal_queue_job",
    "_queue_terminal_snapshot",
    "_apply_terminal_queue_job",
    "_retry_queue_job",
    "queue_jobs_payload",
    "queue_history_payload",
    "_persist_new_queue_claims",
    "_queue_slug_claimed",
    "serienstream_provider_status",
    "build_queue_payload",
    "watchlist_payload",
    "hydrate_watchlist_artwork",
)
publish_service(globals(), _SERVICE_EXPORTS)
