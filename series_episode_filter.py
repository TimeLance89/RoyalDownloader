"""Ermittelt auf Serien-Staffelseiten wirklich veröffentlichte Episoden."""

import html
import re


_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_UPCOMING_TEXT_RE = re.compile(
    r"\b(?:demnächst|demnaechst|tba|releases?\s+soon|coming\s+soon)\b",
    re.IGNORECASE,
)


def available_episode_numbers(page_html: str, series_slug: str, season: int) -> list[int]:
    """Liefert Episodennummern ohne angekündigte, noch nicht abrufbare Folgen.

    S.to hinterlegt auch bei kommenden Episoden bereits die spätere URL im
    ``onclick`` der Tabellenzeile. Eine reine URL-Suche zählt diese Folgen
    deshalb fälschlich als verfügbar.
    """
    episode_re = re.compile(
        rf"/serie/{re.escape(series_slug)}/staffel-{int(season)}/episode-(\d+)(?!\d)",
        re.IGNORECASE,
    )
    found = {int(number) for number in episode_re.findall(page_html or "")}
    upcoming: set[int] = set()

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
            upcoming.update(row_numbers)

    return sorted(found - upcoming)
