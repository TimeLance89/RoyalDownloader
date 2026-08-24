"""Robuster, persistenter Import des öffentlichen SerienStream-Sendeplans."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from network_guard import safe_proxy_url
from runtime_paths import data_dir


logger = logging.getLogger(__name__)

CALENDAR_PAGE_URL = "https://serienstream.to/serienkalender"
CALENDAR_API_URL = "https://serienstream.to/api/calendar"
CALENDAR_CACHE_SECONDS = 5 * 60
CALENDAR_SNAPSHOT_SCHEMA = 1
CALENDAR_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
LANGUAGE_LABELS = {
    1: "Deutsch",
    2: "Englisch",
    3: "Deutsch (Untertitel)",
}
_SERIES_PATH = re.compile(
    r"/serie/([a-z0-9-]+)/staffel-(\d+)(?:/episode-(\d+))?/?"
)
_COVER_PATH = re.compile(r"/media/images/channel/desktop/[A-Za-z0-9_-]+")


def _bounded_int(value, fallback, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        try:
            parsed = int(fallback)
        except (TypeError, ValueError):
            parsed = minimum
    return max(minimum, min(parsed, maximum))


def _cover_url(value: object) -> str:
    raw = str(value or "").strip()
    if _COVER_PATH.fullmatch(raw):
        return f"https://serienstream.to{raw}"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if (
        parsed.scheme == "https"
        and parsed.hostname in {"serienstream.to", "www.serienstream.to"}
        and _COVER_PATH.fullmatch(parsed.path)
        and not parsed.query
        and not parsed.fragment
    ):
        return f"https://serienstream.to{parsed.path}"
    return ""


def _entry(item: object, date: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:240]
    path = str(item.get("url") or "").strip()
    match = _SERIES_PATH.fullmatch(path)
    if not title or not match:
        return None
    season = _bounded_int(item.get("season"), match.group(2), 0, 100)
    episode = _bounded_int(item.get("episode"), match.group(3), 0, 10_000)
    language_id = _bounded_int(item.get("language_id"), 0, 0, 10)
    time_label = str(item.get("time") or "00:00").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_label):
        time_label = "00:00"
    slug = match.group(1)
    base_slug = f"serienstream:{slug}"
    return {
        "date": date,
        "time": time_label,
        "title": title,
        "language": LANGUAGE_LABELS.get(language_id, "Unbekannt"),
        "language_id": language_id,
        "season": season,
        "episode": episode,
        "released": bool(item.get("released")),
        "url": f"https://serienstream.to{path}",
        "cover_url": _cover_url(item.get("cover_url")),
        "base_slug": base_slug,
        "sample_slug": (
            f"{base_slug}-s{season:02d}e{episode:02d}"
            if season > 0 and episode > 0 else base_slug
        ),
    }


def normalize_calendar_document(document: object, *, fetched_at: float | None = None) -> dict:
    """Validiert das Provider-Dokument vollständig und verwirft nur defekte Einträge."""
    if not isinstance(document, dict):
        raise ValueError("SerienStream hat kein Kalenderobjekt geliefert")
    days: list[dict] = []
    total = 0
    for raw_date in sorted(document):
        date = str(raw_date)
        values = document[raw_date]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not isinstance(values, list):
            continue
        entries = [result for value in values if (result := _entry(value, date))]
        entries.sort(key=lambda value: (value["time"], value["title"].casefold()))
        days.append({"date": date, "entries": entries})
        total += len(entries)
    if not days or total < 1:
        raise ValueError("SerienStream hat keine gültigen Kalendereinträge geliefert")
    timestamp = float(fetched_at if fetched_at is not None else time.time())
    return {
        "days": days,
        "total": total,
        "available_from": days[0]["date"],
        "available_to": days[-1]["date"],
        "provider": "serienstream",
        "source_url": CALENDAR_PAGE_URL,
        "updated_at": timestamp,
        "ready": True,
        "stale": False,
        "refreshing": False,
        "error": "",
    }


def fetch_calendar_document() -> dict:
    """Lädt Seite und JSON mit einer kurzen, vollständig unabhängigen HTTP-Session."""
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(impersonate="chrome136")
    proxy = safe_proxy_url()
    proxies = {"http": proxy, "https": proxy}
    page_headers = {
        "User-Agent": CALENDAR_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    }
    page = session.get(
        CALENDAR_PAGE_URL,
        headers=page_headers,
        timeout=5,
        allow_redirects=True,
        proxies=proxies,
    )
    if int(getattr(page, "status_code", 0) or 0) >= 400:
        raise ConnectionError(f"SerienStream-Kalenderseite: HTTP {page.status_code}")
    response = session.get(
        CALENDAR_API_URL,
        headers={
            **page_headers,
            "Accept": "application/json",
            "Referer": CALENDAR_PAGE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
        timeout=8,
        allow_redirects=True,
        proxies=proxies,
    )
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise ConnectionError(f"SerienStream-Kalender-API: HTTP {status or 'unbekannt'}")
    try:
        document = response.json()
    except Exception as exc:
        raise ValueError("SerienStream-Kalender-API lieferte ungültiges JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("SerienStream-Kalender-API lieferte kein Objekt")
    return document


class SeriesCalendarService:
    """Stale-while-revalidate-Speicher mit atomarem Snapshot auf der Platte."""

    def __init__(
        self,
        snapshot_path: Path | None = None,
        *,
        fetcher: Callable[[], dict] = fetch_calendar_document,
        now: Callable[[], float] = time.time,
    ):
        self.snapshot_path = snapshot_path or (data_dir() / "series_calendar_snapshot.json")
        self._fetcher = fetcher
        self._now = now
        self._lock = threading.RLock()
        self._refresh_done = threading.Event()
        self._refresh_done.set()
        self._refreshing = False
        self._last_error = ""
        self._snapshot = self._read_snapshot()

    def _read_snapshot(self) -> dict | None:
        try:
            stored = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if stored.get("schema") != CALENDAR_SNAPSHOT_SCHEMA:
                return None
            return normalize_calendar_document(
                stored.get("document"),
                fetched_at=float(stored.get("fetched_at") or 0),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_snapshot(self, document: dict, fetched_at: float) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.snapshot_path.with_name(
            f".{self.snapshot_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        payload = {
            "schema": CALENDAR_SNAPSHOT_SCHEMA,
            "fetched_at": fetched_at,
            "document": document,
        }
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self.snapshot_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _result(self, snapshot: dict, *, stale: bool, refreshing: bool, error: str = "") -> dict:
        return {
            **snapshot,
            "stale": stale,
            "refreshing": refreshing,
            "error": error,
        }

    def _failure(self, error: str, *, refreshing: bool = False) -> dict:
        return {
            "days": [],
            "total": 0,
            "available_from": "",
            "available_to": "",
            "provider": "serienstream",
            "source_url": CALENDAR_PAGE_URL,
            "updated_at": 0,
            "ready": False,
            "stale": False,
            "refreshing": refreshing,
            "error": error or "Der SerienStream-Sendeplan ist nicht erreichbar.",
        }

    def _refresh_started(self) -> dict:
        try:
            document = self._fetcher()
            fetched_at = self._now()
            snapshot = normalize_calendar_document(document, fetched_at=fetched_at)
            self._write_snapshot(document, fetched_at)
            with self._lock:
                self._snapshot = snapshot
                self._last_error = ""
            return self._result(snapshot, stale=False, refreshing=False)
        except Exception as exc:
            logger.warning("SerienStream-Sendeplan konnte nicht aktualisiert werden: %s", exc)
            message = str(exc).strip() or "Der SerienStream-Sendeplan ist nicht erreichbar."
            with self._lock:
                self._last_error = message
                if self._snapshot:
                    return self._result(
                        self._snapshot, stale=True, refreshing=False, error=message,
                    )
            return self._failure(message)
        finally:
            with self._lock:
                self._refreshing = False
                self._refresh_done.set()

    def refresh(self) -> dict:
        with self._lock:
            if self._refreshing:
                if self._snapshot:
                    return self._result(
                        self._snapshot, stale=True, refreshing=True, error=self._last_error,
                    )
                return self._failure("Der Sendeplan wird gerade aufgebaut.", refreshing=True)
            self._refreshing = True
            self._refresh_done.clear()
        return self._refresh_started()

    def refresh_async(self) -> bool:
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing = True
            self._refresh_done.clear()
        threading.Thread(
            target=self._refresh_started,
            name="series-calendar-refresh",
            daemon=True,
        ).start()
        return True

    def get(self, *, force: bool = False) -> dict:
        with self._lock:
            snapshot = self._snapshot
            refreshing = self._refreshing
            error = self._last_error
        if snapshot is None and refreshing:
            self._refresh_done.wait(timeout=10)
            with self._lock:
                snapshot = self._snapshot
                refreshing = self._refreshing
                error = self._last_error
            if snapshot is not None:
                return self._result(snapshot, stale=False, refreshing=refreshing, error=error)
            if refreshing:
                return self._failure("Der Sendeplan wird gerade aufgebaut.", refreshing=True)
            return self._failure(error)
        if force or snapshot is None:
            return self.refresh()
        age = max(0.0, self._now() - float(snapshot.get("updated_at") or 0))
        if age <= CALENDAR_CACHE_SECONDS:
            return self._result(snapshot, stale=False, refreshing=refreshing, error=error)
        self.refresh_async()
        return self._result(snapshot, stale=True, refreshing=True, error=error)


_service: SeriesCalendarService | None = None
_service_lock = threading.Lock()


def get_series_calendar_service() -> SeriesCalendarService:
    global _service
    with _service_lock:
        if _service is None:
            _service = SeriesCalendarService()
        return _service
