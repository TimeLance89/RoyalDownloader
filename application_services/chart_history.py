"""Durable daily snapshots and history-based Royal Charts views."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import date, timedelta

ALGORITHM = "3.0"
RETENTION_DAYS = 90
RETRY_SECONDS = 15 * 60
SEEN_LIMIT = 32_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS chart_days (
    algorithm TEXT NOT NULL,
    scope TEXT NOT NULL,
    day TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (algorithm, scope, day)
);
CREATE INDEX IF NOT EXISTS chart_days_expiration ON chart_days (day);
CREATE TABLE IF NOT EXISTS chart_attempts (
    algorithm TEXT NOT NULL,
    scope TEXT NOT NULL,
    day TEXT NOT NULL,
    token TEXT NOT NULL,
    retry_after REAL NOT NULL,
    PRIMARY KEY (algorithm, scope, day)
);
CREATE TABLE IF NOT EXISTS chart_baselines (
    algorithm TEXT NOT NULL,
    scope TEXT NOT NULL,
    first_day TEXT NOT NULL,
    last_day TEXT NOT NULL,
    PRIMARY KEY (algorithm, scope)
);
CREATE TABLE IF NOT EXISTS chart_seen (
    algorithm TEXT NOT NULL,
    scope TEXT NOT NULL,
    identity TEXT NOT NULL,
    first_day TEXT NOT NULL,
    PRIMARY KEY (algorithm, scope, identity)
);
"""


class ChartHistory:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.executescript(SCHEMA)
            with db:
                yield db

    def claim(self, scope, day):
        """Reserve one build across processes without holding a DB lock during I/O."""
        day_key = day.isoformat()
        cutoff = (day - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        token = uuid.uuid4().hex
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM chart_days WHERE algorithm = ? AND scope = ? AND day = ?",
                (ALGORITHM, scope, day_key),
            ).fetchone():
                return None
            db.execute("DELETE FROM chart_days WHERE day < ?", (cutoff,))
            db.execute("DELETE FROM chart_attempts WHERE day < ?", (day_key,))
            db.execute(
                """DELETE FROM chart_seen WHERE (algorithm, scope) IN
                   (SELECT algorithm, scope FROM chart_baselines WHERE last_day < ?)""",
                (cutoff,),
            )
            db.execute("DELETE FROM chart_baselines WHERE last_day < ?", (cutoff,))
            updated = db.execute(
                """INSERT INTO chart_attempts VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (algorithm, scope, day) DO UPDATE SET
                       token = excluded.token, retry_after = excluded.retry_after
                   WHERE chart_attempts.retry_after <= ?""",
                (ALGORITHM, scope, day_key, token, now + RETRY_SECONDS, now),
            )
            return token if updated.rowcount else None

    def save(self, scope, day, token, payload):
        day_key = day.isoformat()
        key = (ALGORITHM, scope, day_key)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "DELETE FROM chart_attempts WHERE algorithm = ? AND scope = ? AND day = ? AND token = ?",
                (*key, token),
            ).rowcount:
                return
            db.execute(
                "INSERT INTO chart_days VALUES (?, ?, ?, ?)",
                (*key, json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)),
            )
            db.execute(
                """INSERT INTO chart_baselines VALUES (?, ?, ?, ?)
                   ON CONFLICT (algorithm, scope) DO UPDATE SET
                       last_day = excluded.last_day""",
                (*key, day_key),
            )
            size = db.execute(
                "SELECT COUNT(*) FROM chart_seen WHERE algorithm = ? AND scope = ?", key[:2],
            ).fetchone()[0]
            identities = {value for item in payload["candidates"]
                          for value in [item["identity"], *item.get("aliases", [])]}
            if size + len(identities) <= SEEN_LIMIT:
                db.executemany(
                    "INSERT OR IGNORE INTO chart_seen VALUES (?, ?, ?, ?)",
                    ((*key[:2], identity, day_key) for identity in sorted(identities)),
                )
            else:
                # A gap in first sightings must never produce a later false NEW.
                db.execute(
                    "INSERT OR IGNORE INTO chart_seen VALUES (?, ?, '', ?)", (*key[:2], day_key),
                )

    def read(self, scope, day):
        start = (day - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        with self._connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                """SELECT payload FROM chart_days WHERE algorithm = ? AND scope = ?
                   AND day BETWEEN ? AND ? ORDER BY day""",
                (ALGORITHM, scope, start, day.isoformat()),
            ).fetchall()
            baseline = db.execute(
                "SELECT first_day FROM chart_baselines WHERE algorithm = ? AND scope = ?", (ALGORITHM, scope),
            ).fetchone()
            snapshots = [json.loads(row[0]) for row in rows]
            current = snapshots[-1]["candidates"] if snapshots and snapshots[-1]["period"] == day.isoformat() else []
            identities = {value for item in current for value in [item["identity"], *item.get("aliases", [])]}
            identities.add("")
            seen = dict(db.execute(
                """SELECT identity, first_day FROM chart_seen WHERE algorithm = ? AND scope = ?
                   AND identity IN (SELECT value FROM json_each(?)) AND first_day <= ?""",
                (ALGORITHM, scope, json.dumps(sorted(identities)), day.isoformat()),
            ))
        return snapshots, baseline[0] if baseline else None, seen


def _indexed(snapshots):
    aliases = defaultdict(set)
    for snapshot in snapshots:
        for item in snapshot["candidates"]:
            if ":tmdb:" in item["identity"]:
                for alias in item.get("aliases", []):
                    aliases[alias].add(item["identity"])

    index = {}
    appearances = defaultdict(dict)
    for snapshot in snapshots:
        period = snapshot["period"]
        current = {}
        for item in snapshot["candidates"]:
            identity = item["identity"]
            if ":tmdb:" not in identity:
                matches = set().union(*(aliases[alias] for alias in item.get("aliases", [])))
                if len(matches) == 1:
                    identity = next(iter(matches))
            current.setdefault(identity, item)
        index[period] = current
        for identity, item in current.items():
            appearances[identity][period] = item["global_rank"]
    return index, appearances


def _source_set(snapshot, kind):
    if not snapshot:
        return set()
    return {
        provider for provider, source in snapshot["sources"].get(kind, {}).items()
        if source["observed"] and source["type"] in {
            "views_rank", "trending_rank", "popularity_rank", "editorial_top",
        }
    }


def _movement(item, positions, today, yesterday, seen):
    if today not in positions:
        return {"direction": "unknown"}
    previous = positions.get(yesterday)
    if previous is not None:
        delta = previous - positions[today]
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        return {"direction": direction, "delta": delta, "previous_rank": previous}
    if any(period < today for period in positions) or seen.get(item["identity"], today) < today:
        return {"direction": "returning"}
    identity_keys = [item["identity"], *item.get("aliases", [])]
    first_record = min((seen[key] for key in identity_keys if key in seen), default=None)
    return {"direction": "new" if first_record == today and "" not in seen else "unknown"}


def _breakout(current, previous):
    if not previous:
        return None
    deltas = []
    for source, observation in current["popularity_observations"].items():
        prior = previous["popularity_observations"].get(source)
        if not prior or observation["provider"] != prior["provider"]:
            continue
        provider = observation["provider"]
        signal = current["provider_signals"].get(provider, {}).get("type")
        if provider == "tmdb" or signal in {"views_rank", "trending_rank", "popularity_rank"}:
            deltas.append(observation["value"] - prior["value"])
    increase = sum(deltas) / len(deltas) if deltas else 0
    return round(increase, 2) if increase >= 5 else None


def _aggregate(index, periods, day):
    items = {}
    totals = defaultdict(float)
    total_weight = 0.0
    for period in periods:
        age = (day - date.fromisoformat(period)).days
        weight = 1 / (1 + age / 7)
        total_weight += weight
        for identity, item in index[period].items():
            items[identity] = item
            position = (31 - item["global_rank"]) * 100 / 30
            totals[identity] += weight * (0.60 * position + 0.40 * item["components"]["popularity"])
    return [(identity, item, round(totals[identity] / total_weight, 3))
            for identity, item in items.items()]


def _timeline(positions, days, recorded):
    return [
        {"period": period, "rank": positions.get(period), "recorded": period in recorded}
        for period in days
    ]


def chart_view(data, day, mode, kind, genre):
    snapshots, baseline, seen = data
    index, appearances = _indexed(snapshots)
    sources = {snapshot["period"]: snapshot for snapshot in snapshots}
    today = day.isoformat()
    yesterday = (day - timedelta(days=1)).isoformat()
    dates = [(day - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
    periods = [period for period in dates[-(7 if mode == "week" else 30):] if period in index]
    comparable = yesterday in index and all(
        _source_set(sources.get(today), media) == _source_set(sources.get(yesterday), media)
        for media in ("movie", "series")
    )
    current = index.get(today, {})
    motions = {
        identity: (_movement(item, appearances[identity], today, yesterday, seen)
                   if comparable else {"direction": "unknown"})
        for identity, item in current.items()
    }
    reason = None
    if mode in {"week", "month"}:
        rows = _aggregate(index, periods, day) if len(periods) >= 2 else []
        if not rows:
            reason = "insufficient_history"
    elif mode == "breakouts":
        previous = index.get(yesterday, {})
        rows = [(identity, item, score) for identity, item in current.items()
                if (score := _breakout(item, previous.get(identity))) is not None]
        if not current or not previous:
            reason = "insufficient_history"
    elif mode == "new":
        rows = [(identity, item, item["score"]) for identity, item in current.items()
                if motions[identity]["direction"] == "new"]
        if not comparable or "" in seen:
            reason = "insufficient_history"
    else:
        rows = [(identity, item, item["score"]) for identity, item in current.items()]
        if not rows:
            reason = "no_snapshot"

    if mode != "today":
        rows.sort(key=lambda row: (-row[2], row[0]))
    candidates = []
    for identity, item, mode_score in rows:
        if kind != "mixed" and kind != item["kind"]:
            continue
        if genre and genre.casefold() not in {name.casefold() for name in item["item"].get("genres", [])}:
            continue
        positions = appearances[identity]
        streak = 0
        last_day = max(positions)
        while (date.fromisoformat(last_day) - timedelta(days=streak)).isoformat() in positions:
            streak += 1
        candidates.append({
            **{key: value for key, value in item.items() if key != "aliases"},
            "identity": identity, "mode_rank": len(candidates) + 1, "mode_score": mode_score,
            "movement": motions.get(identity, {"direction": "unknown"}),
            "history": {
                "days_charted": len(positions), "best_rank": min(positions.values()),
                "streak": streak, "last_day": last_day,
                "last_7": _timeline(positions, dates[-7:], index),
                "last_30": _timeline(positions, dates, index),
            },
        })
    if not candidates and not reason:
        reason = "no_matches"
    snapshot = sources.get(today, {})
    return {
        "version": 3, "algorithm_version": ALGORITHM, "period": today, "mode": mode,
        "generated_at": snapshot.get("generated_at"), "sources": snapshot.get("sources", {}),
        "source_status": snapshot.get("source_status", {}),
        "recorded_days": len(periods) if mode in {"week", "month"} else len(index),
        "first_recorded_day": baseline, "empty_reason": reason, "candidates": candidates[:30],
    }
