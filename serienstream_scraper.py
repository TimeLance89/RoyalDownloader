"""
Scraper für serienstream.to (s.to) – NUR Serien.

serienstream.to ist die zuverlässigste deutsche Serien-Quelle (großer Katalog,
stabile Hoster), hat aber eine Anti-Bot-Hürde: nach wenigen ungeschützten
Abrufen zeigt die Seite ein Captcha. Deshalb läuft ALLES hier über den
zweistufigen SessionManager (curl_cffi TLS-Impersonation + Rate-Limiting,
nodriver-Browser-Fallback bei Captcha) – exakt wie bei filmpalast.to.

URL-Schema (Stand 2026-07):
  Suche:    /suche?term=<query>                         -> .card.cover-card
  Katalog:  /beliebte-serien  bzw.  /serien (A-Z)
  Genre:    /genre/<genre-slug>?page=N
  Serie:    /serie/<slug>                               (h1, Cover, Staffeln)
  Staffel:  /serie/<slug>/staffel-N                     (Episoden-Links)
  Episode:  /serie/<slug>/staffel-N/episode-M           (Hoster-Buttons)

Hoster-Buttons auf der Episodenseite:
  <button class="link-box" data-provider-name="VOE" data-language-label="Deutsch"
          data-language-id="1" data-play-url="/r?t=<token>">
Der data-play-url zeigt auf einen /r?t=-Redirect, der per 302 auf die echte
Hoster-Embed-URL (z.B. https://voe.sx/e/...) zeigt. Diese Auflösung ist teuer
(1 Request pro Hoster) und captcha-relevant, daher LAZY: wir speichern die
/r?t=-URL als HosterInfo.url und lösen sie erst beim Download auf
(resolve_play_url()), und zwar nur für die Hoster, die wirklich versucht werden.
"""

import html as ihtml
import logging
import re
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from filmpalast_scraper import (
    FilmpalastMovie,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    HosterInfo,
    SeriesEpisode,
    parse_episode_slug,
)
from session_manager import SessionManager, GATE_BLOCKED
from series_episode_filter import available_episode_numbers

logger = logging.getLogger(__name__)

BASE_URL = "https://serienstream.to"
SOURCE_PREFIX = "serienstream:"
REDIRECT_MARKER = "/r?t="  # Kennung eines noch nicht aufgelösten Hoster-Links

# Genre-Anzeigename -> URL-Slug (serienstream nutzt kleingeschriebene Slugs).
GENRES: Dict[str, str] = {
    "Action": "action",
    "Abenteuer": "abenteuer",
    "Animation": "animation",
    "Anime": "anime",
    "Comedy": "comedy",
    "Drama": "drama",
    "Dokumentation": "dokumentation",
    "Familie": "familie",
    "Fantasy": "fantasy",
    "Horror": "horror",
    "Krimi": "krimi",
    "Mystery": "mystery",
    "Reality-TV": "reality-tv",
    "Science Fiction": "science-fiction",
    "Thriller": "thriller",
    "Western": "western",
}

# Sprach-ID -> Anzeige-/Sortier-Label. 1 = Deutsch (Dub) bevorzugt,
# 3 = Deutsch mit Untertitel, 2 = Englisch (Original) als letzter Fallback.
LANG_LABEL = {"1": "Deutsch", "2": "Englisch", "3": "Deutsch (Untertitel)"}
LANG_PRIORITY = {"1": 0, "3": 1, "2": 2}


class SerienstreamScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None,
                 session: Optional[SessionManager] = None):
        self._log = progress_cb or logger.info
        # Session kann von aussen (server.py-Singleton) injiziert werden, damit
        # Cookies/Rate-Limiting/Captcha-Clearance über Aufrufe hinweg erhalten
        # bleiben. Sonst eigene Session anlegen.
        self.session = session or SessionManager(
            target_domain="serienstream.to", log_cb=self._log,
        )
        # A-Z-Katalog ist eine grosse Seite (~2.4 MB); einmal je Prozess cachen.
        self._catalog_cache: Optional[List[FilmpalastSeriesResult]] = None
        # /beliebte-serien (Rubriken Neu/Angesagt) kurz cachen.
        self._beliebte_cache: Optional[tuple] = None
        # True sobald serienstream das Captcha-Gate (Turnstile) aktiviert hat –
        # dann sind ALLE /r?t=-Auflösungen blockiert; nicht weiter hämmern.
        self.gated: bool = False

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def _get_soup(self, url: str, fast: bool = False) -> BeautifulSoup:
        html = self.session.get(url, fast=fast)
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def _abs(href: str) -> str:
        if not href:
            return ""
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE_URL + href
        if href.startswith("http"):
            return href
        return BASE_URL + "/" + href

    @staticmethod
    def _series_slug(value: str) -> str:
        """Extrahiert den Serien-Slug aus Prefix-Slug, Episode-Slug oder URL."""
        value = str(value or "").strip()
        if value.startswith(SOURCE_PREFIX):
            rest = value[len(SOURCE_PREFIX):]
            parsed = parse_episode_slug(rest)
            return parsed[0] if parsed else rest
        m = re.search(r"/serie/(?:stream/)?([^/?#]+)", value)
        if m:
            return m.group(1)
        return value.strip("/")

    def _series_url(self, slug: str) -> str:
        return f"{BASE_URL}/serie/{slug}"

    # ------------------------------------------------------------------
    # Genres
    # ------------------------------------------------------------------
    def list_genres(self) -> List[str]:
        return list(GENRES.keys())

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSeriesResult]:
        slug = GENRES.get((genre or "").strip())
        if not slug:
            # Fallback: eigenen Slug bauen (Umlaute grob ersetzen)
            g = (genre or "").strip().lower()
            g = (g.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                   .replace("ß", "ss"))
            slug = re.sub(r"[^a-z0-9]+", "-", g).strip("-")
        if not slug:
            return []
        page = max(1, int(page))
        url = f"{BASE_URL}/genre/{slug}"
        if page > 1:
            url += f"?page={page}"
        self._log(f"serienstream Genre: {genre} (Seite {page})")
        soup = self._get_soup(url)
        return self._parse_cards(soup)

    # ------------------------------------------------------------------
    # Suche / Listen
    # ------------------------------------------------------------------
    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        query = (query or "").strip()
        if not query:
            return []
        self._log(f"serienstream Serien-Suche: {query}")
        soup = self._get_soup(f"{BASE_URL}/suche?term={quote(query)}")
        results = self._parse_cards(soup)
        self._log(f"  serienstream: {len(results)} Serie(n) gefunden")
        return results

    def _beliebte_soup(self) -> BeautifulSoup:
        """/beliebte-serien einmal laden + kurz cachen (die Seite trägt beide
        Rubriken „Neue Staffeln" und „Meistgesehen", die von zwei Buttons
        genutzt werden – so bleibt es bei einem Request)."""
        import time
        now = time.time()
        if self._beliebte_cache and (now - self._beliebte_cache[0]) < 120:
            return self._beliebte_cache[1]
        soup = self._get_soup(f"{BASE_URL}/beliebte-serien")
        self._beliebte_cache = (now, soup)
        return soup

    def list_new(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        """Rubrik „Neue Staffeln diese Woche" von /beliebte-serien."""
        if page != 1:
            return []
        self._log("serienstream: Neue Staffeln diese Woche")
        cards = self._cards_under_heading(self._beliebte_soup(), "Neue Staffeln")
        results = self._results_from_cards(cards)
        self._log(f"  serienstream: {len(results)} neue Staffel(n)")
        return results

    def list_trending(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        """Rubrik „Meistgesehen gerade" von /beliebte-serien (= angesagt)."""
        if page != 1:
            return []
        self._log("serienstream: Meistgesehen gerade (angesagt)")
        cards = self._cards_under_heading(self._beliebte_soup(), "Meistgesehen")
        results = self._results_from_cards(cards)
        self._log(f"  serienstream: {len(results)} angesagte Serie(n)")
        return results

    # Rückwärtskompatibel: list_series -> angesagte Serien
    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        return self.list_trending(page)

    @staticmethod
    def _cards_under_heading(soup: BeautifulSoup, needle: str) -> list:
        """Alle Serien-Karten (a.show-card) zwischen der h2-Überschrift, die
        `needle` enthält, und der nächsten h2."""
        heads = soup.find_all("h2")
        target = nxt = None
        for i, h in enumerate(heads):
            if needle.lower() in h.get_text(" ", strip=True).lower():
                target = h
                nxt = heads[i + 1] if i + 1 < len(heads) else None
                break
        if target is None:
            return []
        after_t = target.find_all_next("a", class_="show-card")
        after_n = {id(x) for x in (nxt.find_all_next("a", class_="show-card") if nxt else [])}
        return [a for a in after_t if id(a) not in after_n]

    def _results_from_cards(self, cards: list) -> List[FilmpalastSeriesResult]:
        results: List[FilmpalastSeriesResult] = []
        seen: set = set()
        for a in cards:
            res = self._result_from_card(a)
            if res and res.base_slug not in seen:
                seen.add(res.base_slug)
                results.append(res)
        return results

    def list_series_alpha(self, letter: str, page: int = 1) -> List[FilmpalastSeriesResult]:
        """Alphabetischer Katalog. serienstream liefert ALLE Serien auf einer
        Seite (/serien); wir cachen die Liste je Prozess und filtern lokal
        nach Anfangsbuchstabe + paginieren clientseitig (32 pro Seite)."""
        letter = (letter or "A").strip()
        page = max(1, int(page))
        catalog = self._load_catalog()
        if letter in ("0-9", "#"):
            subset = [r for r in catalog if r.title[:1].isdigit()]
        else:
            subset = [r for r in catalog if r.title[:1].upper() == letter.upper()]
        size = 32
        start = (page - 1) * size
        return subset[start:start + size]

    def _load_catalog(self) -> List[FilmpalastSeriesResult]:
        if self._catalog_cache is not None:
            return self._catalog_cache
        self._log("serienstream A-Z-Katalog wird geladen (einmalig) …")
        soup = self._get_soup(f"{BASE_URL}/serien")
        results: List[FilmpalastSeriesResult] = []
        seen: set = set()
        for a in soup.select('a[href^="/serie/"]'):
            href = a.get("href", "")
            m = re.fullmatch(r"/serie/([a-z0-9\-]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            seen.add(slug)
            results.append(self._result(slug, title))
        results.sort(key=lambda r: r.title.casefold())
        self._catalog_cache = results
        self._log(f"  serienstream: {len(results)} Serien im Katalog")
        return results

    def _parse_cards(self, soup: BeautifulSoup) -> List[FilmpalastSeriesResult]:
        """Parst Serien-Cover-Karten aus Such-/Genre-/Listen-Seiten. Echte
        Serien-Karten tragen IMMER ein Cover-<img> mit alt=Titel (egal ob
        .card.cover-card bei der Suche oder a.show-card bei Genre/Beliebt).
        Reine Text-/Episoden-Treffer (z.B. .search-section--episodes, wo der
        Suchbegriff nur in einer Beschreibung vorkommt) haben das nicht und
        werden so zuverlässig ausgefiltert."""
        results: List[FilmpalastSeriesResult] = []
        seen: set = set()
        for a in soup.select('a[href^="/serie/"]'):
            if a.find_parent(class_="search-section--episodes"):
                continue
            res = self._result_from_card(a)
            if res and res.base_slug not in seen:
                seen.add(res.base_slug)
                results.append(res)
        return results

    def _result_from_card(self, a) -> Optional[FilmpalastSeriesResult]:
        """Eine Serien-Cover-Karte -> Ergebnis. Titel aus img[alt] (echte Karten
        haben immer ein Cover mit alt); Karten ohne alt (Text-/Episodentreffer)
        werden verworfen."""
        img = a.find("img")
        alt = ((img.get("alt") if img else "") or "").strip()
        if not alt:
            return None
        slug = self._slug_from_href(a.get("href", ""))
        if not slug:
            return None
        cover_url = ""
        for attribute in ("data-src", "data-lazy-src", "src"):
            candidate = ((img.get(attribute) if img else "") or "").strip()
            if candidate and not candidate.startswith("data:"):
                cover_url = self._abs(candidate)
                break
        return self._result(slug, alt.split("|")[0].strip(), cover_url)

    @staticmethod
    def _slug_from_href(href: str) -> str:
        """Erster Pfad-Teil nach /serie/ – egal ob /serie/<slug>,
        /serie/<slug>/staffel-1 oder /serie/stream/<slug>."""
        m = re.match(r"/serie/(?:stream/)?([a-z0-9\-]+)", href or "")
        if not m:
            return ""
        slug = m.group(1)
        return "" if slug in ("stream",) else slug

    def _result(
        self, slug: str, title: str, cover_url: str = "",
    ) -> FilmpalastSeriesResult:
        return FilmpalastSeriesResult(
            title=f"{title}  [S.to]",
            base_slug=f"{SOURCE_PREFIX}{slug}",
            sample_slug=f"{SOURCE_PREFIX}{slug}",
            sample_url=self._series_url(slug),
            cover_url=cover_url,
        )

    # ------------------------------------------------------------------
    # Serie (Staffeln/Episoden)
    # ------------------------------------------------------------------
    def get_series(self, url_or_slug: str) -> Optional[FilmpalastSeries]:
        started = time.monotonic()
        slug = self._series_slug(url_or_slug)
        if not slug:
            return None
        url = self._series_url(slug)
        self._log(f"Lade Serie (S.to): {url}")
        soup = self._get_soup(url)

        h1 = soup.find("h1")
        series_title = h1.get_text(" ", strip=True) if h1 else slug.replace("-", " ").title()
        cover_url = self._extract_cover(soup)
        description = self._extract_description(soup)
        genres = self._extract_genres(soup)

        # Staffelnummern einsammeln (inkl. evtl. Staffel 0 = Specials)
        season_nums = sorted({
            int(m) for m in re.findall(rf'/serie/{re.escape(slug)}/staffel-(\d+)', str(soup))
        })
        if not season_nums:
            season_nums = [1]

        seasons: Dict[int, List[SeriesEpisode]] = {}
        for sn in season_nums:
            # /serie/<slug> zeigt bereits Staffel 1. Diesen Inhalt nicht noch
            # einmal abrufen; weitere Staffeln mit kurzem seriellen Abstand.
            eps = (
                self._episodes_from_soup(soup, slug, sn)
                if sn == 1
                else self._load_season(slug, sn)
            )
            if eps:
                seasons[sn] = eps

        if not seasons:
            self._log("  Keine Episoden gefunden – keine Serie?")
            return None

        total = sum(len(v) for v in seasons.values())
        elapsed = time.monotonic() - started
        self._log(
            f"  Serie (S.to): «{series_title}» – {len(seasons)} Staffel(n), "
            f"{total} Episoden ({elapsed:.1f}s)"
        )
        return FilmpalastSeries(
            title=series_title, base_slug=f"{SOURCE_PREFIX}{slug}", url=url,
            cover_url=cover_url, description=description, genres=genres,
            seasons=seasons,
        )

    def _load_season(self, slug: str, season: int) -> List[SeriesEpisode]:
        url = f"{BASE_URL}/serie/{slug}/staffel-{season}"
        try:
            soup = self._get_soup(url, fast=True)
        except Exception as exc:
            self._log(f"  Staffel {season} nicht ladbar: {exc}", )
            return []
        return self._episodes_from_soup(soup, slug, season)

    @staticmethod
    def _episodes_from_soup(
        soup: BeautifulSoup, slug: str, season: int,
    ) -> List[SeriesEpisode]:
        # S.to trägt auch für noch unveröffentlichte "Demnächst"-Zeilen schon
        # eine Episoden-URL im onclick ein. Nur tatsächlich abrufbare Zeilen
        # übernehmen, sonst landen zukünftige Folgen in Abo und Downloadqueue.
        ep_nums = available_episode_numbers(str(soup), slug, season)
        eps: List[SeriesEpisode] = []
        for en in ep_nums:
            eps.append(SeriesEpisode(
                season=season, episode=en,
                slug=f"{SOURCE_PREFIX}{slug}-s{season:02d}e{en:02d}",
                url=f"{BASE_URL}/serie/{slug}/staffel-{season}/episode-{en}",
                release_name="",
            ))
        return eps

    # ------------------------------------------------------------------
    # Episode -> FilmpalastMovie (mit lazy Hoster-URLs)
    # ------------------------------------------------------------------
    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        parsed = None
        raw = url_or_slug[len(SOURCE_PREFIX):] if url_or_slug.startswith(SOURCE_PREFIX) else url_or_slug
        parsed = parse_episode_slug(raw)
        if parsed:
            slug, season, episode = parsed
            url = f"{BASE_URL}/serie/{slug}/staffel-{season}/episode-{episode}"
            series_title = slug.replace("-", " ").title()
        elif url_or_slug.startswith("http"):
            url = url_or_slug
            m = re.search(r"/serie/(?:stream/)?([^/]+)/staffel-(\d+)/episode-(\d+)", url)
            if not m:
                return None
            slug, season, episode = m.group(1), int(m.group(2)), int(m.group(3))
            series_title = slug.replace("-", " ").title()
        else:
            return None

        self._log(f"Lade Episode (S.to): S{season:02d}E{episode:02d}")
        soup = self._get_soup(url)

        # Serientitel sauberer aus H1 der Episodenseite ziehen falls vorhanden
        h1 = soup.find("h1")
        if h1:
            t = h1.get_text(" ", strip=True)
            if t:
                series_title = t

        hosters = self._extract_hosters(soup)
        if not hosters:
            self._log("  Keine Hoster auf der Episodenseite gefunden.")
            return None

        return FilmpalastMovie(
            title=f"{series_title} S{season:02d}E{episode:02d}",
            url=url,
            cover_url=self._extract_cover(soup),
            hosters=hosters,
        )

    def _extract_hosters(self, soup: BeautifulSoup) -> List[HosterInfo]:
        """Parst die Hoster-Buttons. URLs bleiben als /r?t=-Redirect (lazy);
        Auflösung erst beim Download via resolve_play_url()."""
        hosters: List[HosterInfo] = []
        seen: set = set()
        for btn in soup.select("[data-play-url]"):
            play = ihtml.unescape(btn.get("data-play-url", "").strip())
            if not play:
                continue
            provider = (btn.get("data-provider-name") or "").strip() or "Hoster"
            lang_id = str(btn.get("data-language-id") or "1")
            language = (btn.get("data-language-label")
                        or LANG_LABEL.get(lang_id, "")).strip()
            key = (provider.lower(), lang_id, play)
            if key in seen:
                continue
            seen.add(key)
            hosters.append(HosterInfo(
                name=provider,
                url=self._abs(play),
                language=language,
                quality="",
            ))
        # Sortierung: bevorzugte Sprache (Deutsch-Dub) zuerst, dann Hoster-
        # Priorität. hoster_intel.rank() sortiert später final nach Score,
        # aber diese Vor-Sortierung hält die Reihenfolge innerhalb gleicher
        # Scores stabil (Dub vor Sub vor Englisch).
        def sort_key(h: HosterInfo):
            lang_id = "1"
            for k, v in LANG_LABEL.items():
                if v == h.language:
                    lang_id = k
                    break
            return (LANG_PRIORITY.get(lang_id, 3), h.name.lower())

        hosters.sort(key=sort_key)
        return hosters

    # ------------------------------------------------------------------
    # Lazy Redirect-Auflösung (/r?t= -> echte Hoster-Embed-URL)
    # ------------------------------------------------------------------
    @staticmethod
    def is_redirect_url(url: str) -> bool:
        return REDIRECT_MARKER in (url or "")

    def resolve_play_url(self, url: str, referer: str = "") -> Optional[str]:
        """Löst einen /r?t=-Redirect zur echten Hoster-Embed-URL auf.
        Geht durch den SessionManager (Rate-Limiting + Captcha-Fallback).
        Setzt self.gated=True, wenn serienstream das Turnstile-Gate aktiviert
        hat (dann liefern ALLE Auflösungen nur noch die frameBridge-Seite)."""
        if not self.is_redirect_url(url):
            return url
        try:
            target = self.session.get_redirect_location(url, referer=referer or BASE_URL + "/")
        except Exception as exc:
            self._log(f"  S.to Redirect-Auflösung fehlgeschlagen: {exc}")
            return None
        if target == GATE_BLOCKED:
            if not self.gated:
                self._log("  serienstream Captcha-Gate (Turnstile) aktiv – IP vorübergehend geflaggt.")
            self.gated = True
            return None
        if target:
            self._log(f"  S.to -> {target[:70]}")
        return target

    def reset_gate(self) -> None:
        self.gated = False

    # ------------------------------------------------------------------
    # Metadaten-Helfer
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_cover(soup: BeautifulSoup) -> str:
        # Poster (portrait, /channel/) bevorzugen; /backdrop/ (breites Hero-Bild)
        # nur als Notnagel.
        backdrop = ""
        for img in soup.select("img[data-src*='/media/images'], img[src*='/media/images']"):
            src = img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:"):
                continue
            if "/channel/" in src:
                return SerienstreamScraper._abs(src)
            if not backdrop:
                backdrop = src
        return SerienstreamScraper._abs(backdrop)

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str:
        for sel in ("[itemprop=description]", ".seri_des", "[class*=description]"):
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt and len(txt) > 20:
                    return txt
        return ""

    @staticmethod
    def _extract_genres(soup: BeautifulSoup) -> List[str]:
        genres: List[str] = []
        for a in soup.select('a[href^="/genre/"]'):
            g = a.get_text(strip=True)
            if g and g not in genres:
                genres.append(g)
        return genres
