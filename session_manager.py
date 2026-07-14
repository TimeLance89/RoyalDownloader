"""
Zwei-Tier Session-Manager für filmpalast.to (Cloudflare-Bypass):

  Tier 1 – curl_cffi   Impersoniert Chrome TLS/JA3/HTTP2-Fingerprint.
                        Kein Browser nötig, sehr schnell.
                        Besteht Cloudflare-Checks, die nur auf TLS/Header
                        schauen (der häufigste Fall bei filmpalast.to).

  Tier 2 – nodriver    Echter Chrome via Chrome DevTools Protocol (CDP).
                        Kein WebDriver – daher von CF Bot Management nicht
                        erkannt. Löst JS-Challenges.
                        Wird nur gestartet wenn Tier 1 geblockt wird.

  Cookie-Sharing:       Cookies aus nodriver werden in curl_cffi eingespielt
                        und auf Disk gespeichert → nächste Session startet
                        direkt mit gültiger CF-Clearance.
"""

import asyncio
import json
import logging
import random
import re
import time
import threading
from pathlib import Path
from typing import Callable, Optional

from runtime_paths import data_dir

logger = logging.getLogger(__name__)


def _cookie_file_for(domain: str) -> Path:
    """Pro Domain eigene Cookie-Datei (für spätere Erweiterungen)."""
    safe = domain.replace(".", "_").replace("/", "_")
    return data_dir() / f".cf_cookies_{safe}.json"


# Backward-compat
_COOKIE_FILE = _cookie_file_for("filmpalast.to")

# Texte/Status-Codes die auf eine CF-Challenge hindeuten
_CF_MARKERS = [
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "challenge-form",
    "cf_chl_opt",
    "ray id",
    "enable javascript",
    "cloudflare",
]


def _is_cf_challenge(html: str, status: int) -> bool:
    if status in (403, 503, 429):
        return True
    if len(html) < 30_000:
        low = html.lower()
        return sum(1 for m in _CF_MARKERS if m in low) >= 2
    return False


# Marker für eine Captcha-/Bot-Schutz-Seite (serienstream.to zeigt nach zu
# vielen Abrufen ein Captcha statt des eigentlichen Redirects).
_CAPTCHA_MARKERS = [
    "captcha", "hcaptcha", "recaptcha", "turnstile", "cf-chl",
    "bitte bestätige", "kein roboter", "are you human",
]


def _looks_blocked(html: str, status: int) -> bool:
    """True wenn die Antwort wie eine Captcha-/Challenge-Seite aussieht
    (kleine Seite mit Captcha-Markern oder ein blockierender Statuscode)."""
    if status in (403, 429, 503):
        return True
    if not html:
        return False
    if len(html) < 20_000:
        low = html.lower()
        if any(m in low for m in _CAPTCHA_MARKERS):
            return True
    return False


# Sentinel: der Redirect wurde von einem Anti-Scraping-Gate mit Captcha
# abgefangen (serienstream.to „redirect gate" / frameBridge + Cloudflare
# Turnstile). Kein Retry per Cookie-Clearance möglich – nur Captcha lösen hilft.
GATE_BLOCKED = "__redirect_gate_blocked__"

# Marker der serienstream frameBridge-/Redirect-Gate-Seite.
_GATE_MARKERS = ("framebridge", "episode-redirect-gate", "player-prepare-token",
                 'window.location.replace("https:\\/\\/serienstream')


def _looks_gated(html: str) -> bool:
    if not html or len(html) > 20_000:
        return False
    low = html.lower()
    return any(m in low for m in _GATE_MARKERS)


def _extract_redirect_target(html: str) -> Optional[str]:
    """Zieht das Ziel aus einer Meta-Refresh-/JS-Redirect-Seite (der /r?t=-
    Endpoint liefert genau so eine Weiterleitungsseite)."""
    if not html:
        return None
    for pat in (
        r'http-equiv=["\']refresh["\'][^>]*content=["\']\s*\d+\s*;\s*url=[\'"]?([^\'">]+)',
        r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>\s*Redirecting',
    ):
        m = re.search(pat, html, re.I)
        if m:
            target = m.group(1).strip().strip("'\"")
            if target.startswith("http"):
                return target
    return None


class SessionManager:
    """
    Öffentliche API: nur .get(url) und .cookies (dict).
    Alles andere (Tier-Wechsel, Cookie-Sync) läuft intern.

    Wird für filmpalast.to benutzt; Default-Domain entsprechend gesetzt.
    """

    TARGET_DOMAIN = "filmpalast.to"  # Klassen-Default, wird durch __init__ überschrieben
    IMPERSONATE = "chrome136"  # curl_cffi Browser-Profil

    def __init__(
        self,
        log_cb: Optional[Callable[[str], None]] = None,
        target_domain: str = "filmpalast.to",
    ):
        self._log = log_cb or logger.info
        self.TARGET_DOMAIN = target_domain
        self._cookie_file = _cookie_file_for(target_domain)
        self._cookies: dict = self._load_cookies()
        self._curl = self._make_curl_session()
        self._last_req = 0.0
        self._nodriver_lock = threading.Lock()  # immer nur ein Browser gleichzeitig

    # ------------------------------------------------------------------
    # Öffentliche Methode
    # ------------------------------------------------------------------
    def get(self, url: str, fast: bool = False) -> str:
        """
        Holt url und gibt den HTML-Body zurück.
        Handled CF-Challenges transparent.

        ``fast`` ist für direkt zusammengehörige Folgeseiten gedacht, etwa
        mehrere Staffeln derselben Serie. Die Requests bleiben seriell, nutzen
        aber keinen mehrsekündigen Zufallsabstand.
        """
        self._human_delay(fast=fast)
        html, status = self._curl_get(url)

        if _is_cf_challenge(html, status):
            self._log(f"Cloudflare erkannt (Status {status}) → Browser wird gestartet…")
            html = self._nodriver_get(url)
            if html is None:
                raise ConnectionError(
                    f"Cloudflare konnte nicht umgangen werden: {url}\n"
                    "Tipp: Beim nächsten Versuch öffnet sich ein Browser-Fenster – "
                    "bitte nicht schließen bis die Seite geladen ist."
                )

        return html

    def get_redirect_location(self, url: str, referer: Optional[str] = None) -> Optional[str]:
        """Löst eine Weiterleitungs-URL (z.B. serienstream /r?t=<token>) zur
        Ziel-URL auf, OHNE ihr komplett zu folgen. Reihenfolge:
          1. curl_cffi GET (allow_redirects=False) -> Location-Header.
          2. Meta-Refresh/JS-Redirect im Body.
          3. Bei Captcha/Block: Browser-Fallback holt CF-/Session-Cookies auf
             der Startseite, danach Wiederholung von Schritt 1/2.
        """
        self._human_delay()
        ref = referer or f"https://{self.TARGET_DOMAIN}/"

        def _probe() -> tuple[Optional[str], str, int]:
            try:
                resp = self._curl.get(
                    url,
                    headers=self._browser_headers(url, ref),
                    timeout=25,
                    allow_redirects=False,
                )
                loc = resp.headers.get("Location") or resp.headers.get("location")
                return loc, resp.text, resp.status_code
            except Exception as exc:
                logger.debug("Redirect-Probe Fehler: %s", exc)
                return None, "", 0

        loc, body, status = _probe()
        if loc and loc.startswith("http"):
            return loc
        target = _extract_redirect_target(body)
        if target:
            return target
        # Anti-Scraping-Gate mit Captcha (frameBridge/Turnstile)? -> Signal,
        # damit der Aufrufer sofort aufhört zu hämmern (kein Cookie-Retry hilft).
        if _looks_gated(body):
            return GATE_BLOCKED

        if _looks_blocked(body, status):
            self._log(f"Captcha/Block bei Redirect (Status {status}) → Browser holt Clearance …")
            # Challenge auf der Startseite lösen -> gültige Cookies -> retry.
            self._nodriver_get(f"https://{self.TARGET_DOMAIN}/")
            loc, body, status = _probe()
            if loc and loc.startswith("http"):
                return loc
            target = _extract_redirect_target(body)
            if target:
                return target
        return None

    # ------------------------------------------------------------------
    # Tier 1: curl_cffi
    # ------------------------------------------------------------------
    def _make_curl_session(self):
        from curl_cffi import requests as cffi_req
        session = cffi_req.Session(impersonate=self.IMPERSONATE)
        # Gespeicherte Cookies einsetzen
        for name, value in self._cookies.items():
            session.cookies.set(name, value, domain=self.TARGET_DOMAIN)
        return session

    def _curl_get(self, url: str) -> tuple[str, int]:
        try:
            referer = f"https://{self.TARGET_DOMAIN}/"
            resp = self._curl.get(
                url,
                headers=self._browser_headers(url, referer),
                timeout=25,
                allow_redirects=True,
            )
            return resp.text, resp.status_code
        except Exception as exc:
            logger.debug("curl_cffi Fehler: %s", exc)
            return "", 0

    @staticmethod
    def _browser_headers(url: str, referer: str) -> dict:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Referer": referer,
            "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

    # ------------------------------------------------------------------
    # Tier 2: nodriver  (echter Chrome, kein WebDriver)
    # ------------------------------------------------------------------
    def _nodriver_get(self, url: str) -> Optional[str]:
        """Blockierender Wrapper um den async nodriver-Code."""
        with self._nodriver_lock:
            result: list = [None]
            exc_holder: list = [None]

            def _run():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result[0] = loop.run_until_complete(self._nodriver_async(url))
                except Exception as e:
                    exc_holder[0] = e
                finally:
                    loop.close()

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=120)

            if exc_holder[0]:
                logger.error("nodriver Ausnahme: %s", exc_holder[0])
                return None
            return result[0]

    async def _nodriver_async(self, url: str) -> Optional[str]:
        import nodriver as uc
        import nodriver_patch
        nodriver_patch.apply()  # nodriver-Listener-Busy-Loop-Fix (siehe Modul)

        self._log("Browser startet (bitte Fenster nicht schließen)…")

        browser = await uc.start(
            headless=True,
            lang="de-DE",
            browser_args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-client-side-phishing-detection",
            ],
        )

        html = None
        try:
            # Erst Startseite besuchen (menschliches Muster)
            home = f"https://{self.TARGET_DOMAIN}/"
            if url != home:
                start_tab = await browser.get(home)
                await asyncio.sleep(random.uniform(1.5, 3.0))
                # Warte bis CF-Challenge auf Startseite weg ist
                html_home = await start_tab.get_content()
                if _is_cf_challenge(html_home, 200):
                    self._log("CF-Challenge auf Startseite – warte auf Lösung…")
                    html_home = await self._wait_for_cf(start_tab, timeout=30)

            # Ziel-URL navigieren
            tab = await browser.get(url)
            await asyncio.sleep(random.uniform(1.0, 2.5))

            # Warte bis Challenge gelöst ist
            html = await tab.get_content()
            if _is_cf_challenge(html, 200):
                self._log("CF-Challenge auf Zielseite – warte auf Lösung…")
                html = await self._wait_for_cf(tab, timeout=40)

            # Cookies aus dem Browser holen und persistieren
            await self._steal_cookies(browser)

        finally:
            browser.stop()

        return html

    async def _wait_for_cf(self, tab, timeout: int = 30) -> str:
        """Pollt den Tab-Inhalt bis die CF-Challenge verschwunden ist."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.0)
            html = await tab.get_content()
            if not _is_cf_challenge(html, 200):
                self._log("CF-Challenge gelöst.")
                return html
        self._log("CF-Challenge-Timeout – nehme aktuellen Inhalt.")
        return await tab.get_content()

    async def _steal_cookies(self, browser):
        """Cookies aus dem Browser in curl_cffi-Session und Disk übertragen."""
        try:
            # CDP-Aufruf für alle Cookies
            import nodriver.cdp.network as cdp_net
            raw = await browser.connection.send(cdp_net.get_all_cookies())
            new: dict = {}
            for c in raw:
                domain = getattr(c, "domain", "")
                if self.TARGET_DOMAIN in domain:
                    new[c.name] = c.value

            if new:
                self._cookies.update(new)
                self._save_cookies()
                # curl_cffi-Session neu initialisieren mit frischen Cookies
                self._curl = self._make_curl_session()
                self._log(f"{len(new)} neue Cookies gesichert – nächste Anfrage ohne Browser.")
        except Exception as exc:
            logger.warning("Cookie-Extraktion fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------------
    # Rate-Limiting (menschliches Timing)
    # ------------------------------------------------------------------
    def _human_delay(self, fast: bool = False):
        elapsed = time.monotonic() - self._last_req
        # Zusammengehörige Staffel-Seiten zügig, aber weiterhin seriell laden.
        # Einzelaufrufe behalten das vorsichtige menschliche Timing.
        delay = random.uniform(0.15, 0.35) if fast else random.uniform(0.8, 2.0)
        if not fast and random.random() < 0.1:  # 10% Chance auf längere Pause
            delay += random.uniform(2.0, 5.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_req = time.monotonic()

    # ------------------------------------------------------------------
    # Cookie-Persistenz
    # ------------------------------------------------------------------
    def _load_cookies(self) -> dict:
        if self._cookie_file.exists():
            try:
                data = json.loads(self._cookie_file.read_text())
                logger.info("[%s] Cookies geladen: %d Einträge", self.TARGET_DOMAIN, len(data))
                return data
            except Exception:
                pass
        return {}

    def _save_cookies(self):
        try:
            self._cookie_file.write_text(json.dumps(self._cookies, indent=2))
        except Exception as exc:
            logger.warning("Cookie-Speicherung fehlgeschlagen: %s", exc)

    def clear_cookies(self):
        """Cookies löschen (z. B. bei Login-Problemen)."""
        self._cookies = {}
        if self._cookie_file.exists():
            self._cookie_file.unlink()
        self._curl = self._make_curl_session()
        self._log("Cookies gelöscht.")
