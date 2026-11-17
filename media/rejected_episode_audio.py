"""Remember Huhu episodes whose spoken audio contradicted the German label."""

import logging
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit


_log = logging.getLogger(__name__)
_schema = """CREATE TABLE IF NOT EXISTS rejected_huhu_episodes (
    tmdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
    PRIMARY KEY (tmdb_id, season, episode)
)"""


def huhu_episode_identity(url):
    try:
        address = urlsplit(url)
        values = parse_qs(address.query)
        if address.hostname not in {"huhu.to", "www.huhu.to"} or values.get("type") != ["series"]:
            return None
        identity = tuple(int(values[key][0]) for key in ("id", "season", "episode"))
        return identity if all(0 < value < 2**31 for value in identity) else None
    except (ValueError, KeyError):
        return None


def _path():
    from core.config import data_dir

    return data_dir() / "rejected-episode-audio.sqlite3"


def huhu_audio_rejected(identity):
    if identity is None:
        return False
    path = _path()
    if not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(path, timeout=3)) as db:
            return db.execute(
                "SELECT 1 FROM rejected_huhu_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                identity,
            ).fetchone() is not None
    except sqlite3.Error:
        _log.warning("Huhu-Tonspur-Ausschlüsse sind nicht lesbar")
        return True


def reject_huhu_audio(identity):
    if identity is None:
        return False
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=3)) as db, db:
            db.execute(_schema)
            db.execute(
                "INSERT OR IGNORE INTO rejected_huhu_episodes (tmdb_id, season, episode) VALUES (?, ?, ?)",
                identity,
            )
        return True
    except (OSError, sqlite3.Error):
        _log.warning("Huhu-Tonspur-Ausschluss konnte nicht gespeichert werden")
        return False


def huhu_episode_rejected(slug, tmdb_id=""):
    """Resolve a logical episode to Huhu's durable audio exclusion."""
    from providers.models import parse_episode_slug

    parsed = parse_episode_slug(slug)
    if parsed is None:
        return False
    base, season, episode = parsed
    if base.startswith("huhu:"):
        tmdb_id = base.split(":", 2)[1]
    try:
        identity = (int(tmdb_id), season, episode)
    except (TypeError, ValueError):
        return False
    return huhu_audio_rejected(identity)
