"""Seasonal discovery and durable, server-dated Advent assignments."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
CHRISTMAS = re.compile(r"\b(?:christmas|xmas|weihnacht\w*|heiligabend|santa claus|heiliger abend)\b", re.I)


def christmas_evidence(item: dict) -> str:
    """Only item-specific Christmas metadata qualifies, never the series or release month."""
    for field in ("Name", "Overview", "title", "description", "overview"):
        value = str(item.get(field) or "")
        if CHRISTMAS.search(value):
            return "Weihnachten in " + ("Titel" if field in ("Name", "title") else "Episodenbeschreibung")
    tags = item.get("Tags") or item.get("keywords") or []
    if any(CHRISTMAS.search(str(tag)) for tag in tags):
        return "Weihnachts-Schlagwort"
    return ""


def daily_selection(movies: list[dict], episodes: list[dict], day: str) -> list[dict]:
    def rotated(items, kind):
        ordered = sorted(items, key=lambda item: str(item.get("id") or item.get("tmdb_id")))
        if not ordered:
            return []
        # A fixed yearly order plus a daily offset guarantees movement between consecutive days.
        ordered.sort(key=lambda item: hashlib.sha256(
            f"{day[:4]}|{kind}|{item.get('id', item.get('tmdb_id'))}".encode()).hexdigest())
        offset = datetime.fromisoformat(day).timetuple().tm_yday % len(ordered)
        return ordered[offset:] + ordered[:offset]
    films, shows = rotated(movies, "movie"), rotated(episodes, "episode")
    result = []
    while (films or shows) and len(result) < 12:
        if films:
            result.append(films.pop(0))
        if shows and len(result) < 12:
            result.append(shows.pop(0))
    return result


class ChristmasService:
    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(BERLIN))
        self.preparation = threading.Lock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS seasons (year INTEGER PRIMARY KEY, movies TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS calendars (
                owner TEXT NOT NULL, year INTEGER NOT NULL, items TEXT NOT NULL,
                PRIMARY KEY(owner, year))""")
            db.execute("""CREATE TABLE IF NOT EXISTS doors (
                owner TEXT NOT NULL, year INTEGER NOT NULL, day INTEGER NOT NULL,
                PRIMARY KEY(owner, year, day))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def today(self):
        return self.clock().astimezone(BERLIN).date()

    def purge(self, today):
        # Dec 31 expires the current year too. January also cleans up a missed Dec 31.
        before = today.year + (1 if today.month == 12 and today.day == 31 else 0)
        with self.connect() as db:
            db.execute("DELETE FROM seasons WHERE year < ?", (before,))
            db.execute("DELETE FROM calendars WHERE year < ?", (before,))
            db.execute("DELETE FROM doors WHERE year < ?", (before,))

    @staticmethod
    def discover(client, today):
        if client is None or not client.configured:
            return []
        keyword_ids = set()
        for query in ("christmas", "christmas eve"):
            data = client._request("/search/keyword", {"query": query}) or {}
            for keyword in data.get("results") or []:
                if str(keyword.get("name") or "").lower() == query:
                    keyword_ids.add(int(keyword["id"]))
        if not keyword_ids:
            return []
        found = {}
        for page in range(1, 5):
            data = client._request("/discover/movie", {
                "language": "de-DE", "with_keywords": "|".join(map(str, sorted(keyword_ids))),
                "include_adult": "false", "sort_by": "popularity.desc", "page": page,
                "primary_release_date.lte": today.isoformat(), "vote_count.gte": 20,
            }) or {}
            for raw in data.get("results") or []:
                identity = raw.get("id")
                if not isinstance(identity, int) or identity <= 0 or raw.get("adult"):
                    continue
                if not raw.get("title") or not raw.get("poster_path"):
                    continue
                found[identity] = {
                    "tmdb_id": identity, "slug": f"tmdb:{identity}", "media_type": "movie",
                    "title": raw["title"], "year": str(raw.get("release_date") or "")[:4],
                    "description": raw.get("overview") or "", "rating": raw.get("vote_average") or 0,
                    "cover_url": client._poster_url(raw["poster_path"]),
                    "backdrop_url": client._backdrop_url(raw.get("backdrop_path") or ""),
                    "tmdb_discovery": True, "genre_ids": raw.get("genre_ids") or [],
                    "christmas_reason": "Verifiziertes TMDB-Weihnachts-Schlagwort",
                }
        return list(found.values())

    def movies(self, client, today):
        with self.connect() as db:
            existing = db.execute("SELECT movies FROM seasons WHERE year=?", (today.year,)).fetchone()
        if existing:
            return json.loads(existing[0])
        if client is None:
            return []
        with self.preparation:
            with self.connect() as db:
                existing = db.execute("SELECT movies FROM seasons WHERE year=?", (today.year,)).fetchone()
            if existing:
                return json.loads(existing[0])
            movies = self.discover(client, today)
            # Never freeze an incomplete calendar after a partial provider failure.
            eligible = [movie for movie in movies if 27 not in movie["genre_ids"]]
            if len(eligible) < 24:
                return []
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO seasons VALUES (?,?)",
                           (today.year, json.dumps(movies, ensure_ascii=False)))
            return movies

    def calendar(self, owner, year, movies):
        with self.connect() as db:
            existing = db.execute("SELECT items FROM calendars WHERE owner=? AND year=?", (owner, year)).fetchone()
            if existing:
                return json.loads(existing[0])
            eligible = [movie for movie in movies if 27 not in movie.get("genre_ids", [])]
            eligible.sort(key=lambda movie: hashlib.sha256(
                f"advent|{year}|{owner}|{movie['tmdb_id']}".encode()).hexdigest())
            if len(eligible) < 24:
                return []
            items = eligible[:24]
            db.execute("INSERT OR IGNORE INTO calendars VALUES (?,?,?)",
                       (owner, year, json.dumps(items, ensure_ascii=False)))
            # A competing process may have inserted its snapshot first.
            return json.loads(db.execute("SELECT items FROM calendars WHERE owner=? AND year=?",
                                         (owner, year)).fetchone()[0])

    def status(self, owner, client):
        today = self.today()
        self.purge(today)
        december = today.month == 12 and today.day <= 30
        carousel = december or today.month == 11 and today.day >= 10
        prepare_calendar = december or today.month == 11 and today.day >= 24
        payload = {
            "server_date": today.isoformat(), "timezone": "Europe/Berlin", "year": today.year,
            "calendar_active": december, "carousel_active": carousel,
            "unlocked": min(today.day, 24) if december else 0, "opened": [], "items": [],
            "manifest": [], "preparing": False,
        }
        if not carousel:
            return payload
        movies = self.movies(client, today)
        manifest = self.calendar(owner, today.year, movies) if prepare_calendar else []
        with self.connect() as db:
            payload["opened"] = [row[0] for row in db.execute(
                "SELECT day FROM doors WHERE owner=? AND year=? ORDER BY day", (owner, today.year))]
        payload["manifest"] = manifest
        payload["preparing"] = not movies or prepare_calendar and len(manifest) < 24
        if payload["carousel_active"]:
            payload["items"] = daily_selection(movies, [], today.isoformat())
        return payload

    def open(self, owner, day):
        today = self.today()
        if today.month != 12 or today.day > 30 or day < 1 or day > min(today.day, 24):
            raise ValueError("Dieses Türchen ist noch nicht freigegeben.")
        with self.connect() as db:
            existing = db.execute("SELECT items FROM calendars WHERE owner=? AND year=?",
                                  (owner, today.year)).fetchone()
            if not existing or len(json.loads(existing[0])) != 24:
                raise LookupError("Der Kalender wird noch vorbereitet.")
            item = json.loads(existing[0])[day - 1]
            db.execute("INSERT OR IGNORE INTO doors VALUES (?,?,?)", (owner, today.year, day))
        return {"year": today.year, "day": day, "item": item, "server_date": today.isoformat()}
