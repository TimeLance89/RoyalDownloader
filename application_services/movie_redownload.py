"""Explicit delete-before-download transactions; never accept client file paths.

The durable journal precedes deletion. An interrupted/failed delete requires
inspection instead of replaying destructive calls against possibly new media.
Once deleted, retries only enqueue; completed request IDs never delete again.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException

from providers.models import parse_episode_slug

replacement_request: ContextVar[str] = ContextVar("replacement_request", default="")
replacement_lock = threading.Lock()


class ReplacementJournal:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS replacements "
            "(request_id TEXT PRIMARY KEY, identity TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        return connection

    def get(self, request_id: str):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM replacements WHERE request_id=?", (request_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def begin(self, request_id: str, identity: str, fingerprint: str, targets: list[str]):
        record = {"phase": "deleting", "fingerprint": fingerprint, "targets": targets}
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload FROM replacements WHERE identity=?", (identity,),
            ).fetchall()
            if any(json.loads(row[0])["phase"] != "queued" for row in rows):
                raise HTTPException(409, "Für diesen Film läuft bereits ein Ersetzen oder eine Prüfung ist erforderlich.")
            connection.execute(
                "INSERT INTO replacements VALUES (?, ?, ?)",
                (request_id, identity, json.dumps(record)),
            )
        return record

    def save(self, request_id: str, record: dict):
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE replacements SET payload=? WHERE request_id=?",
                (json.dumps(record), request_id),
            )


def request_fingerprint(user_id: str, body) -> str:
    payload = [user_id, body.slug, str(body.tmdb_id), body.preference.model_dump()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def prepare_replacement(backend, journal, body, user_id: str):
    """Resolve trustworthy identity/source before deleting exact Jellyfin items."""
    fingerprint = request_fingerprint(user_id, body)
    previous = journal.get(str(body.request_id))
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise HTTPException(409, "Diese Anfrage-ID gehört zu einer anderen Auswahl.")
        if previous["phase"] == "deleting":
            raise HTTPException(409, "Löschung nicht sicher abgeschlossen. Jellyfin-Bestand zuerst manuell prüfen; es wird nichts erneut gelöscht.")
        return previous
    if parse_episode_slug(body.slug):
        raise HTTPException(422, "Ersetzen ist hier nur für einzelne Filme möglich.")
    movie = backend.load_movie_for_slug(body.slug)
    if movie is None or not movie.hosters:
        raise HTTPException(409, "Keine Downloadquelle verfügbar. Der vorhandene Film bleibt erhalten.")
    selected, _fallbacks = backend._preferred_movie_sources(body.slug, movie, body.preference)
    if not selected.hosters:
        raise HTTPException(409, "Die gewählte Quelle ist nicht verfügbar.")
    title = backend.clean_movie_title(movie.title)
    summary = backend.get_tmdb_client().movie_summary(title, movie.year) or {}
    identity = str(summary.get("tmdb_id") or "")
    client = backend.get_jellyfin_client()
    if not client.configured:
        raise HTTPException(409, "Jellyfin muss für das sichere Ersetzen eingerichtet sein.")
    # A search result must agree with both the server title/year and the item
    # the viewer confirmed. Fuzzy TMDB search alone cannot authorize deletion.
    if (
        identity != str(body.tmdb_id)
        or not movie.year
        or str(summary.get("year") or "") != str(movie.year)
        or not client.match(title, movie.year, items=[{
            "name": summary.get("title"), "original_title": summary.get("original_title"),
            "year": summary.get("year"),
        }])
    ):
        raise HTTPException(409, "Filmidentität nicht eindeutig bestätigt. Es wurde nichts gelöscht.")
    state = backend.state
    # Same lock order as automatic queue admission. No queue may start between
    # the active-job check and deletion. Network work runs in a worker thread.
    with state.auto_download_lock, state.queue_lifecycle_lock:
        key = f"movie:tmdb:{identity}"
        physical_slugs = set()
        for job in state.dl_queue.active_jobs():
            physical_slugs.update(getattr(job, "queue_slugs", set()) or set())
            if getattr(job, "queue_slug", ""):
                physical_slugs.add(job.queue_slug)
        with state.queue_claim_lock:
            if any(
                slug == body.slug or backend.queue_content_key(slug) == key
                for slug in state.picked | physical_slugs
            ):
                raise HTTPException(409, "Dieser Film ist bereits eingeplant. Es wurde nichts gelöscht.")
        items = client.list_movies()
        if items is None:
            raise HTTPException(503, "Jellyfin nicht erreichbar. Es wurde nichts gelöscht.")
        targets = sorted({
            str(item["id"]) for item in items
            if item.get("id") and str(item.get("tmdb_id") or "") == identity
        })
        if not targets:
            raise HTTPException(409, "Keine eindeutig zugeordnete alte Version in Jellyfin gefunden.")
        record = journal.begin(str(body.request_id), identity, fingerprint, targets)
        for item_id in targets:
            if not client.delete_item(item_id):
                raise HTTPException(502, "Alte Version konnte nicht vollständig gelöscht werden. Kein Download gestartet; Jellyfin-Bestand prüfen.")
        # Persist this boundary before refreshing caches or entering the queue.
        record["phase"] = "deleted"
        journal.save(str(body.request_id), record)
    return record


def refresh_after_replacement(backend, body):
    items = backend.get_jellyfin_library(force=True)
    identities = backend.get_jellyfin_movie_identities(force=True)
    if items is None or identities is None:
        raise HTTPException(503, "Alte Version gelöscht. Jellyfin-Abgleich fehlgeschlagen; dieselbe Anfrage erneut versuchen.")
    if any(str(item.get("tmdb_id") or "") == str(body.tmdb_id) for item in items):
        raise HTTPException(409, "Jellyfin meldet weiterhin eine Version. Kein Download gestartet; dieselbe Anfrage später erneut versuchen.")
    backend.request_jellyfin_live_refresh()
