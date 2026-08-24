"""
Zwei-Tier Session-Manager für Provider mit Browser-Recovery.

Für SerienStream gilt zusätzlich ein gemeinsamer Session-Pfad nach dem gleichen
Grundprinzip wie StreamFlix: curl_cffi ist der schnelle HTTP-Client, Chromium
nutzt dasselbe persistente Provider-Profil und beide Seiten synchronisieren
Cookies bidirektional. Eine echte interaktive Turnstile/CAPTCHA-Bestätigung
wird dabei nicht automatisiert.
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
from urllib.parse import urlparse

from runtime_paths import data_dir
from network_guard import safe_proxy_url
from serienstream_session_identity import (
    SERIESSTREAM_ACCEPT_LANGUAGE,
    SERIESSTREAM_USER_AGENT,
)

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


_CAPTCHA_MARKERS = [
    "captcha", "hcaptcha", "recaptcha", "turnstile", "cf-chl",
    "bitte bestätige", "kein roboter", "are you human",
]


def _looks_blocked(html: str, status: int) -> bool:
    """True wenn die Antwort wie eine Captcha-/Challenge-Seite aussieht."""
    if status in (403, 429, 503):
        return True
    if not html:
        return False
    if len(html) < 20_000:
        low = html.lower()
        if any(m in low for m in _CAPTCHA_MARKERS):
            return True
    return False


# Erst wenn auch die gemeinsame echte Browser-Session am interaktiven Gate
# hängen bleibt, wird dieser Sentinel an den Circuit-Breaker weitergegeben.
GATE_BLOCKED = "__redirect_gate_blocked__"


class ProviderBlockedError(ConnectionError):
    """Provider blieb auch nach dem vorgesehenen Session-Recovery blockiert."""

    def __init__(self, reason: str, status: int = 0):
        self.reason = str(reason or "provider_blocked")
        self.status = int(status or 0)
        super().__init__(f"Provider blockiert ({self.reason}, HTTP {self.status or 'unbekannt'})")


_GATE_MARKERS = (
    "framebridge", "episode-redirect-gate", "player-prepare-token",
    'window.location.replace("https:\\/\\/serienstream',
)


def _looks_gated(html: str) -> bool:
    if not html or len(html) > 20_000:
        return False
    low = html.lower()
    return any(m in low for m in _GATE_MARKERS)


def _extract_redirect_target(html: str) -> Optional[str]:
    """Zieht das Ziel aus einer Meta-Refresh-/JS-Redirect-Seite."""
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
    """Persistente HTTP-/Browser-Session für einen Provider."""

    TARGET_DOMAIN = "filmpalast.to"
    IMPERSONATE = "chrome136"

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
        self._nodriver_lock = threading.Lock()

    # ------------------------------------------------------------------
    # SerienStream shared Cookie/WebView-style session
    # ------------------------------------------------------------------
    def _browser_cookie_seed(self) -> list[dict]:
        result: list[dict] = []
        jar = getattr(getattr(getattr(self, "_curl", None), "cookies", None), "jar", None)
        if jar is not None:
            try:
                for cookie in jar:
                    domain = str(getattr(cookie, "domain", "") or "").strip()
                    if domain and self.TARGET_DOMAIN not in domain:
                        continue
                    result.append({
                        "name": str(cookie.name),
                        "value": str(cookie.value),
                        "domain": domain or self.TARGET_DOMAIN,
                        "path": str(getattr(cookie, "path", "/") or "/"),
                        "secure": bool(getattr(cookie, "secure", True)),
                    })
            except TypeError:
                result = []
        if result:
            return result
        return [
            {
                "name": str(name),
                "value": str(value),
                "domain": self.TARGET_DOMAIN,
                "path": "/",
                "secure": True,
            }
            for name, value in dict(getattr(self, "_cookies", {}) or {}).items()
        ]

    def _install_shared_browser_cookies(self, cookies: list[dict]) -> list[str]:
        installed: dict[str, str] = {}
        cookie_jar = getattr(getattr(self, "_curl", None), "cookies", None)
        for cookie in cookies or []:
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            domain = str(cookie.get("domain") or self.TARGET_DOMAIN)
            path = str(cookie.get("path") or "/")
            if not name or self.TARGET_DOMAIN not in domain:
                continue
            if cookie_jar is not None and hasattr(cookie_jar, "set"):
                cookie_jar.set(
                    name,
                    value,
                    domain=domain,
                    path=path,
                    secure=bool(cookie.get("secure", True)),
                )
            installed[name] = value
        if installed:
            if not hasattr(self, "_cookies"):
                self._cookies = {}
            self._cookies.update(installed)
            if hasattr(self, "_cookie_file"):
                self._save_cookies()
            self._log(
                f"SerienStream Browser-Session synchronisiert: {len(installed)} Cookie(s)."
            )
        return sorted(installed)

    def _serienstream_browser_html(self, url: str) -> Optional[str]:
        try:
            from serienstream_shared_session import fetch_provider_html

            result = fetch_provider_html(url, self._browser_cookie_seed())
        except Exception as exc:
            logger.debug("SerienStream Browser-HTML Fehler: %s", exc)
            return None
        self._install_shared_browser_cookies(result.cookies)
        if result.html and not result.gated:
            self._log("SerienStream-Seite aus gemeinsamer Chromium-Session übernommen.")
            return result.html
        if result.error:
            logger.debug("SerienStream Browser-HTML: %s", result.error)
        return None

    def _serienstream_browser_redirect(self, url: str, referer: str) -> Optional[str]:
        try:
            from serienstream_shared_session import resolve_provider_redirect

            result = resolve_provider_redirect(
                url,
                referer,
                self._browser_cookie_seed(),
            )
        except Exception as exc:
            logger.debug("SerienStream Browser-Redirect Fehler: %s", exc)
            return None
        self._install_shared_browser_cookies(result.cookies)
        if result.target:
            self._log(f"SerienStream Browser-Session -> {result.target[:70]}")
            return result.target
        if result.gated:
            return GATE_BLOCKED
        if result.error:
            logger.debug("SerienStream Browser-Redirect: %s", result.error)
        return None

    # ------------------------------------------------------------------
    # Öffentliche Methoden
    # ------------------------------------------------------------------
    def get(self, url: str, fast: bool = False) -> str:
        """Holt HTML; SerienStream kann seine persistente Browser-Session nutzen."""
        self._human_delay(fast=fast)
        html, status = self._curl_get(url)

        if _is_cf_challenge(html, status):
            if self.TARGET_DOMAIN == "serienstream.to":
                browser_html = self._serienstream_browser_html(url)
                if browser_html:
                    return browser_html
                reason = "rate_limit" if status == 429 else "captcha_gate"
                raise ProviderBlockedError(reason, status)
            self._log(f"Cloudflare erkannt (Status {status}) → Browser wird gestartet…")
            html = self._nodriver_get(url)
            if html is None:
                raise ConnectionError(
                    f"Cloudflare konnte nicht umgangen werden: {url}\n"
                    "Tipp: Beim nächsten Versuch öffnet sich ein Browser-Fenster – "
                    "bitte nicht schließen bis die Seite geladen ist."
                )

        return html

    def get_json(
        self,
        url: str,
        *,
        referer: Optional[str] = None,
        timeout: int = 8,
    ) -> object:
        """Holt ein öffentliches JSON-Dokument ohne Browser-Eskalation.

        Kleine Datenendpunkte wie der SerienStream-Kalender dürfen weder den
        allgemeinen 25-Sekunden-HTML-Pfad noch eine Chromium-Sitzung starten.
        Der Aufrufer kann dadurch schnell auf seinen letzten Stand ausweichen.
        """
        self._human_delay(fast=True)
        ref = referer or f"https://{self.TARGET_DOMAIN}/"
        headers = self._browser_headers(url, ref)
        headers.update({
            "Accept": "application/json",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
        headers.pop("Sec-Fetch-User", None)
        headers.pop("Upgrade-Insecure-Requests", None)
        try:
            response = self._curl.get(
                url,
                headers=headers,
                timeout=max(1, min(int(timeout), 20)),
                allow_redirects=True,
                proxies={"http": safe_proxy_url(), "https": safe_proxy_url()},
            )
        except Exception as exc:
            raise ConnectionError(f"JSON-Abruf fehlgeschlagen: {url}") from exc

        body = str(getattr(response, "text", "") or "")
        status = int(getattr(response, "status_code", 0) or 0)
        if _is_cf_challenge(body, status):
            reason = "rate_limit" if status == 429 else "captcha_gate"
            raise ProviderBlockedError(reason, status)
        if status < 200 or status >= 300:
            raise ConnectionError(f"JSON-Abruf lieferte HTTP {status or 'unbekannt'}")
        try:
            return response.json()
        except Exception:
            try:
                return json.loads(body)
            except (TypeError, ValueError) as exc:
                raise ValueError("JSON-Antwort ist ungültig") from exc

    def get_redirect_location(self, url: str, referer: Optional[str] = None) -> Optional[str]:
        """Löst eine Weiterleitungs-URL zur finalen externen Ziel-URL auf.

        SerienStream versucht zuerst den schnellen HTTP-Pfad. Liefert dieser
        keine externe Embed-URL, wird vor einem Provider-Cooldown automatisch
        dieselbe persistente Chromium-Session benutzt: Episodenseite laden,
        exakt den vorhandenen Hoster anklicken, Browser-Cookies zurückspielen.
        Nur ein weiterhin interaktives Gate wird als ``GATE_BLOCKED`` gemeldet.
        """
        self._human_delay()
        ref = referer or f"https://{self.TARGET_DOMAIN}/"

        def _external_http_target(candidate: str) -> Optional[str]:
            candidate = str(candidate or "").strip()
            if not candidate:
                return None
            try:
                parsed = urlparse(candidate)
            except ValueError:
                return None
            if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
                return None
            host = parsed.hostname.casefold().rstrip(".")
            provider_host = self.TARGET_DOMAIN.casefold().rstrip(".")
            if host == provider_host or host.endswith("." + provider_host):
                return None
            if host == "challenges.cloudflare.com":
                return None
            return candidate

        if self.TARGET_DOMAIN == "serienstream.to":
            body = ""
            status = 0
            final_url = ""
            try:
                resp = self._curl.get(
                    url,
                    headers=self._browser_headers(url, ref),
                    timeout=25,
                    allow_redirects=True,
                    proxies={"http": safe_proxy_url(), "https": safe_proxy_url()},
                )
                body = str(getattr(resp, "text", "") or "")
                status = int(getattr(resp, "status_code", 0) or 0)
                final_url = str(
                    getattr(resp, "url", "")
                    or getattr(getattr(resp, "request", None), "url", "")
                    or ""
                )
            except Exception as exc:
                logger.debug("Redirect-Kette Fehler: %s", exc)

            external = _external_http_target(final_url)
            if external:
                return external

            external = _external_http_target(_extract_redirect_target(body) or "")
            if external:
                return external

            # Wichtig: Noch NICHT den Circuit-Breaker auslösen. Wie bei einer
            # WebView/OkHttp-Session bekommt das persistente Chromium-Profil
            # zuerst die Chance, denselben Token im normalen Seitenkontext zu
            # öffnen und Cookies an den HTTP-Client zurückzugeben.
            browser_target = self._serienstream_browser_redirect(url, ref)
            if browser_target == GATE_BLOCKED:
                return GATE_BLOCKED
            external = _external_http_target(browser_target or "")
            if external:
                return external

            if _looks_gated(body) or _looks_blocked(body, status):
                return GATE_BLOCKED
            return None

        def _probe() -> tuple[Optional[str], str, int]:
            try:
                resp = self._curl.get(
                    url,
                    headers=self._browser_headers(url, ref),
                    timeout=25,
                    allow_redirects=False,
                    proxies={"http": safe_proxy_url(), "https": safe_proxy_url()},
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
        if _looks_gated(body):
            return GATE_BLOCKED

        if _looks_blocked(body, status):
            self._log(f"Captcha/Block bei Redirect (Status {status}) → Browser holt Clearance …")
            self._nodriver_get(f"https://{self.TARGET_DOMAIN}/")
            loc, body, status = _probe()
            if loc and loc.startswith("http"):
                return loc
            target = _extract_redirect_target(body)
            if target:
                return target
            if _looks_gated(body) or _looks_blocked(body, status):
                return GATE_BLOCKED
        return None

    # ------------------------------------------------------------------
    # Tier 1: curl_cffi
    # ------------------------------------------------------------------
    def _make_curl_session(self):
        from curl_cffi import requests as cffi_req
        session = cffi_req.Session(impersonate=self.IMPERSONATE)
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
                proxies={"http": safe_proxy_url(), "https": safe_proxy_url()},
            )
            return resp.text, resp.status_code
        except Exception as exc:
            logger.debug("curl_cffi Fehler: %s", exc)
            return "", 0

    @staticmethod
    def _browser_headers(url: str, referer: str) -> dict:
        return {
            "User-Agent": SERIESSTREAM_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": SERIESSTREAM_ACCEPT_LANGUAGE,
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
    # Tier 2: nodriver (andere Provider)
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
        nodriver_patch.apply()

        self._log("Browser startet (bitte Fenster nicht schließen)…")

        browser_args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
        ]
        proxy = safe_proxy_url()
        if proxy:
            browser_args.append(f"--proxy-server={proxy}")
        browser = await uc.start(
            headless=True,
            lang="de-DE",
            sandbox=True,
            browser_args=browser_args,
        )

        html = None
        try:
            home = f"https://{self.TARGET_DOMAIN}/"
            if url != home:
                start_tab = await browser.get(home)
                await asyncio.sleep(random.uniform(1.5, 3.0))
                html_home = await start_tab.get_content()
                if _is_cf_challenge(html_home, 200):
                    self._log("CF-Challenge auf Startseite – warte auf Lösung…")
                    await self._wait_for_cf(start_tab, timeout=30)

            tab = await browser.get(url)
            await asyncio.sleep(random.uniform(1.0, 2.5))
            html = await tab.get_content()
            if _is_cf_challenge(html, 200):
                self._log("CF-Challenge auf Zielseite – warte auf Lösung…")
                html = await self._wait_for_cf(tab, timeout=40)
            await self._steal_cookies(browser)
        finally:
            browser.stop()

        return html

    async def _wait_for_cf(self, tab, timeout: int = 30) -> str:
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
                self._curl = self._make_curl_session()
                self._log(f"{len(new)} neue Cookies gesichert – nächste Anfrage ohne Browser.")
        except Exception as exc:
            logger.warning("Cookie-Extraktion fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------------
    # Rate-Limiting
    # ------------------------------------------------------------------
    def _human_delay(self, fast: bool = False):
        elapsed = time.monotonic() - self._last_req
        delay = random.uniform(0.15, 0.35) if fast else random.uniform(0.8, 2.0)
        if not fast and random.random() < 0.1:
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
        self._cookies = {}
        if self._cookie_file.exists():
            self._cookie_file.unlink()
        self._curl = self._make_curl_session()
        self._log("Cookies gelöscht.")
