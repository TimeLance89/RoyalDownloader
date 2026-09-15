"""Regeln fuer Film-Abos, Qualitaets-Upgrades und Gesehen-Bereinigung."""

import re


MOVIE_CLEANUP_KEEP = "keep"
MOVIE_CLEANUP_WATCHED = "watched"
MOVIE_CLEANUP_DEFAULT = MOVIE_CLEANUP_KEEP
MOVIE_CLEANUP_LABELS = {
    MOVIE_CLEANUP_KEEP: "Film behalten",
    MOVIE_CLEANUP_WATCHED: "Nach dem Ansehen löschen",
}

MOVIE_QUALITY_BEST = "best"
MOVIE_QUALITY_720P = "720p"
MOVIE_QUALITY_1080P = "1080p"
MOVIE_QUALITY_2160P = "2160p"
MOVIE_QUALITY_DEFAULT = MOVIE_QUALITY_BEST
MOVIE_QUALITY_TARGETS = {
    MOVIE_QUALITY_BEST: 10000,
    MOVIE_QUALITY_720P: 720,
    MOVIE_QUALITY_1080P: 1080,
    MOVIE_QUALITY_2160P: 2160,
}
MOVIE_QUALITY_LABELS = {
    MOVIE_QUALITY_BEST: "Beste verfügbare Qualität",
    MOVIE_QUALITY_720P: "Bis 720p",
    MOVIE_QUALITY_1080P: "Bis 1080p",
    MOVIE_QUALITY_2160P: "Bis 4K",
}


def normalize_movie_cleanup(value) -> str:
    value = str(value or "").strip().casefold()
    return value if value in MOVIE_CLEANUP_LABELS else MOVIE_CLEANUP_DEFAULT


def normalize_movie_quality(value) -> str:
    value = str(value or "").strip().casefold()
    aliases = {"4k": MOVIE_QUALITY_2160P, "uhd": MOVIE_QUALITY_2160P}
    value = aliases.get(value, value)
    return value if value in MOVIE_QUALITY_TARGETS else MOVIE_QUALITY_DEFAULT


def movie_quality_rank(value) -> int:
    """Ordnet uebliche Anbieterbezeichnungen einer vertikalen Aufloesung zu."""
    text = str(value or "").strip().upper()
    if "2160" in text or "4K" in text or "UHD" in text:
        return 2160
    if "1080" in text or "FULL HD" in text or "FHD" in text:
        return 1080
    if "720" in text or re.search(r"(?<!FULL )\bHD\b", text):
        return 720
    if "576" in text:
        return 576
    if "480" in text or "SD" in text or "DVD" in text:
        return 480
    match = re.search(r"(\d{3,4})\s*P?\b", text)
    return int(match.group(1)) if match else 0


def select_upgrade_quality(qualities, current_rank: int, target: str):
    """Liefert die beste echte Verbesserung bis zur konfigurierten Zielstufe."""
    ceiling = MOVIE_QUALITY_TARGETS[normalize_movie_quality(target)]
    ranked = [
        (movie_quality_rank(value), str(value or "").strip())
        for value in qualities
    ]
    eligible = [item for item in ranked if current_rank < item[0] <= ceiling]
    return max(eligible, default=None, key=lambda item: item[0])
