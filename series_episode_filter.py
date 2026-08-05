"""Ermittelt Episoden und angekündigte Ausstrahlungstermine auf Staffelseiten."""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_UPCOMING_TEXT_RE = re.compile(
    r"\b(?:demnächst|demnaechst|tba|releases?\s+soon|coming\s+soon)\b",
    re.IGNORECASE,
)
_RELEASE_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})"
    r"\s*[~\-–]\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)
try:
    _BERLIN = ZoneInfo("Europe/Berlin")
except ZoneInfoNotFoundError:  # Windows ohne separates tzdata-Paket
    _BERLIN = datetime.now().astimezone().tzinfo


@dataclass(frozen=True)
class EpisodeListing:
    episode: int
    release_at: str = ""
    release_label: str = ""

    @property
    def is_released(self) -> bool:
        if not self.release_at:
            return not self.release_label
        try:
            return datetime.now(_BERLIN) >= datetime.fromisoformat(self.release_at)
        except ValueError:
            return False


def _release_details(row: str) -> tuple[str, str]:
    plain_text = " ".join(html.unescape(_TAG_RE.sub(" ", row)).split())
    match = _RELEASE_DATE_RE.search(plain_text)
    if not match:
        return "", "Demnächst"
    try:
        release = datetime(
            int(match.group("year")), int(match.group("month")), int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")), tzinfo=_BERLIN,
        )
    except ValueError:
        return "", "Demnächst"
    label = (
        f"{match.group('day')}.{match.group('month')}.{match.group('year')}"
        f" · {match.group('hour')}:{match.group('minute')}"
    )
    return release.isoformat(), label


def episode_listings(page_html: str, series_slug: str, season: int) -> list[EpisodeListing]:
    """Liefert veröffentlichte und terminierte Folgen in Episodenreihenfolge."""
    episode_re = re.compile(
        rf"/serie/{re.escape(series_slug)}/staffel-{int(season)}/episode-(\d+)(?!\d)",
        re.IGNORECASE,
    )
    found = {int(number) for number in episode_re.findall(page_html or "")}
    upcoming: dict[int, tuple[str, str]] = {}

    for row_match in _ROW_RE.finditer(page_html or ""):
        row = row_match.group(0)
        row_numbers = {int(number) for number in episode_re.findall(row)}
        if not row_numbers:
            continue
        opening_tag = row.split(">", 1)[0].casefold()
        plain_text = html.unescape(_TAG_RE.sub(" ", row))
        is_upcoming = (
            bool(re.search(r"class\s*=\s*['\"][^'\"]*\bupcoming\b", opening_tag, re.IGNORECASE))
            or "badge-upcoming" in row.casefold()
            or bool(_UPCOMING_TEXT_RE.search(plain_text))
        )
        if is_upcoming:
            details = _release_details(row)
            upcoming.update((number, details) for number in row_numbers)

    return [
        EpisodeListing(number, *(upcoming.get(number) or ("", "")))
        for number in sorted(found)
    ]


def available_episode_numbers(page_html: str, series_slug: str, season: int) -> list[int]:
    """Liefert Episodennummern ohne angekündigte, noch nicht abrufbare Folgen.

    S.to hinterlegt auch bei kommenden Episoden bereits die spätere URL im
    ``onclick`` der Tabellenzeile. Eine reine URL-Suche zählt diese Folgen
    deshalb fälschlich als verfügbar.
    """
    return [item.episode for item in episode_listings(page_html, series_slug, season) if item.is_released]
