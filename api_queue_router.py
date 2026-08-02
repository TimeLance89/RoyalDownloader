"""Taste profile, queue lifecycle, and download-control routes."""

# Queue/provider failures are deliberately contained at this boundary.
# ruff: noqa: BLE001

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from providers.mkissa import SOURCE_PREFIX as MKISSA_PREFIX
from providers.models import FilmpalastMovie, parse_episode_slug, strip_episode_suffix

router = APIRouter(tags=["queue"])


def _unbound_dependency(*_args, **_kwargs):
    raise RuntimeError("Queue router dependencies are not configured")


state: Any = None
UPDATE_INSTALLER: Any = None
_content_already_available = _unbound_dependency
_episode_placeholder = _unbound_dependency
_is_jellyfin_safety_block = _unbound_dependency
_movie_provider = _unbound_dependency
_persist_queue_state = _unbound_dependency
_queue_slug_claimed = _unbound_dependency
_require_persistent_snapshot = _unbound_dependency
_seerr_terminal_without_job = _unbound_dependency
_telegram_terminal_without_job = _unbound_dependency
broadcast = _unbound_dependency
build_queue_payload = _unbound_dependency
cached_movie_source_fallbacks = _unbound_dependency
load_movie_for_slug = _unbound_dependency
log = _unbound_dependency
on_job_done = _unbound_dependency
queue_content_key = _unbound_dependency
refresh_jellyfin_after_download = _unbound_dependency
run_download_queue = _unbound_dependency

_DYNAMIC_CALLS = (
    "_cancel_queue_slugs",
    "_cancel_withdrawn_watchlist_slugs",
    "_content_already_available",
    "_drop_queue_claims",
    "_enqueue_automatic_downloads",
    "_episode_placeholder",
    "_is_jellyfin_safety_block",
    "_job_queue_slugs",
    "_movie_provider",
    "_persist_queue_state",
    "_preferred_movie_sources",
    "_queue_slug_claimed",
    "_record_download_taste",
    "_release_removed_queue_slugs",
    "_require_persistent_snapshot",
    "_seerr_terminal_without_job",
    "_telegram_terminal_without_job",
    "broadcast",
    "build_queue_payload",
    "cached_movie_source_fallbacks",
    "load_movie_for_slug",
    "log",
    "on_job_done",
    "queue_content_key",
    "refresh_jellyfin_after_download",
    "run_download_queue",
)


def create_queue_router(backend) -> APIRouter:
    """Bind queue services dynamically and return their production router."""

    def dynamic(name):
        return lambda *args, **kwargs: getattr(backend, name)(*args, **kwargs)

    globals().update({name: dynamic(name) for name in _DYNAMIC_CALLS})
    globals().update({
        "state": backend.state,
        "UPDATE_INSTALLER": backend.UPDATE_INSTALLER,
    })
    return router


# ── Warteschlange ────────────────────────────────────────────────────────────
class _QueuePreparationJob:
    """Löst neu hinzugefügte Inhalte mit eigener Scheduler-Kapazität auf.

    Der gemeinsame Scheduler bleibt fuer Abbruch/Reihenfolge zustaendig, aber
    Vorbereitungen zaehlen nicht gegen die zwei echten Download-Slots.
    """

    is_preparation_job = True
    # Reine Diagnose-/Kompatibilitaetsgruppe. Der Scheduler begrenzt
    # Vorbereitungen separat; echte Providerzugriffe bleiben durch ihre
    # adaptereigenen Locks geschuetzt.
    host_group = "__series_preparation__"

    def __init__(
        self, jobs: list[tuple], out_root: Path,
        movie_fallbacks: dict[str, list[FilmpalastMovie]] | None = None,
    ):
        self.jobs = jobs
        self.out_root = out_root
        self.movie_fallbacks = movie_fallbacks or {}
        self.queue_slugs = {slug for _movie, slug in jobs}
        self.queue_slug = next(iter(self.queue_slugs)) if len(self.queue_slugs) == 1 else ""
        # Filme laufen auf einer unabhängigen, zuverlässigeren Route und sollen
        # nicht hinter hunderten Serien-Fallbacks auf ihre Vorbereitung warten.
        self.queue_priority = (
            0
            if any(parse_episode_slug(slug) is None for _movie, slug in jobs)
            else 100
        )
        self._cancelled = threading.Event()

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return thread

    def cancel(self):
        self._cancelled.set()

    def _run(self):
        queued_slugs: set[str] = set()
        marked_preparing = False
        try:
            with state.queue_prepare_lock:
                if self._cancelled.is_set():
                    return
                with state.queue_claim_lock:
                    state.preparing_queue_slugs.update(self.queue_slugs & state.picked)
                    marked_preparing = True
                broadcast({"type": "queue_update", "queue": build_queue_payload()})
                queued_slugs = run_download_queue(
                    self.jobs,
                    self.out_root,
                    start_queue=False,
                    cancelled=self._cancelled.is_set,
                    movie_fallbacks=self.movie_fallbacks,
                ) or set()
        except Exception as exc:
            log(f"Automatische Downloadvorbereitung fehlgeschlagen: {exc}", "err")
            for movie, slug in self.jobs:
                on_job_done(
                    False, f"Vorbereitung fehlgeschlagen: {exc}",
                    movie.title, Path(""), slug=slug,
                )
        finally:
            if marked_preparing:
                with state.queue_claim_lock:
                    state.preparing_queue_slugs.difference_update(self.queue_slugs)
            if not self._cancelled.is_set():
                for movie, slug in self.jobs:
                    if slug not in queued_slugs and _queue_slug_claimed(slug):
                        on_job_done(
                            False,
                            "Downloadvorbereitung ohne Abschluss beendet",
                            movie.title,
                            Path(""),
                            slug=slug,
                        )
            # Falls während einer laufenden Extraktion abgebrochen wurde, dürfen
            # danach erzeugte echte DownloadJobs nicht liegenbleiben/anlaufen.
            if self._cancelled.is_set():
                remove_pending = getattr(state.dl_queue, "remove_pending", None)
                if remove_pending:
                    remove_pending(
                        lambda job: bool(self.queue_slugs & set(getattr(job, "queue_slugs", [])))
                        or getattr(job, "queue_slug", "") in self.queue_slugs
                    )
            if marked_preparing:
                broadcast({"type": "queue_update", "queue": build_queue_payload()})


def _record_download_taste(jobs: list[tuple[FilmpalastMovie, str]], source: str) -> None:
    if not source:
        return
    for movie, slug in jobs:
        episode = parse_episode_slug(slug)
        is_anime = source == "anime" or slug.startswith(MKISSA_PREFIX)
        media_type = "anime" if is_anime else ("series" if episode else "movie")
        if is_anime:
            anime_base = (
                episode[0] if episode else slug
            ).removeprefix(MKISSA_PREFIX).split("|", 1)[0]
            item_key = f"anime:{anime_base}"
        else:
            item_key = f"series:{episode[0]}" if episode else f"movie:{slug}"
        state.taste_profile.record_event(
            "download",
            source=source,
            media_type=media_type,
            item_key=item_key,
            title=strip_episode_suffix(movie.title) if episode else movie.title,
            metadata={
                "genres": list(movie.genres or []),
                "year": movie.year,
                "runtime": movie.runtime,
                "languages": [movie.content_language] if movie.content_language else [],
            },
        )


def _enqueue_automatic_downloads(
    slugs: list[str],
    movie_fallbacks: dict[str, list[FilmpalastMovie]] | None = None,
    taste_source: str = "",
) -> set[str]:
    if UPDATE_INSTALLER.is_active() or state.ytdlp_update_active:
        log("Downloadstart pausiert: Ein Systemupdate läuft.", "warn")
        return set()
    content_keys = {
        slug: queue_content_key(slug, state.fp_movies.get(slug))
        for slug in slugs if slug in state.fp_movies
    }
    with state.queue_lifecycle_lock:
        # Zweite Prüfung unter demselben Lock, den auch der Updater beim Start
        # hält. So kann zwischen Vorprüfung und Queue-Aufbau kein Update starten.
        if UPDATE_INSTALLER.is_active() or state.ytdlp_update_active:
            log("Downloadstart pausiert: Ein Systemupdate läuft.", "warn")
            return set()
        queue_idle = (
            state.dl_queue.active_count() == 0
            and state.dl_queue.pending_count() == 0
        )
        active_slugs = {
            active_slug
            for active_job in state.dl_queue.active_jobs()
            for active_slug in _job_queue_slugs(active_job)
        }
        with state.queue_claim_lock:
            state.queue_content_keys.update(content_keys)
            queue_idle = queue_idle and not state.provider_waiting_jobs
            with state.download_state_lock:
                if queue_idle:
                    state.total_jobs = 0
                    state.done_jobs = 0
                    state.done_slugs.clear()
                    state.counted_queue_slugs.clear()
                already_counted = set(state.counted_queue_slugs)

            # Ein bereits gezählter oder noch physisch aktiver Slug gehört zu
            # einem älteren/aktiven Queue-Eintrag. Dessen Claim darf beim
            # Bereinigen neu abgelehnter Cross-Provider-Duplikate nicht fallen.
            protected_slugs = already_counted | active_slugs
            retained_key_slugs = protected_slugs | set(content_keys)
            for stale_slug in set(state.queue_content_keys) - retained_key_slugs:
                state.queue_content_keys.pop(stale_slug, None)
            occupied_keys = {
                state.queue_content_keys.get(existing_slug, "")
                for existing_slug in protected_slugs
            }
            occupied_keys.discard("")

            # Claim nach allen langsamen Provider-Aufrufen erneut prüfen. Ein
            # zwischenzeitliches Entfernen oder ein paralleler Trigger darf
            # keinen ungetrackten beziehungsweise doppelten Job starten.
            jobs = []
            for slug in slugs:
                movie = state.fp_movies.get(slug)
                key = content_keys.get(slug, "")
                if (
                    slug not in state.picked
                    or slug in already_counted
                    or slug in active_slugs
                    or movie is None
                    or (not movie.hosters and parse_episode_slug(slug) is None)
                    or (key and key in occupied_keys)
                ):
                    continue
                jobs.append((movie, slug))
                if key:
                    occupied_keys.add(key)

            newly_counted = {slug for _movie, slug in jobs}
            rejected_claims = {
                slug for slug in set(slugs)
                if slug in state.picked
                and slug not in newly_counted
                and slug not in protected_slugs
            }
            state.picked.difference_update(rejected_claims)

            if jobs:
                with state.download_state_lock:
                    state.counted_queue_slugs.update(newly_counted)
                    state.total_jobs += len(newly_counted)
                    done_jobs = state.done_jobs
                    total_jobs = state.total_jobs

                # Ein Vorbereitungsjob pro Inhalt: Dadurch werden signierte Stream-URLs
                # erst kurz vor ihrem echten Queue-Slot extrahiert statt stapelweise.
                for job in jobs:
                    slug = job[1]
                    # Vorbereitete Quellen sind Hinweise. Bei Episoden gilt
                    # selbst ein leerer Key nicht als endgültige Anbietersuche,
                    # weil sich Verfügbarkeit und Provider-Cooldowns ändern.
                    fallbacks = {}
                    if movie_fallbacks is not None and slug in movie_fallbacks:
                        fallbacks[slug] = list(movie_fallbacks[slug])
                    else:
                        cached_fallbacks = cached_movie_source_fallbacks(slug)
                        if cached_fallbacks is not None:
                            fallbacks[slug] = cached_fallbacks
                    state.dl_queue.add(_QueuePreparationJob(
                        [job], Path(state.save_path), movie_fallbacks=fallbacks,
                    ))
                state.dl_queue.start()

    if rejected_claims:
        _persist_queue_state()
    if not jobs:
        if rejected_claims:
            broadcast({"type": "queue_update", "queue": build_queue_payload()})
        return set()
    _record_download_taste(jobs, taste_source)
    log(f"Automatisch eingeplant: {len(jobs)} Download(s) (max. 2 parallel)")
    broadcast({
        "type": "queue_started",
        "added": len(jobs),
        "done_jobs": done_jobs,
        "total_jobs": total_jobs,
        "queue": build_queue_payload(),
    })
    return {slug for _movie, slug in jobs}


def restore_persisted_queue():
    """Stellt nach einem Neustart noch offene Queue-Einträge sicher wieder her."""
    with state.queue_claim_lock:
        unresolved = set(state.picked)
    if not unresolved:
        return
    log(f"Stelle {len(unresolved)} gespeicherte Queue-Einträge wieder her …")
    while unresolved:
        prepared: list[str] = []
        for slug in list(unresolved):
            with state.queue_claim_lock:
                if slug not in state.picked:
                    unresolved.discard(slug)
                    continue
            try:
                movie = (
                    _episode_placeholder(slug)
                    if parse_episode_slug(slug)
                    else load_movie_for_slug(slug)
                )
                if movie is None or not movie.hosters:
                    if parse_episode_slug(slug):
                        movie = _episode_placeholder(slug)
                    else:
                        continue
                already, reason = _content_already_available(movie, slug)
                if already and _is_jellyfin_safety_block(reason):
                    continue
                if already:
                    _release_removed_queue_slugs({slug})
                    unresolved.discard(slug)
                    continue
                state.fp_movies[slug] = movie
                prepared.append(slug)
                unresolved.discard(slug)
            except Exception as exc:
                log(f"Queue-Wiederherstellung für «{slug}» wartet: {exc}", "warn")
        if prepared:
            _enqueue_automatic_downloads(prepared)
        if unresolved:
            time.sleep(60)


class MovieDownloadPreference(BaseModel):
    provider: str = ""
    quality: str = ""
    hoster_url: str = ""


class QueueAddBody(BaseModel):
    slugs: list[str]
    preferences: dict[str, MovieDownloadPreference] = Field(default_factory=dict)
    source: str = Field(default="api", max_length=32)


class TasteEventBody(BaseModel):
    action: str = Field(min_length=1, max_length=24)
    source: str = Field(default="api", max_length=32)
    media_type: str = Field(default="", max_length=20)
    item_key: str = Field(default="", max_length=240)
    title: str = Field(default="", max_length=160)
    metadata: dict[str, object] = Field(default_factory=dict)
    value: float | None = None
    query: str = Field(default="", max_length=160)


class TasteFeedbackBody(BaseModel):
    item_key: str = Field(min_length=1, max_length=240)
    action: str = Field(min_length=1, max_length=24)
    source: str = Field(default="api", max_length=32)
    media_type: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=160)
    metadata: dict[str, object] = Field(default_factory=dict)
    value: float | None = None


class TasteImportBody(BaseModel):
    genres: dict[str, float] = Field(default_factory=dict)
    kinds: dict[str, float] = Field(default_factory=dict)


@router.get("/api/v1/taste/profile")
@router.get("/api/taste/profile")
async def api_taste_profile_get():
    return state.taste_profile.public_profile()


@router.post("/api/v1/taste/events")
@router.post("/api/taste/events")
async def api_taste_event(body: TasteEventBody):
    try:
        recorded = await run_in_threadpool(
            state.taste_profile.record_event,
            body.action,
            source=body.source,
            media_type=body.media_type,
            item_key=body.item_key,
            title=body.title,
            metadata=body.metadata,
            value=body.value,
            query=body.query,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"recorded": recorded, "profile": state.taste_profile.public_profile()}


@router.post("/api/v1/taste/feedback")
@router.post("/api/taste/feedback")
async def api_taste_feedback(body: TasteFeedbackBody):
    try:
        if body.action.casefold() == "clear":
            changed = await run_in_threadpool(
                state.taste_profile.clear_feedback, body.item_key,
            )
        else:
            await run_in_threadpool(
                state.taste_profile.set_feedback,
                body.item_key,
                body.action,
                source=body.source,
                media_type=body.media_type,
                title=body.title,
                metadata=body.metadata,
                value=body.value,
            )
            changed = True
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"changed": changed, "profile": state.taste_profile.public_profile()}


@router.post("/api/v1/taste/import")
@router.post("/api/taste/import")
async def api_taste_import(body: TasteImportBody):
    try:
        imported = await run_in_threadpool(
            state.taste_profile.import_legacy, body.model_dump(),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Das alte Geschmacksprofil ist ungültig.") from exc
    return {"imported": imported, "profile": state.taste_profile.public_profile()}


@router.post("/api/v1/taste/reset")
@router.post("/api/taste/reset")
@router.delete("/api/v1/taste/profile")
@router.delete("/api/taste/profile")
async def api_taste_profile_reset():
    await run_in_threadpool(state.taste_profile.reset)
    return {"reset": True, "profile": state.taste_profile.public_profile()}


def _preferred_movie_sources(
    slug: str,
    movie: FilmpalastMovie,
    preference: MovieDownloadPreference | None,
) -> tuple[FilmpalastMovie, list[FilmpalastMovie] | None]:
    """Sortiert die gewählte Quelle/Qualität vor, behält aber alle Fallbacks."""
    if preference is None or parse_episode_slug(slug):
        return movie, None
    provider = str(preference.provider or "").strip().casefold()
    quality = str(preference.quality or "").strip()
    hoster_url = str(preference.hoster_url or "").strip()
    with state.movie_source_cache_lock:
        sources = list(state.movie_source_cache.get(slug) or [movie])
    chosen_index = next(
        (index for index, source in enumerate(sources) if _movie_provider(source) == provider),
        None,
    )
    if chosen_index is None:
        return movie, None
    chosen_source = sources.pop(chosen_index)
    chosen = replace(chosen_source, hosters=list(chosen_source.hosters))
    chosen._preferred_quality = quality
    if hoster_url:
        chosen.hosters.sort(key=lambda hoster: str(hoster.url or "").strip() != hoster_url)
    return chosen, sources


@router.post("/api/v1/queue/add")
@router.post("/api/queue/add")
async def api_queue_add(body: QueueAddBody):
    def _work():
        added_slugs: list[str] = []
        selected_fallbacks: dict[str, list[FilmpalastMovie]] = {}
        skipped = 0
        skipped_details: dict[str, str] = {}
        for slug in body.slugs:
            with state.queue_lifecycle_lock:
                physically_active = any(
                    slug in _job_queue_slugs(job) for job in state.dl_queue.active_jobs()
                )
                with state.queue_claim_lock:
                    if slug in state.picked:
                        skipped += 1
                        skipped_details[slug] = "bereits eingeplant"
                        continue
                    with state.download_state_lock:
                        if slug in state.counted_queue_slugs or physically_active:
                            skipped += 1
                            skipped_details[slug] = "Abbruch läuft noch"
                            continue
                    state.picked.add(slug)
            try:
                movie = state.fp_movies.get(slug)
                if movie is None:
                    movie = (
                        _episode_placeholder(slug)
                        if parse_episode_slug(slug)
                        else load_movie_for_slug(slug)
                    )
                if movie is None or not movie.hosters:
                    if parse_episode_slug(slug):
                        movie = _episode_placeholder(slug)
                    else:
                        raise RuntimeError("kein Hoster verfügbar")
                already_available, reason = _content_already_available(movie, slug)
                if already_available:
                    skipped += 1
                    skipped_details[slug] = reason
                    with state.queue_claim_lock:
                        state.picked.discard(slug)
                    continue
                state.fp_movies[slug] = movie
                preferred, fallbacks = _preferred_movie_sources(
                    slug, movie, body.preferences.get(slug),
                )
                if fallbacks is not None:
                    movie = preferred
                    state.fp_movies[slug] = movie
                    selected_fallbacks[slug] = fallbacks
                added_slugs.append(slug)
            except Exception as exc:
                with state.queue_claim_lock:
                    state.picked.discard(slug)
                skipped += 1
                skipped_details[slug] = str(exc)[:180]
        return added_slugs, skipped, skipped_details, selected_fallbacks

    added_slugs, skipped, skipped_details, selected_fallbacks = await run_in_threadpool(_work)
    def _commit_claims():
        with state.queue_claim_lock:
            queue_snapshot = set(state.picked)
        try:
            _require_persistent_snapshot("queue", queue_snapshot)
        except HTTPException:
            with state.queue_claim_lock:
                state.picked.difference_update(added_slugs)
            raise
        accepted = _enqueue_automatic_downloads(
            added_slugs,
            movie_fallbacks=selected_fallbacks or None,
            taste_source=body.source,
        )
        duplicate_rejected = set(added_slugs) - accepted
        if len(accepted) < len(added_slugs):
            with state.queue_claim_lock:
                not_started = {
                    slug for slug in added_slugs
                    if slug in state.picked and slug not in accepted
                }
                state.picked.difference_update(not_started)
            _persist_queue_state()
        with state.download_state_lock:
            counters = state.done_jobs, state.total_jobs
        return accepted, duplicate_rejected, counters

    accepted, duplicate_rejected, counters = await run_in_threadpool(_commit_claims)
    if duplicate_rejected:
        skipped += len(duplicate_rejected)
        for slug in duplicate_rejected:
            skipped_details.setdefault(slug, "gleicher Inhalt bereits eingeplant")
    done_jobs, total_jobs = counters
    return {
        "added": len(accepted),
        "skipped": skipped,
        "skipped_details": skipped_details,
        "auto_started": len(accepted),
        "done_jobs": done_jobs,
        "total_jobs": total_jobs,
        "queue": build_queue_payload(),
    }


class QueueRemoveBody(BaseModel):
    slug: str


def _job_queue_slugs(job) -> set[str]:
    slugs = set(getattr(job, "queue_slugs", set()) or set())
    slug = getattr(job, "queue_slug", "")
    if slug:
        slugs.add(slug)
    return slugs


def _drop_queue_claims(slugs: set[str]) -> None:
    if not slugs:
        return
    with state.queue_claim_lock:
        state.picked.difference_update(slugs)
        state.preparing_queue_slugs.difference_update(slugs)
        for slug in slugs:
            state.provider_waiting_jobs.pop(slug, None)
        state.provider_retry_wake_event.set()
    _persist_queue_state()


def _release_removed_queue_slugs(slugs: set[str], *, persist: bool = True) -> None:
    if not slugs:
        return
    with state.queue_lifecycle_lock, state.queue_claim_lock:
        state.picked.difference_update(slugs)
        state.preparing_queue_slugs.difference_update(slugs)
        for slug in slugs:
            state.provider_waiting_jobs.pop(slug, None)
        state.provider_retry_wake_event.set()
        with state.download_state_lock:
            counted = slugs & state.counted_queue_slugs
            state.counted_queue_slugs.difference_update(counted)
            state.total_jobs = max(state.done_jobs, state.total_jobs - len(counted))
        if persist:
            _persist_queue_state()


def _cancel_queue_slugs(slugs: set[str], reason: str) -> None:
    if not slugs:
        return
    with state.queue_lifecycle_lock:
        state.dl_queue.remove_pending(lambda job: bool(slugs & _job_queue_slugs(job)))
        state.dl_queue.cancel_active(lambda job: bool(slugs & _job_queue_slugs(job)))
        state.dl_queue.remove_pending(lambda job: bool(slugs & _job_queue_slugs(job)))
        _release_removed_queue_slugs(slugs)
    for slug in slugs:
        _telegram_terminal_without_job(slug, False, reason, Path(""))
        _seerr_terminal_without_job(slug, False, reason, Path(""))
    broadcast({"type": "queue_update", "queue": build_queue_payload()})


def _cancel_withdrawn_watchlist_slugs(slugs: set[str], reason: str) -> set[str]:
    """Bricht nur Slugs ab, die kein aktueller Abo-Stand mehr benötigt."""
    if not slugs:
        return set()
    # Der Auto-Scheduler darf zwischen Recheck und Abbruch keinen veralteten
    # Snapshot neu einreihen. Die Watchlist bleibt bis nach dem Queue-Abbruch
    # gesperrt, damit ein neuerer Check denselben Slug nicht wieder freigibt.
    with state.auto_download_lock:  # noqa: SIM117 - documents lock order
        # Globale Reihenfolge: Queue-Lebenszyklus → Claim → Watchlist. Damit
        # bleibt die Entscheidung atomar, ohne mit watchlist_payload()
        # (Claim → Watchlist) eine Lock-Inversion zu erzeugen.
        with state.queue_lifecycle_lock:
            with state.queue_claim_lock:
                with state.watchlist_lock:
                    currently_required = {
                        slug
                        for pending in state.watchlist_new_slugs.values()
                        for slug in pending
                    }
                    cancellable = set(slugs) - currently_required
                    if cancellable:
                        _cancel_queue_slugs(cancellable, reason)
    return cancellable


@router.post("/api/v1/queue/remove")
@router.post("/api/queue/remove")
async def api_queue_remove(body: QueueRemoveBody):
    def _work():
        with state.queue_lifecycle_lock:
            with state.queue_claim_lock:
                candidate = set(state.picked) - {body.slug}
            _require_persistent_snapshot("queue", candidate)
            removed = state.dl_queue.remove_pending(
                lambda job: body.slug in _job_queue_slugs(job)
            )
            active = state.dl_queue.cancel_active(
                lambda job: body.slug in _job_queue_slugs(job)
            )
            # Ein Vorbereitungsjob kann während des Abbruchs noch einen echten
            # Download eingereiht haben; deshalb Pending erneut leeren.
            removed.extend(state.dl_queue.remove_pending(
                lambda job: body.slug in _job_queue_slugs(job)
            ))
            _release_removed_queue_slugs({body.slug}, persist=False)
            removed.extend(state.dl_queue.remove_pending(
                lambda job: body.slug in _job_queue_slugs(job)
            ))
        _telegram_terminal_without_job(body.slug, False, "Abgebrochen", Path(""))
        _seerr_terminal_without_job(body.slug, False, "Abgebrochen", Path(""))
        return len(removed), len(active), build_queue_payload()

    removed, active, queue = await run_in_threadpool(_work)
    broadcast({"type": "queue_update", "queue": queue})
    return {
        "removed": removed,
        "cancelled": active,
        "queue": queue,
    }


@router.post("/api/v1/queue/clear")
@router.post("/api/queue/clear")
async def api_queue_clear():
    def _work():
        with state.queue_lifecycle_lock:
            active_slugs = {
                slug for job in state.dl_queue.active_jobs()
                for slug in _job_queue_slugs(job)
            }
            with state.queue_claim_lock:
                removed_slugs = set(state.picked) - active_slugs
                candidate = set(state.picked) - removed_slugs
            _require_persistent_snapshot("queue", candidate)
            removed = state.dl_queue.remove_pending(lambda _job: True)
            removed_slugs.update(
                slug for job in removed for slug in _job_queue_slugs(job)
            )
            _release_removed_queue_slugs(removed_slugs, persist=False)
        for slug in removed_slugs:
            _telegram_terminal_without_job(slug, False, "Abgebrochen", Path(""))
            _seerr_terminal_without_job(slug, False, "Abgebrochen", Path(""))
        return removed_slugs, build_queue_payload()

    removed_slugs, queue = await run_in_threadpool(_work)
    broadcast({"type": "queue_update", "queue": queue})
    return {"removed": len(removed_slugs), "queue": queue}


@router.get("/api/v1/queue")
@router.get("/api/queue")
async def api_queue_get():
    return {"queue": build_queue_payload()}


# ── Downloads ────────────────────────────────────────────────────────────────
@router.post("/api/v1/download/cancel")
@router.post("/api/download/cancel")
async def api_download_cancel():
    def _work():
        with state.queue_lifecycle_lock:
            had_queue_activity = bool(
                state.dl_queue.active_count() or state.dl_queue.pending_count()
            )
            _require_persistent_snapshot("queue", set())
            state.dl_queue.cancel_all()
            with state.queue_claim_lock:
                with state.download_state_lock:
                    cancelled_slugs = set(state.picked) | set(state.counted_queue_slugs)
                    refresh_partial_success = bool(had_queue_activity and state.done_slugs)
                state.picked.clear()
                state.preparing_queue_slugs.clear()
                state.provider_waiting_jobs.clear()
                state.provider_retry_wake_event.set()
                with state.download_state_lock:
                    state.counted_queue_slugs.clear()
                    state.total_jobs = state.done_jobs
            with state.hoster_extract_lock:
                for attribute in ("voe_pool", "embed_pool"):
                    pool = getattr(state, attribute)
                    if pool is not None:
                        try:
                            pool.close()
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht geschlossen werden: {exc}", "warn")
                        setattr(state, attribute, None)
        for slug in cancelled_slugs:
            _telegram_terminal_without_job(slug, False, "Abgebrochen", Path(""))
            _seerr_terminal_without_job(slug, False, "Abgebrochen", Path(""))
        return refresh_partial_success, build_queue_payload()

    refresh_partial_success, queue = await run_in_threadpool(_work)
    broadcast({"type": "queue_update", "queue": queue})
    log("Download abgebrochen.")
    if refresh_partial_success:
        threading.Thread(target=refresh_jellyfin_after_download, daemon=True).start()
    return {"cancelled": True, "queue": queue}
