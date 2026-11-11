"""Daily movie browse order and bounded history of the films it featured."""

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import timedelta

from core.config import config_path

logger = logging.getLogger(__name__)
FEATURED = 9
HISTORY_DAYS = 28
RECENT_FEEDS = frozenset({"filmpalast", "kinoger", "kinox", "einschalten", "ridomovies"})


def movie_browse_configuration(priority):
    from application_services.runtime import backend_value

    state = backend_value("state")
    config = backend_value("appconfig")
    with state.provider_priority_lock:
        order = backend_value("provider_order")("movies")
        enabled = config.normalize_provider_selection(state.provider_enabled.get("movies", order), order)
        languages = set(state.content_languages)
    ranks = {provider: index for index, provider in enumerate(order)}
    return sorted(priority, key=lambda provider: ranks.get(provider, len(ranks))), enabled, languages


def _signals(scope, day, identities):
    from application_services.chart_history import ChartHistory, _breakout, _indexed

    snapshots, _, _ = ChartHistory(config_path().with_name("royal_charts.sqlite3")).read(scope, day)
    index, _ = _indexed(snapshots)
    if day.isoformat() not in index:
        day -= timedelta(days=1)
    current = index.get(day.isoformat(), {})
    earlier = [items for date, items in index.items()
               if (day - timedelta(days=7)).isoformat() <= date < day.isoformat()]
    aliases = {}
    for key, item in current.items():
        if item.get("kind") == "movie":
            for alias in [key, *item.get("aliases", [])]:
                aliases.setdefault(alias, set()).add(key)
    signals = {}
    for identity in identities:
        matches = aliases.get(identity, set())
        if len(matches) != 1:
            continue
        key = next(iter(matches))
        comparable = [_breakout(current[key], items[key]) or 0 for items in earlier if key in items]
        if comparable and comparable[-1] and sum(comparable) / len(comparable) >= 5:
            signals[identity] = sum(comparable) / len(comparable)
    return signals


def _rank(day, keys, recent, history, rising):
    week = [row for date, row in history if date >= (day - timedelta(days=7)).isoformat()]
    counts = Counter(key for row in week for key in row["order"][:FEATURED])
    recent_head = {key for date, row in history if date >= (day - timedelta(days=2)).isoformat()
                   for key in row["order"][:FEATURED]}
    seen = {key for _, row in history for key in row["order"]}
    # Establish a baseline before interpreting a newly observed feed entry.
    observed_feeds = {provider for _, row in history for provider in row["feeds"]}
    new = {key for key, providers in recent.items() if key not in seen and providers & observed_feeds}
    reasons = {}
    scores = {}
    for position, key in enumerate(keys):
        rise = rising.get(key, 0)
        if rise:
            reasons[key] = "rising"
        elif key in new:
            reasons[key] = "new"
        seed = hashlib.sha256(f"{day.isoformat()}|{key}".encode()).digest()
        variation = seed[0] / 255 * 5
        score = 22 / (1 + position / 12) + variation
        score += min(20, rise) + (10 if key in new else 0) - min(16, 4 * counts[key])
        cooling_down = counts[key] >= 3 and key in recent_head and rise < 12
        scores[key] = (cooling_down, -score, position)
    return sorted(keys, key=scores.__getitem__), reasons


def rank_movie_browse(entries, first_wave, configured, languages):
    if not entries:
        return entries, {}
    from application_services.daily_top import _candidate_identity, _configuration, chart_day

    def key_for(provider, item):
        if item.tmdb_id or item.year:
            return _candidate_identity("movie", item.title, item.year, item.tmdb_id)
        return f"movie:source:{provider}:{item.slug}"

    keys = [key_for(provider, item) for provider, item in entries]
    recent = {}
    for provider in RECENT_FEEDS:
        for item in first_wave.get(provider, [])[:12]:
            recent.setdefault(key_for(provider, item), set()).add(provider)
    feeds = sorted(provider for provider in RECENT_FEEDS if first_wave.get(provider))
    day = chart_day()
    scope = hashlib.sha256(json.dumps([configured, sorted(languages)]).encode()).hexdigest()
    try:
        with closing(sqlite3.connect(config_path().with_name("movie_discovery.sqlite3"), timeout=1)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS movie_browse_days (
                scope TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (scope, day)
            )""")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM movie_browse_days WHERE scope = ? AND day = ?",
                             (scope, day.isoformat())).fetchone()
            if row:
                snapshot = json.loads(row[0])
            else:
                start = (day - timedelta(days=HISTORY_DAYS)).isoformat()
                history = [(date, json.loads(payload)) for date, payload in db.execute(
                    "SELECT day, payload FROM movie_browse_days WHERE scope = ? AND day >= ? AND day < ?",
                    (scope, start, day.isoformat()),
                )]
                try:
                    chart_scope = _configuration()[0]
                    rising = _signals(chart_scope, day, set(keys))
                except (OSError, sqlite3.Error, ValueError):
                    rising = {}
                order, reasons = _rank(day, list(dict.fromkeys(keys)), recent, history, rising)
                snapshot = {"order": order, "reasons": reasons, "feeds": feeds}
                db.execute("DELETE FROM movie_browse_days WHERE day < ?", (start,))
                db.execute("INSERT INTO movie_browse_days VALUES (?, ?, ?)",
                           (scope, day.isoformat(), json.dumps(snapshot)))
    except (OSError, sqlite3.Error, ValueError):
        logger.warning("Filmreihenfolge konnte nicht gespeichert werden", exc_info=True)
        return entries, {}

    positions = {key: rank for rank, key in enumerate(snapshot["order"])}
    ranked = sorted(zip(keys, entries), key=lambda pair: positions.get(pair[0], len(positions)))
    return [entry for _, entry in ranked], {
        entry[1].slug: snapshot["reasons"][key] for key, entry in ranked if key in snapshot["reasons"]
    }
