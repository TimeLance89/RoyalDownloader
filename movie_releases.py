"""Bounded, persistent streaming release discovery via the free direct API.

No RapidAPI billing, automatic subscription or paid fallback. A rolling request
ledger survives key changes and restarts; only the fixed vendor origin is used.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from runtime_paths import data_dir

API_URL = "https://api.movieofthenight.com/v4/changes"
COUNTRY_URL = "https://api.movieofthenight.com/v4/countries/{region}"
DAY = 86400
MONTH_LIMIT = 900
PAGES_PER_KIND = 6
API_CONTRACT_VERSION = 3
PREFERRED_SERVICES = (
    "netflix", "disney", "prime", "apple", "hbo", "paramount", "mubi",
    "hulu", "peacock", "skyshowtime", "wow", "plutotv", "crunchyroll",
    "rtl", "tubi", "iplayer", "itvx", "stan",
)
UPCOMING_SERVICES = frozenset({"netflix", "disney", "prime", "apple", "hbo", "mubi"})


class ReleaseAPIError(ValueError):
    """A safe provider error that can be shown without leaking response data."""


def safe_image(value: str) -> str:
    parsed = urlparse(str(value or ""))
    host = parsed.hostname or ""
    return str(value) if parsed.scheme == "https" and (
        host == "image.tmdb.org" or host.endswith(".movieofthenight.com")
    ) else ""


def normalize_changes(payload: dict, region: str, kind: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list) or not isinstance(payload.get("shows"), dict):
        raise ValueError("Release-Dienst lieferte ungültige Filmdaten.")
    entries = {}
    for change in payload["changes"]:
        if not isinstance(change, dict):
            continue
        show = payload["shows"].get(str(change.get("showId"))) or {}
        if (change.get("showType") != "movie" or change.get("itemType") != "show"
                or change.get("changeType") != kind or show.get("showType") != "movie"
                or change.get("streamingOptionType") not in {"subscription", "free"}):
            continue
        service = change.get("service") or {}
        service_id = str(service.get("id") or "")[:64]
        title = str(show.get("title") or "")[:240]
        if not title or not service_id:
            continue
        raw_id = str(show.get("tmdbId") or "").removeprefix("movie/")
        tmdb_id = int(raw_id) if raw_id.isdigit() else None
        timestamp = change.get("timestamp")
        if not isinstance(timestamp, (int, float)) or not 946684800 < timestamp < 7258118400:
            timestamp = None
        identity = f"{region}:{change.get('showId')}:{service_id}"
        images = show.get("imageSet") or {}
        poster = images.get("verticalPoster") or {}
        entries[identity] = {
            "id": identity, "title": title, "tmdb_id": tmdb_id,
            "year": str(show.get("releaseYear") or "")[:4],
            "overview": str(show.get("overview") or "")[:1200],
            "poster": safe_image(poster.get("w360") or poster.get("w240") or ""),
            "platform": str(service.get("name") or service_id)[:80],
            "platform_id": service_id, "region": region,
            "timestamp": timestamp, "date_kind": "announced" if kind == "upcoming" else "observed",
        }
    return list(entries.values())


def can_check(entry: dict, now: float) -> bool:
    # Unknown dates never release the RD check. Use the exact supplied instant.
    return bool(entry.get("timestamp") and entry["timestamp"] < now)


def catalogs_for_country(payload: dict, kind: str) -> str:
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, list):
        raise ValueError("Release-Dienst lieferte ungültige Länderdaten.")
    by_id = {
        str(service.get("id")): service
        for service in services
        if isinstance(service, dict) and service.get("id")
    }
    catalogs = []
    for service_id in PREFERRED_SERVICES:
        if kind == "upcoming" and service_id not in UPCOMING_SERVICES:
            continue
        service = by_id.get(service_id)
        options = service.get("streamingOptionTypes") if service else None
        if not isinstance(options, dict):
            continue
        for option_type in ("subscription", "free"):
            if options.get(option_type) is True:
                catalogs.append(f"{service_id}.{option_type}")
    if not catalogs:
        raise ValueError("Keine unterstützten Streamingdienste für diese Region gefunden.")
    return ",".join(catalogs[:32])


class ReleaseService:
    def __init__(self, path: Path | None = None, request=None, clock=time.time):
        self.path = path or data_dir() / "movie_releases_cache.json"
        self.request = request or requests.get
        self.clock = clock
        self.lock = threading.RLock()
        self.running = False
        self.checking = {}
        self.checks = {}
        try:
            self.doc = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(self.doc, dict) or not isinstance(self.doc.get("requests", []), list)
                    or not isinstance(self.doc.get("snapshots", {}), dict)):
                raise ValueError("Invalid snapshot")
        except (OSError, ValueError):
            self.doc = {"requests": [], "snapshots": {}}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(self.doc, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.path)

    def _reserve(self):
        with self.lock:
            now = self.clock()
            self.doc["requests"] = [t for t in self.doc.get("requests", [])
                                    if isinstance(t, (int, float)) and t > now - 31 * DAY]
            if len(self.doc["requests"]) >= MONTH_LIMIT:
                raise ValueError("Lokales Gratis-Kontingent erreicht. Gespeicherte Daten bleiben verfügbar.")
            self.doc["requests"].append(now)
            self._save()  # Fail closed: no request if quota cannot be persisted.

    def _request_json(self, url, config, params=None):
        self._reserve()
        with self.request(url, params=params, headers={"X-API-Key": config["api_key"]},
                          timeout=(5, 20), allow_redirects=False) as response:
            if response.status_code in (401, 403):
                raise ReleaseAPIError("API-Key oder Free-Tarif beim Release-Anbieter prüfen.")
            if response.status_code == 429:
                raise ReleaseAPIError("API-Kontingent ausgeschöpft. Nächster Versuch frühestens morgen.")
            if response.status_code == 400:
                raise ReleaseAPIError("Release-Anfrage wurde vom Anbieter abgelehnt. App-Version prüfen.")
            if response.status_code != 200:
                raise ReleaseAPIError("Release-Dienst derzeit nicht erreichbar.")
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Release-Dienst lieferte eine ungültige Antwort.")
        return payload

    def _fetch(self, config):
        rows = []
        partial = False
        country = self._request_json(COUNTRY_URL.format(region=config["region"]), config)
        completed_categories = 0
        successful_pages = 0
        failures = []
        for kind in ("upcoming", "new"):
            params = {"country": config["region"], "change_type": kind,
                      "item_type": "show", "show_type": "movie",
                      # The provider currently supports en/es/tr/fr here. The
                      # UI itself remains localized independently.
                      "include_unknown_dates": "true", "output_language": "en",
                      "order_direction": "asc" if kind == "upcoming" else "desc",
                      "catalogs": catalogs_for_country(country, kind)}
            try:
                for _ in range(PAGES_PER_KIND):
                    payload = self._request_json(API_URL, config, params)
                    rows.extend(normalize_changes(payload, config["region"], kind))
                    successful_pages += 1
                    if not payload.get("hasMore"):
                        break
                    cursor = payload.get("nextCursor")
                    if not isinstance(cursor, str) or not cursor or cursor == params.get("cursor"):
                        raise ValueError("Unvollständige Antwort des Release-Diensts.")
                    params["cursor"] = cursor
                else:
                    partial = True
                completed_categories += 1
            except ReleaseAPIError:
                raise
            except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as error:
                failures.append(error)
                partial = True
        if not completed_categories and not successful_pages:
            raise ValueError("Release-Dienst konnte keine Filmkategorie vollständig laden.") from failures[0]
        # Upcoming and new can overlap; observed availability takes precedence.
        return list({entry["id"]: entry for entry in rows}.values()), partial

    def refresh(self, config):
        try:
            rows, partial = self._fetch(config)
            with self.lock:
                snapshot = self.doc.setdefault("snapshots", {}).setdefault(config["region"], {})
                snapshot.update(entries=rows, updated_at=self.clock(), error="", partial=partial)
                self._save()
        except ValueError as error:
            # ValueError messages originate only from the controlled checks above.
            with self.lock:
                snapshot = self.doc.setdefault("snapshots", {}).setdefault(config["region"], {})
                snapshot["error"] = str(error)
                try:
                    self._save()
                except OSError:
                    pass
        except (requests.RequestException, OSError, TypeError, KeyError, AttributeError):
            # Never forward upstream bodies or exception strings containing credentials.
            with self.lock:
                snapshot = self.doc.setdefault("snapshots", {}).setdefault(config["region"], {})
                snapshot["error"] = "Release-Dienst derzeit nicht erreichbar. Gespeicherte Termine können veraltet sein."
                try:
                    self._save()
                except OSError:
                    pass
        finally:
            with self.lock:
                self.running = False

    def get(self, config, refresh=False):
        with self.lock:
            now = self.clock()
            snapshot = self.doc.setdefault("snapshots", {}).setdefault(config["region"], {})
            due = (snapshot.get("api_contract_version") != API_CONTRACT_VERSION
                   or now - snapshot.get("attempted_at", 0) >= (300 if refresh else DAY))
            if config["api_key"] and due and not self.running:
                snapshot["attempted_at"] = now
                snapshot["api_contract_version"] = API_CONTRACT_VERSION
                try:
                    self._save()
                except OSError:
                    snapshot["error"] = "Release-Cache konnte nicht gespeichert werden."
                else:
                    self.running = True
                    threading.Thread(target=self.refresh, args=(dict(config),), daemon=True).start()
            rows = copy.deepcopy(snapshot.get("entries", [])) if config["api_key"] else []
            for entry in rows:
                entry["can_check"] = can_check(entry, now)
                cached = self.checks.get(entry["id"], {})
                if now - cached.get("checked_at", 0) >= 900:
                    cached = {"status": "unchecked"}
                started = self.checking.get(entry["id"])
                if started is not None:
                    cached = {"status": "checking" if now - started < 60 else "unknown"}
                entry["rd"] = cached or {"status": "unchecked"}
                if not entry["can_check"]:
                    entry["rd"] = {"status": "scheduled"}
            return {"entries": rows, "region": config["region"], "configured": bool(config["api_key"]),
                    "loading": self.running, "error": snapshot.get("error", ""),
                    "partial": snapshot.get("partial", False), "updated_at": snapshot.get("updated_at", 0),
                    "stale": now - snapshot.get("updated_at", 0) > DAY,
                    "requests_used": len([t for t in self.doc.get("requests", []) if t > now - 31 * DAY]),
                    "request_limit": MONTH_LIMIT}

    def check(self, config, identity, search):
        with self.lock:
            rows = self.doc.get("snapshots", {}).get(config["region"], {}).get("entries", [])
            entry = next((copy.deepcopy(e) for e in rows if e["id"] == identity), None)
            if not entry or not can_check(entry, self.clock()):
                raise ValueError("RD-Prüfung erst nach einem bekannten Termin möglich.")
            previous = self.checks.get(identity, {})
            if self.clock() - previous.get("checked_at", 0) < 900:
                return previous
            if identity in self.checking or len(self.checking) >= 2:
                return {"status": "checking"}
            self.checking[identity] = self.clock()
        def work():
            try:
                results = search(entry["title"])
                exact = [r for r in results if entry["tmdb_id"] and str(r.get("tmdb_id")) == str(entry["tmdb_id"])]
                result = {"status": ("catalog" if exact else "not_found") if entry["tmdb_id"] else "unknown", "matches": exact[:3],
                          "checked_at": self.clock()}
            except Exception:  # Independent providers may fail; never claim absence on error.
                result = {"status": "unknown", "checked_at": self.clock()}
            with self.lock:
                self.checks[identity] = result
                self.checking.pop(identity, None)
        threading.Thread(target=work, daemon=True).start()
        return {"status": "checking"}


_service = None
_service_lock = threading.Lock()


def release_service():
    global _service
    with _service_lock:
        if _service is None:
            _service = ReleaseService()
        return _service
