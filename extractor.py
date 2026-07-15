"""
VOE.SX Stream-URL-Extraktor.

Zwei-Stufen-Ansatz:
  Stufe 1 (schnell): Regex-Methoden direkt auf dem HTML.
  Stufe 2 (Fallback): Browser-Pool mit nodriver + CDP. Einmal pro
                      Download-Queue gestartet, fängt die m3u8-URL
                      für jeden Film ab, schließt am Ende.

Gibt zurück: (stream_url, "hls" | "mp4") oder None.
"""

import asyncio
import ast
import base64
import json
import logging
import os
import random
import re
import shutil
import string
import threading
import time
import warnings
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

logger = logging.getLogger(__name__)

# Erkennungsstrings für Test-/Platzhalter-Videos (kein echter Stream)
_TEST_INDICATORS = [
    "test-videos.co.uk",
    "bigbuckbunny",
    "sample-videos.com",
    "cdn.plyr.io",  # Plyr.js Player-Library lädt "blank.mp4" als Platzhalter, bevor die echte Quelle gesetzt wird
]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _decode_rot13(s: str) -> str:
    result = []
    for c in s:
        if "a" <= c <= "z":
            result.append(chr((ord(c) - ord("a") + 13) % 26 + ord("a")))
        elif "A" <= c <= "Z":
            result.append(chr((ord(c) - ord("A") + 13) % 26 + ord("A")))
        else:
            result.append(c)
    return "".join(result)


def _safe_b64decode(s: str) -> str:
    s = s.strip().replace("-", "+").replace("_", "/")
    padding = (4 - len(s) % 4) % 4
    try:
        return base64.b64decode(s + "=" * padding).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _is_test_url(url: str) -> bool:
    return any(t in url.lower() for t in _TEST_INDICATORS)


def _make_session():
    from curl_cffi import requests as cr
    return cr.Session(impersonate="chrome136")


def _chrome_executable() -> Optional[str]:
    """Liefert ein explizites Chrome/Chromium-Binary, sofern auffindbar."""
    configured = os.environ.get("CHROME_PATH", "").strip()
    if configured:
        configured = os.path.abspath(
            os.path.expanduser(os.path.expandvars(configured))
        )
        if not os.path.isfile(configured):
            raise RuntimeError(f"CHROME_PATH existiert nicht: {configured}")
        if not os.access(configured, os.X_OK):
            raise RuntimeError(f"CHROME_PATH ist nicht ausführbar: {configured}")
        return configured

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome-stable",
        "google-chrome",
        "chrome",
    ):
        executable = shutil.which(name)
        if executable:
            return executable
    return None


def _fetch_html(session, url: str, referer: str = "https://filmpalast.to/") -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9",
        "Referer": referer,
    }
    resp = session.get(url, headers=headers, timeout=20, allow_redirects=True)
    return resp.text


def _find_js_redirect_url(html: str, base_url: str = "") -> Optional[str]:
    """Findet einfache JS-/Meta-Redirect-Ziele, ohne sie direkt zu laden."""
    if len(html) > 10_000:
        return None
    for pat in [
        r"window\.location(?:\.href)?\s*=\s*['\"](?!#)([^'\"]+)['\"]",
        r'content=["\']0;\s*url=([^"\']+)["\']',
    ]:
        m = re.search(pat, html, re.I)
        if not m:
            continue
        target = m.group(1).strip()
        if target:
            return urljoin(base_url, target)
    return None


def _follow_js_redirect(html: str, session) -> str:
    """Folge einfachen JS window.location Redirects (VOE Redirect-Seite)."""
    target = _find_js_redirect_url(html)
    if target and target.startswith("http"):
        logger.debug("JS-Redirect → %s", target)
        try:
            return _fetch_html(session, target)
        except Exception as exc:
            logger.warning("JS-Redirect fehlgeschlagen: %s", exc)
    return html


def _js_literal(value: str) -> str:
    try:
        return ast.literal_eval(value)
    except Exception:
        return value.strip("\"'").encode("utf-8", errors="ignore").decode(
            "unicode_escape", errors="ignore"
        )


def _to_radix(value: int, radix: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    out = []
    while value:
        value, rem = divmod(value, radix)
        out.append(digits[rem])
    return "".join(reversed(out))


def _unpack_packer_scripts(html: str) -> List[str]:
    """Entpackt klassische eval(function(p,a,c,k,e,d){...}) Player-Skripte."""
    unpacked = []
    pattern = re.compile(
        r"eval\(function\(p,a,c,k,e,d\).*?\(\s*"
        r"(?P<p>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\s*,\s*"
        r"(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*"
        r"(?P<k>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\.split\('\|'\)",
        re.S,
    )
    for m in pattern.finditer(html):
        radix = int(m.group("a"))
        count = int(m.group("c"))
        if radix < 2 or radix > 36:
            continue
        code = _js_literal(m.group("p"))
        keys = _js_literal(m.group("k")).split("|")
        for idx in range(count - 1, -1, -1):
            if idx >= len(keys) or not keys[idx]:
                continue
            token = _to_radix(idx, radix)
            code = re.sub(rf"\b{re.escape(token)}\b", keys[idx], code)
        unpacked.append(code)
    return unpacked


def _best_direct_media_url(text: str, extension: str) -> Optional[str]:
    """Findet direkte Medien-URLs, auch in JWPlayer-Qualitaetslisten.

    Einige Player liefern alle Varianten in einem String wie
    ``[360p]https://...mp4/,[1080p]https://...mp4/``. Die alte, sehr breite
    Regex hat daraus eine einzige ungueltige URL gemacht. Hier werden die
    Varianten getrennt und die hoechste deklarierte Aufloesung gewaehlt.
    """
    pattern = re.compile(
        rf"(?:\[(?P<quality>\d{{3,4}})p\])?\s*"
        rf"(?P<url>https?://[^\s\"'<> ,\]]+\.{re.escape(extension)}"
        rf"(?:[/?][^\s\"'<> ,\]]*)?)",
        re.I,
    )
    candidates = []
    for index, match in enumerate(pattern.finditer(text or "")):
        url = match.group("url")
        if _is_test_url(url):
            continue
        quality = int(match.group("quality") or 0)
        if not quality:
            hinted = re.search(r"(?:^|[_-])(2160|1440|1080|720|480|360)p?(?:[_./?-]|$)", url, re.I)
            quality = int(hinted.group(1)) if hinted else 0
        candidates.append((quality, index, url))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


# ---------------------------------------------------------------------------
# Regex-Extraktion
# ---------------------------------------------------------------------------
def _extract_regex(html: str) -> Optional[Tuple[str, str]]:
    """Versucht alle bekannten VOE-Verschlüsselungsmuster."""

    # 1. var sources = {...}
    m = re.search(r"var\s+sources\s*=\s*(\{[^}]+\})", html)
    if m:
        try:
            data = json.loads(m.group(1))
            for key in ("hls", "m3u8"):
                if key in data and not _is_test_url(data[key]):
                    return data[key], "hls"
            if "mp4" in data and not _is_test_url(data["mp4"]):
                return data["mp4"], "mp4"
        except json.JSONDecodeError:
            pass

    # 2. 'hls': '...' Objekt-Literal
    m = re.search(r"['\"]hls['\"]\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html)
    if m and not _is_test_url(m.group(1)):
        return m.group(1), "hls"

    # 3. Direkte .m3u8 URL im HTML
    for m in re.finditer(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", html):
        if not _is_test_url(m.group(0)):
            return m.group(0), "hls"

    # 3b. Gepackte Player-Skripte, z.B. Moflix/StreamRuby Mirrors.
    for unpacked in _unpack_packer_scripts(html):
        for m in re.finditer(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", unpacked):
            if not _is_test_url(m.group(0)):
                return m.group(0), "hls"
        for m in re.finditer(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*", unpacked):
            if not _is_test_url(m.group(0)):
                return m.group(0), "mp4"

    # 4. a168c Base64-Enkodierung
    m = re.search(r"a168c\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", html)
    if m:
        decoded = _safe_b64decode(m.group(1))[::-1]
        try:
            data = json.loads(decoded)
            for key in ("hls", "m3u8"):
                if key in data and not _is_test_url(data[key]):
                    return data[key], "hls"
            if "mp4" in data and not _is_test_url(data["mp4"]):
                return data["mp4"], "mp4"
        except json.JSONDecodeError:
            for m2 in re.finditer(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", decoded):
                if not _is_test_url(m2.group(0)):
                    return m2.group(0), "hls"

    # 5. MKGMa (ROT13 → strip _ → b64 → char-shift → reverse → b64)
    m = re.search(r"MKGMa\s*=\s*['\"]([A-Za-z0-9+/=_]+)['\"]", html)
    if m:
        step = _safe_b64decode(
            "".join(chr(ord(c) - 3) for c in _safe_b64decode(
                _decode_rot13(m.group(1)).replace("_", "")
            )[::-1])
        )
        for m2 in re.finditer(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", step):
            if not _is_test_url(m2.group(0)):
                return m2.group(0), "hls"
        try:
            data = json.loads(step)
            if "hls" in data and not _is_test_url(data["hls"]):
                return data["hls"], "hls"
        except json.JSONDecodeError:
            pass

    # 6. Embedded JSON scripts (ROT13 + b64 Varianten)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/json"):
        raw = (script.string or "").strip()
        for transform in [lambda x: x, _decode_rot13,
                          lambda x: _safe_b64decode(_decode_rot13(x))]:
            try:
                data = json.loads(transform(raw))
                if isinstance(data, dict):
                    for key in ("hls", "m3u8", "mp4", "video_url"):
                        if key in data and not _is_test_url(str(data[key])):
                            kind = "hls" if key in ("hls", "m3u8") else "mp4"
                            return data[key], kind
            except Exception:
                pass

    # 7. Direkte MP4 URL (echter Inhalt, kein Test). Qualitaetslisten werden
    # in einzelne URLs zerlegt und nach Aufloesung priorisiert.
    direct_mp4 = _best_direct_media_url(html, "mp4")
    if direct_mp4:
        return direct_mp4, "mp4"

    return None


# ---------------------------------------------------------------------------
# VOE-Verfügbarkeits-Check (schnell, ohne Browser)
# ---------------------------------------------------------------------------
VOE_OK = "ok"           # 200, Film lebt
VOE_NOT_FOUND = "404"   # 404, Film tot – User informieren
VOE_UNKNOWN = "unknown" # Timeout, 5xx, etc.


def pre_check_voe(url: str, session=None, timeout: float = 8.0) -> str:
    """
    Schneller HTTP-Probe um zu prüfen ob eine VOE.SX-URL noch lebt.
    Kein Browser nötig.
    """
    if not url:
        return VOE_UNKNOWN
    try:
        if session is None:
            session = _make_session()
        resp = session.get(
            url,
            headers={"Referer": "https://filmpalast.to/"},
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status_code == 404:
            return VOE_NOT_FOUND
        if resp.status_code == 200:
            if len(resp.text) > 10_000 and "404" in resp.text and "not found" in resp.text.lower():
                return VOE_NOT_FOUND
            return VOE_OK
        return VOE_UNKNOWN
    except Exception as exc:
        logger.debug("pre_check_voe: %s", exc)
        return VOE_UNKNOWN


# ---------------------------------------------------------------------------
# Browser-Pool (nodriver + CDP, persistent über mehrere Extraktionen)
# ---------------------------------------------------------------------------
class VOEBrowserPool:
    """
    Hält eine Chrome-Instanz und stellt sie für mehrere Extraktionen
    zur Verfügung. Wird einmal pro Download-Queue gestartet und
    explizit per .close() beendet.

    Verwendung:
        pool = VOEBrowserPool()
        try:
            result = pool.extract(url)
        finally:
            pool.close()
    """

    def __init__(self, log_cb: Optional[Callable[[str], None]] = None, setup_voe: bool = True):
        self._log = log_cb or logger.info
        self._setup_voe = setup_voe
        self._browser = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        # Zwei Locks: einer fuer thread-safe extract() von aussen, einer
        # innerhalb des asyncio-Loops um die Coroutines zu serialisieren.
        # Hintergrund: nodriver's Background-Listener und tab.send() rufen
        # beide ws.recv() auf, was bei "concurrent" Calls in websockets
        # crashed. Mit asyncio.Lock serialisieren wir die Calls im Loop,
        # sodass jeweils nur ein ws.recv() aktiv ist.
        self._lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None  # wird im Loop erstellt
        self._ready = False
        self._closed = False

    def extract(
        self,
        target_url: str,
        wait_seconds: int = 25,
        referer: str = "",
    ) -> Optional[Tuple[str, str]]:
        """
        Extrahiert die Stream-URL der gegebenen VOE-Seite.
        Blockiert; thread-safe.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Pool ist geschlossen")
            if not self._ready:
                self._start()
            return self._do_extract(target_url, wait_seconds, referer)

    def close(self):
        """Browser stoppen, Thread sauber beenden."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._browser is not None and self._loop is not None:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._async_browser_stop(), self._loop
                    )
                    future.result(timeout=10)
                except Exception as exc:
                    logger.warning("Browser-Stop Fehler: %s", exc)
            if self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._browser = None
            self._loop = None
            self._thread = None
            self._ready = False

    def _start(self):
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                self._start_once()
                return
            except Exception as exc:
                last_exc = exc
                self._cleanup_failed_start()
                if attempt == 0:
                    reason = " ".join(str(exc).split())
                    self._log(
                        f"Chrome-Start fehlgeschlagen ({reason[:180]}) – "
                        "neuer Versuch …"
                    )
                    time.sleep(1)
        raise last_exc or RuntimeError("Chrome konnte nicht gestartet werden")

    def _start_once(self):
        ready_evt = threading.Event()
        exc_holder: list = [None]

        def _thread_main():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._browser = self._loop.run_until_complete(
                    self._async_browser_start()
                )
                if self._setup_voe:
                    self._loop.run_until_complete(self._async_setup_voe_token())
                self._ready = True
                ready_evt.set()
                self._loop.run_forever()
            except Exception as exc:
                exc_holder[0] = exc
                ready_evt.set()
            finally:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if self._loop is not None:
                        try:
                            self._loop.close()
                        except Exception:
                            pass

        self._thread = threading.Thread(target=_thread_main, daemon=True)
        self._thread.start()

        if not ready_evt.wait(timeout=90):
            raise RuntimeError("Browser-Start Timeout (90s)")
        if exc_holder[0]:
            raise exc_holder[0]

    def _cleanup_failed_start(self):
        """Räumt einen unvollständigen nodriver-Start vor dem Retry auf."""
        loop = self._loop
        if loop is not None and not loop.is_closed() and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._browser = None
        self._loop = None
        self._thread = None
        self._async_lock = None
        self._ready = False

    async def _async_browser_start(self):
        import nodriver_patch
        nodriver_patch.ensure_cdp_utf8()
        import nodriver as uc
        nodriver_patch.apply()  # nodriver-Listener-Busy-Loop-Fix (siehe Modul)
        executable = _chrome_executable()
        if executable:
            self._log(f"Starte Chrome: {executable}")
        else:
            self._log("Starte Chrome (automatische Binary-Suche) …")

        options = {
            "headless": True,
            "lang": "de-DE",
            # Chromium verweigert als root den Start mit aktiver Sandbox.
            # Explizit setzen statt von nodrivers Root-Erkennung abzuhängen.
            "sandbox": False,
            "browser_args": [
                "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
                "--no-first-run",
                "--disable-background-networking",
                "--disable-extensions",
                "--disable-gpu",
                "--window-size=1280,900",
            ],
        }
        if executable:
            options["browser_executable_path"] = executable

        # Browser selbst instanziieren: uc.start() verwirft die Instanz bei
        # Fehlern und damit auch Chromiums stderr. So landet künftig die echte
        # Ursache im Log statt nodrivers generischem Root-Hinweis.
        config = uc.Config(**options)
        browser = uc.Browser(config)
        try:
            await browser.start()
            return browser
        except Exception as exc:
            diagnostic = await self._failed_browser_diagnostic(browser)
            detail = diagnostic or "Chromium beendete sich ohne Fehlerausgabe"
            raise RuntimeError(f"Chromium-Start fehlgeschlagen: {detail}") from exc

    @staticmethod
    async def _failed_browser_diagnostic(browser) -> str:
        """Stoppt einen Fehlstart und liest die letzten Chromium-Meldungen."""
        process = getattr(browser, "_process", None)
        if process is None:
            return "Chromium-Prozess wurde nicht erzeugt"

        try:
            if process.returncode is None:
                process.terminate()
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                _, stderr = await process.communicate()
        except Exception as exc:
            return f"Prozessdiagnose fehlgeschlagen: {exc}"
        finally:
            # Verhindert, dass nodrivers atexit-Handler den bereits beendeten
            # Fehlstart später noch einmal behandelt.
            try:
                import nodriver as uc
                uc.util.get_registered_instances().discard(browser)
            except Exception:
                pass
            browser._process = None
            browser._process_pid = None

        message = stderr.decode("utf-8", errors="replace") if stderr else ""
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        return " | ".join(lines[-6:])[-1200:]

    async def _async_setup_voe_token(self):
        """Einmal pro Session: VOE-Token holen, im localStorage setzen."""
        self._log("Richte VOE Token ein …")
        try:
            await self._browser.get("https://voe.sx/")
            await asyncio.sleep(2)
            try:
                await self._browser.get("https://voe.sx/api2/session/generate-token")
                await asyncio.sleep(2)
            except Exception as exc:
                self._log(f"  Token-API nicht erreichbar: {exc}")
        except Exception as exc:
            self._log(f"  VOE-Setup teilweise fehlgeschlagen: {exc}")

    async def _async_browser_stop(self):
        try:
            if self._browser is not None:
                self._browser.stop()
        except Exception:
            pass

    def _do_extract(
        self, target_url: str, wait_seconds: int, referer: str = "",
    ) -> Optional[Tuple[str, str]]:
        future = asyncio.run_coroutine_threadsafe(
            self._async_extract(target_url, wait_seconds, referer), self._loop
        )
        try:
            return future.result(timeout=wait_seconds + 20)
        except Exception as exc:
            logger.error("Extraktions-Fehler: %s", exc)
            return None

    async def _async_extract(
        self, target_url: str, wait_seconds: int, referer: str = "",
    ) -> Optional[Tuple[str, str]]:
        import nodriver.cdp.network as cdp_net

        # Async-Lock im Loop: serialisiert Coroutines damit immer nur
        # ein ws.send/recv aktiv ist. Ohne das crashed websockets mit
        # "cannot call get() concurrently" wenn mehrere Calls ueberlappen.
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            return await self._async_extract_inner(target_url, wait_seconds, referer)

    async def _async_extract_inner(
        self, target_url: str, wait_seconds: int, referer: str = "",
    ) -> Optional[Tuple[str, str]]:
        import nodriver.cdp.network as cdp_net
        import nodriver.cdp.page as cdp_page

        m3u8_urls: List[str] = []
        mp4_urls: List[str] = []

        def _remember_stream(url: str, source: str):
            if _is_test_url(url):
                return
            if ".m3u8" in url.lower():
                if not m3u8_urls:
                    self._log(f"M3U8 abgefangen ({source}): {url[:80]}")
                m3u8_urls.append(url)
            elif re.search(r"\.mp4(\?|$)", url, re.I):
                if not mp4_urls:
                    self._log(f"MP4 abgefangen ({source}): {url[:80]}")
                mp4_urls.append(url)

        def _on_request(event: cdp_net.RequestWillBeSent):
            _remember_stream(event.request.url, "request")

        def _on_response(event: cdp_net.ResponseReceived):
            _remember_stream(event.response.url, "response")

        self._log(f"Lade VOE: {target_url[:70]}")
        tab = await self._browser.get("about:blank", new_tab=True)
        try:
            # Handler vor der Navigation registrieren, sonst gehen fruehe
            # Stream-Requests bei schnellen Redirect-Ketten verloren.
            tab.add_handler(cdp_net.RequestWillBeSent, _on_request)
            tab.add_handler(cdp_net.ResponseReceived, _on_response)
            await tab.send(cdp_net.enable())
            await tab.send(cdp_page.navigate(target_url, referrer=referer or None))

            for tick in range(wait_seconds):
                await asyncio.sleep(1)
                if m3u8_urls or mp4_urls:
                    break
                if tick == 5:
                    try:
                        await tab.evaluate(
                            "document.querySelector('video')?.play();"
                            "document.querySelectorAll('[class*=play],[id*=play]')"
                            ".forEach(e => e.click());"
                        )
                    except Exception:
                        pass
        finally:
            # Immer frischer Tab pro Film. Das verhindert den beobachteten
            # "Session with given id not found"-Fehler nach closeTarget.
            try:
                await tab.close()
            except Exception:
                pass

        if m3u8_urls:
            return m3u8_urls[0], "hls"
        if mp4_urls:
            return mp4_urls[0], "mp4"
        self._log("Keine Stream-URL gefunden.")
        return None


# ---------------------------------------------------------------------------
# DoodStream-Familie (dood.to, vide0.net und Mirrors – gleicher Handshake)
# ---------------------------------------------------------------------------
def extract_doodstream_url(
    embed_url: str,
    session=None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Tuple[str, str]]:
    """
    Löst den DoodStream "/pass_md5"-Handshake auf (yt-dlp's DoodStream-Extractor
    wurde entfernt, daher hier nachgebaut):
      1. Embed-HTML laden, den `$.get('/pass_md5/<token>')`-Aufruf finden.
      2. pass_md5-Endpoint abrufen (Referer = Embed-URL) -> Basis-CDN-URL.
      3. Zufälligen Suffix + Token + Expiry-Timestamp anhängen -> fertige,
         zeitlich begrenzte MP4-URL.
    """
    _log = log_cb or logger.info
    if session is None:
        session = _make_session()

    try:
        html = _fetch_html(session, embed_url, referer=embed_url)
    except Exception as exc:
        _log(f"DoodStream-Embed nicht ladbar: {exc}")
        return None

    m = re.search(r"\$\.get\('(/pass_md5/[^']+)'", html)
    if not m:
        _log("DoodStream: kein pass_md5-Aufruf gefunden.")
        return None
    pass_path = m.group(1)
    parsed = urlparse(embed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        resp = session.get(base + pass_path, headers={"Referer": embed_url}, timeout=20)
        resp.raise_for_status()
        data_base = resp.text.strip()
    except Exception as exc:
        _log(f"DoodStream pass_md5 fehlgeschlagen: {exc}")
        return None

    if not data_base.startswith("http"):
        _log("DoodStream: unerwartete pass_md5-Antwort.")
        return None

    token = pass_path.rsplit("/", 1)[-1]
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    final_url = f"{data_base}{rand}?token={token}&expiry={int(time.time() * 1000)}"
    return final_url, "mp4"


def extract_vidara_url(
    embed_url: str,
    session=None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Tuple[str, str]]:
    """VIDARA (Player „Vidara", Domains wie vidmatrixa.com – rotieren).
    yt-dlp kennt diesen Hoster nicht. Mechanik der Embed-Seite:
      filecode = letztes Pfad-Segment; POST /api/stream mit
      {filecode, device:"web"} -> JSON mit `streaming_url` (HLS master.m3u8).
    Der Token ist IP-gebunden – API-Call und Download müssen von derselben IP
    kommen (im Container beides der Fall)."""
    _log = log_cb or logger.info
    if session is None:
        session = _make_session()
    parsed = urlparse(embed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    filecode = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not filecode:
        _log("VIDARA: kein filecode in der Embed-URL.")
        return None
    try:
        # Embed einmal laden (Cookies/Referer), dann die JSON-API abfragen.
        session.get(embed_url, headers={"Referer": "https://filmpalast.to/"}, timeout=20)
        resp = session.post(
            f"{base}/api/stream",
            headers={
                "Content-Type": "application/json",
                "Referer": embed_url,
                "Origin": base,
                "X-Requested-With": "XMLHttpRequest",
            },
            data=json.dumps({"filecode": filecode, "device": "web"}),
            timeout=20,
        )
        data = resp.json()
    except Exception as exc:
        _log(f"VIDARA API fehlgeschlagen: {exc}")
        return None

    stream = (data or {}).get("streaming_url") if isinstance(data, dict) else None
    if not stream or not str(stream).startswith("http"):
        _log("VIDARA: keine streaming_url in der Antwort.")
        return None
    # VIDARA liefert HLS auch dann, wenn die signierte URL nicht auf .m3u8
    # endet (typisch: /hls/<token>). Als MP4 markiert würde nach einem
    # yt-dlp-Fehler fälschlich der Direct-Download auf das Manifest losgehen.
    return stream, "hls"


def extract_vidsonic_url(
    embed_url: str,
    session=None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Tuple[str, str]]:
    """Vidsonic (vidsonic.net). yt-dlp kennt diesen Hoster nicht. Die Stream-URL
    steckt in einer JS-Variable (pipe-getrennte Hex-Chunks): '|' entfernen,
    Hex-Paare -> Zeichen, dann den String UMKEHREN -> HLS master.m3u8. Der
    Variablenname ist obfuskiert, daher wird jeder pipe-getrennte Hex-String
    getestet und der genommen, der eine http-URL ergibt."""
    _log = log_cb or logger.info
    if session is None:
        session = _make_session()
    try:
        html = _fetch_html(session, embed_url, referer="https://filmpalast.to/")
    except Exception as exc:
        _log(f"Vidsonic-Embed nicht ladbar: {exc}")
        return None

    for cand in re.findall(r"'([0-9a-fA-F]+(?:\|[0-9a-fA-F]+)+)'", html):
        clean = cand.replace("|", "")
        if len(clean) < 40 or len(clean) % 2:
            continue
        try:
            chars = "".join(chr(int(clean[i:i + 2], 16)) for i in range(0, len(clean), 2))
        except ValueError:
            continue
        url = chars[::-1]
        if url.startswith("http") and (".m3u8" in url or ".mp4" in url):
            return url, ("hls" if ".m3u8" in url else "mp4")

    _log("Vidsonic: keine dekodierbare Stream-URL gefunden.")
    return None


def extract_firestream_url(
    embed_url: str,
    session=None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Tuple[str, str]]:
    """Loest FireStreams einmaligen Player-Token auf.

    Die Embed-Seite enthaelt einen ``token-blob``. Dieser wird einmalig an
    ``POST /api/videos/<slug>/resolve`` gesendet und liefert eine signierte
    MP4- oder HLS-URL. ``/v/``-Freigabelinks werden auf die technisch
    identische ``/e/``-Playerroute abgebildet.
    """
    _log = log_cb or logger.info
    if session is None:
        session = _make_session()

    parsed = urlparse(embed_url)
    if not parsed.scheme or not parsed.netloc:
        _log("FireStream: ungueltige Player-URL.")
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        _log("FireStream: kein Video-Slug in der Player-URL.")
        return None
    player_url = f"{base}/e/{quote(slug, safe='-_')}"

    try:
        html = _fetch_html(session, player_url, referer="https://megakino.org/")
    except Exception as exc:
        _log(f"FireStream-Embed nicht ladbar: {exc}")
        return None

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    video_data = {}
    data_node = soup.find(id="video-data")
    if data_node:
        try:
            video_data = json.loads(data_node.get_text(strip=True))
        except (TypeError, json.JSONDecodeError):
            video_data = {}
    video = video_data.get("video") if isinstance(video_data, dict) else {}
    video = video if isinstance(video, dict) else {}
    direct = str(video.get("signedVideoUrl") or "").strip()

    if not direct:
        blob_node = soup.find(id="token-blob")
        blob = blob_node.get_text(strip=True) if blob_node else ""
        if not blob:
            _log("FireStream: token-blob fehlt.")
            return None
        try:
            response = session.post(
                f"{base}/api/videos/{quote(slug, safe='-_')}/resolve",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": base,
                    "Referer": player_url,
                },
                data=json.dumps({"blob": blob}),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            direct = str(payload.get("signedVideoUrl") or "").strip()
        except Exception as exc:
            _log(f"FireStream Token-Aufloesung fehlgeschlagen: {exc}")
            return None

    if not direct.startswith("http"):
        _log("FireStream: keine signierte Video-URL in der Antwort.")
        return None
    encoded_path = str(video.get("encodedPath") or "").casefold()
    stream_type = "hls" if ".m3u8" in direct.casefold() or encoded_path.endswith(".m3u8") else "mp4"
    return direct, stream_type


# ---------------------------------------------------------------------------
# Haupt-API (Regex + Browser-Fallback)
# ---------------------------------------------------------------------------
def extract_stream_url(
    url: str,
    session=None,
    log_cb: Optional[Callable[[str], None]] = None,
    pool: Optional[VOEBrowserPool] = None,
    referer: str = "https://filmpalast.to/",
) -> Optional[Tuple[str, str]]:
    """
    Haupt-Einstiegspunkt für eine VOE.SX-URL.

    Args:
        url: VOE-URL
        session: optionale curl_cffi-Session
        log_cb: optionaler Log-Callback
        pool: optionaler VOEBrowserPool (schneller für mehrere Extraktionen).
              Wenn None, wird kein Browser benutzt (nur Regex-Pfad).

    Returns: (stream_url, "hls" | "mp4") oder None.
    """
    _log = log_cb or logger.info

    if session is None:
        session = _make_session()

    try:
        first_html = _fetch_html(session, url, referer=referer)
        alias_url = _find_js_redirect_url(first_html, url)
        if alias_url:
            logger.debug("JS-Redirect → %s", alias_url)
            try:
                html = _fetch_html(session, alias_url, referer=referer)
            except Exception as exc:
                logger.warning("JS-Redirect fehlgeschlagen: %s", exc)
                html = first_html
        else:
            html = first_html
    except Exception as exc:
        logger.error("Fetch fehlgeschlagen: %s", exc)
        return None

    result = _extract_regex(html)
    if result:
        _log(f"Stream-URL (Regex): {result[0][:60]}...")
        return result

    if pool is None:
        _log("Regex erfolglos – kein Browser-Pool übergeben.")
        return None

    _log("Regex erfolglos – starte Browser-Extraktion …")
    target = alias_url or url
    return pool.extract(target, referer=referer)


def _get_alias_url(html: str, original_url: str) -> Optional[str]:
    """Extrahiert die Domain-Alias-URL aus der JS-Redirect-Seite."""
    alias_url = _find_js_redirect_url(html, original_url)
    if alias_url and "filmpalast.to" not in alias_url:
        return alias_url
    return None
