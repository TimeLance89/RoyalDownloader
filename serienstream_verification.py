"""User-driven SerienStream browser verification.

The runtime deliberately does not solve or synthesize CAPTCHA/Turnstile input.
It exposes a short-lived Chromium viewport to the authenticated Royal user,
forwards only that user's click/scroll gestures, and imports the resulting
SerienStream cookies only after the site has accepted the normal interaction.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from websockets.sync.client import connect

from network_guard import safe_proxy_url
from runtime_paths import data_dir
from session_manager import GATE_BLOCKED, SessionManager

SERIESSTREAM_HOSTS = {"serienstream.to", "www.serienstream.to"}
DEFAULT_EPISODE_URL = "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1"
EPISODE_PATH_RE = re.compile(r"^/serie/[^/?#]+/staffel-\d+/episode-\d+/?$")
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
SESSION_TTL_SECONDS = 10 * 60


def valid_episode_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").casefold() in SERIESSTREAM_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and bool(EPISODE_PATH_RE.fullmatch(parsed.path or ""))
        and not parsed.query
        and not parsed.fragment
    )


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_endpoint(port: int, path: str, *, method: str = "GET") -> Any:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


class _Cdp:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self._counter = 0

    def _command(self, method: str, params: dict | None = None) -> dict:
        self._counter += 1
        request_id = self._counter
        with connect(self.websocket_url, max_size=None, open_timeout=5) as websocket:
            websocket.send(json.dumps({
                "id": request_id,
                "method": method,
                "params": params or {},
            }))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                payload = json.loads(websocket.recv(timeout=10))
                if payload.get("id") != request_id:
                    continue
                if payload.get("error"):
                    raise RuntimeError(f"CDP {method}: {payload['error']}")
                return payload.get("result") or {}
        raise TimeoutError(f"CDP timeout: {method}")

    def evaluate(self, expression: str) -> Any:
        result = self._command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        })
        return (result.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self._command("Page.navigate", {"url": url})

    def screenshot(self) -> bytes:
        result = self._command("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": False,
        })
        return base64.b64decode(str(result.get("data") or ""))

    def click(self, x: float, y: float) -> None:
        common = {
            "x": float(x),
            "y": float(y),
            "button": "left",
            "clickCount": 1,
        }
        self._command("Input.dispatchMouseEvent", {
            **common,
            "type": "mousePressed",
        })
        self._command("Input.dispatchMouseEvent", {
            **common,
            "type": "mouseReleased",
        })

    def scroll(self, delta_y: float) -> None:
        self._command("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": VIEWPORT_WIDTH / 2,
            "y": VIEWPORT_HEIGHT / 2,
            "deltaX": 0,
            "deltaY": float(delta_y),
        })

    def cookies(self) -> list[dict]:
        return list(self._command("Network.getAllCookies").get("cookies") or [])

    def set_cookies(self, cookies: list[dict]) -> None:
        if cookies:
            self._command("Network.setCookies", {"cookies": cookies})

    def current_url(self) -> str:
        return str(self.evaluate("window.location.href") or "")

    def page_markers(self) -> dict[str, bool]:
        html = str(self.evaluate(
            "document.documentElement ? document.documentElement.outerHTML : ''"
        ) or "")
        low = html.casefold()
        return {
            "turnstile": "turnstile" in low,
            "gate_root": "episode-redirect-gate-root" in low,
            "prepare_modal": "playerpreparemodal" in low,
            "challenge": "challenges.cloudflare.com" in low,
        }

    def click_first_hoster(self) -> bool:
        return bool(self.evaluate("""
            (() => {
              const button = document.querySelector('[data-play-url]');
              if (!button) return false;
              button.scrollIntoView({block: 'center', inline: 'center'});
              button.click();
              return true;
            })()
        """))


@dataclass
class VerificationState:
    phase: str = "idle"
    episode_url: str = ""
    redirect_url: str = ""
    started_at: float = 0.0
    error: str = ""
    final_host: str = ""


class SerienStreamVerificationManager:
    """Own one short-lived visible Chromium verification session."""

    def __init__(self, *, clock=time.time):
        self.clock = clock
        self._lock = threading.RLock()
        self._state = VerificationState()
        self._xvfb: subprocess.Popen | None = None
        self._chrome: subprocess.Popen | None = None
        self._cdp: _Cdp | None = None
        self._port = 0
        self._display = ""

    @property
    def profile_dir(self) -> Path:
        return data_dir() / "serienstream-browser-profile"

    def _expired_locked(self) -> bool:
        return bool(
            self._state.started_at
            and self.clock() - self._state.started_at > SESSION_TTL_SECONDS
        )

    def _cleanup_locked(self, *, reset_state: bool = True) -> None:
        for process in (self._chrome, self._xvfb):
            if process is None or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self._chrome = None
        self._xvfb = None
        self._cdp = None
        self._port = 0
        self._display = ""
        if reset_state:
            self._state = VerificationState()

    def close(self) -> None:
        with self._lock:
            self._cleanup_locked()

    def _require_active_locked(self) -> _Cdp:
        if self._expired_locked():
            self._cleanup_locked()
            raise RuntimeError("Die SerienStream-Freischaltung ist abgelaufen.")
        if self._cdp is None or self._chrome is None or self._chrome.poll() is not None:
            raise RuntimeError("Keine SerienStream-Freischaltung aktiv.")
        return self._cdp

    @staticmethod
    def _session_cookies(session: SessionManager) -> list[dict]:
        result = []
        for cookie in session._curl.cookies.jar:
            domain = str(getattr(cookie, "domain", "") or "").strip()
            if domain and "serienstream.to" not in domain.casefold():
                continue
            result.append({
                "name": str(cookie.name),
                "value": str(cookie.value),
                "domain": domain or "serienstream.to",
                "path": str(getattr(cookie, "path", "/") or "/"),
                "secure": bool(getattr(cookie, "secure", True)),
            })
        return result

    @staticmethod
    def _extract_redirect_url(html: str, episode_url: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        button = soup.select_one("[data-play-url]")
        href = str(button.get("data-play-url") or "").strip() if button else ""
        if not href.startswith("/r?t="):
            raise RuntimeError("Auf der Testepisode wurde kein SerienStream-Hoster gefunden.")
        return "https://serienstream.to" + href

    def _start_processes_locked(self) -> _Cdp:
        chrome = os.environ.get("CHROME_PATH", "").strip() or shutil.which("chromium") or shutil.which("google-chrome")
        xvfb = shutil.which("Xvfb")
        if not chrome:
            raise RuntimeError("Chromium ist auf dieser Royal-Instanz nicht verfügbar.")
        if not xvfb:
            raise RuntimeError("Xvfb ist auf dieser Royal-Instanz nicht verfügbar.")

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        display_number = 80 + (_free_local_port() % 100)
        self._display = f":{display_number}"
        self._xvfb = subprocess.Popen(
            [xvfb, self._display, "-screen", "0", f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._port = _free_local_port()
        args = [
            chrome,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self.profile_dir}",
            f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
            f"--user-agent={CHROME_USER_AGENT}",
        ]
        proxy = safe_proxy_url()
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.append("about:blank")
        env = {**os.environ, "DISPLAY": self._display}
        self._chrome = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 15
        page = None
        while time.monotonic() < deadline:
            if self._chrome.poll() is not None:
                raise RuntimeError("Chromium wurde während der Freischaltung beendet.")
            try:
                targets = _json_endpoint(self._port, "/json/list")
                page = next((target for target in targets if target.get("type") == "page"), None)
                if page and page.get("webSocketDebuggerUrl"):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not page or not page.get("webSocketDebuggerUrl"):
            raise RuntimeError("Chromium DevTools konnte nicht gestartet werden.")
        cdp = _Cdp(str(page["webSocketDebuggerUrl"]))
        cdp._command("Network.enable")
        cdp._command("Page.enable")
        cdp._command("Runtime.enable")
        cdp._command("Emulation.setDeviceMetricsOverride", {
            "width": VIEWPORT_WIDTH,
            "height": VIEWPORT_HEIGHT,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        cdp._command("Network.setUserAgentOverride", {
            "userAgent": CHROME_USER_AGENT,
            "acceptLanguage": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "platform": "Win32",
        })
        return cdp

    def start(self, episode_url: str = DEFAULT_EPISODE_URL) -> dict:
        episode_url = str(episode_url or DEFAULT_EPISODE_URL).strip()
        if not valid_episode_url(episode_url):
            raise ValueError("Es ist nur eine direkte serienstream.to-Episoden-URL erlaubt.")
        with self._lock:
            self._cleanup_locked()
            session = SessionManager(target_domain="serienstream.to")
            try:
                html = session.get(episode_url, fast=True)
                redirect_url = self._extract_redirect_url(html, episode_url)
                self._state = VerificationState(
                    phase="starting",
                    episode_url=episode_url,
                    redirect_url=redirect_url,
                    started_at=self.clock(),
                )
                cdp = self._start_processes_locked()
                self._cdp = cdp
                cdp.set_cookies(self._session_cookies(session))
                cdp.navigate(episode_url)
                time.sleep(3)
                cdp.click_first_hoster()
                time.sleep(1)
                self._state.phase = "waiting_for_user"
                return self.status()
            except Exception:
                self._cleanup_locked()
                raise

    def status(self) -> dict:
        with self._lock:
            if self._expired_locked():
                self._cleanup_locked()
            cdp = self._cdp
            cookies = []
            current_url = ""
            markers: dict[str, bool] = {}
            if cdp is not None:
                try:
                    cookies = cdp.cookies()
                    current_url = cdp.current_url()
                    markers = cdp.page_markers()
                except Exception as exc:
                    self._state.error = str(exc)[:300]
            names = sorted({
                str(cookie.get("name") or "")
                for cookie in cookies
                if "serienstream.to" in str(cookie.get("domain") or "").casefold()
            } - {""})
            return {
                "active": cdp is not None,
                "phase": self._state.phase,
                "episode_url": self._state.episode_url,
                "started_at": self._state.started_at,
                "expires_at": self._state.started_at + SESSION_TTL_SECONDS if self._state.started_at else 0,
                "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                "browser_url": current_url,
                "cookie_names": names,
                "has_clearance": "cf_clearance" in names,
                "page": markers,
                "error": self._state.error,
                "final_host": self._state.final_host,
            }

    def screenshot(self) -> bytes:
        with self._lock:
            return self._require_active_locked().screenshot()

    def click(self, x_ratio: float, y_ratio: float) -> dict:
        x_ratio = float(x_ratio)
        y_ratio = float(y_ratio)
        if not (0 <= x_ratio <= 1 and 0 <= y_ratio <= 1):
            raise ValueError("Klickkoordinaten müssen zwischen 0 und 1 liegen.")
        with self._lock:
            cdp = self._require_active_locked()
            cdp.click(x_ratio * VIEWPORT_WIDTH, y_ratio * VIEWPORT_HEIGHT)
            time.sleep(0.25)
            return self.status()

    def scroll(self, delta_y: float) -> dict:
        delta_y = max(-1600.0, min(1600.0, float(delta_y)))
        with self._lock:
            cdp = self._require_active_locked()
            cdp.scroll(delta_y)
            time.sleep(0.15)
            return self.status()

    @staticmethod
    def _serienstream_cookies(cdp: _Cdp) -> list[dict]:
        return [
            cookie for cookie in cdp.cookies()
            if "serienstream.to" in str(cookie.get("domain") or "").casefold()
            and cookie.get("name")
        ]

    @staticmethod
    def _install_into_session(session: SessionManager, cookies: list[dict]) -> list[str]:
        installed = {}
        for cookie in cookies:
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            domain = str(cookie.get("domain") or "serienstream.to")
            path = str(cookie.get("path") or "/")
            if not name:
                continue
            session._curl.cookies.set(
                name,
                value,
                domain=domain,
                path=path,
                secure=bool(cookie.get("secure", True)),
            )
            installed[name] = value
        if installed:
            session._cookies.update(installed)
            session._save_cookies()
        return sorted(installed)

    def finish(self) -> dict:
        with self._lock:
            cdp = self._require_active_locked()
            cookies = self._serienstream_cookies(cdp)
            if not cookies:
                raise RuntimeError("Der Browser hat noch keine SerienStream-Sitzung erzeugt.")

            # Synchronize both a fresh session and the already-live scraper so
            # queued work can resume without restarting Royal.
            session = SessionManager(target_domain="serienstream.to")
            installed = self._install_into_session(session, cookies)
            try:
                from application_services.runtime import backend_value

                scraper = backend_value("get_sto_scraper")()
                self._install_into_session(scraper.session, cookies)
            except (AttributeError, RuntimeError):
                scraper = None

            target = session.get_redirect_location(
                self._state.redirect_url,
                referer=self._state.episode_url,
            )
            parsed = urlparse(str(target or ""))
            external = bool(
                target
                and target != GATE_BLOCKED
                and parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.hostname.casefold() not in SERIESSTREAM_HOSTS
            )
            if not external:
                self._state.phase = "waiting_for_user"
                self._state.error = "Die SerienStream-Verifikation ist noch nicht abgeschlossen."
                return {**self.status(), "verified": False, "installed_cookie_names": installed}

            self._state.phase = "verified"
            self._state.final_host = str(parsed.hostname or "")
            self._state.error = ""
            if scraper is not None:
                scraper.gated = False
                scraper.last_block_reason = ""
            try:
                from application_services.runtime import backend_value

                state = backend_value("state")
                state.provider_health.mark_success("serienstream")
                state.provider_retry_wake_event.set()
            except (AttributeError, RuntimeError):
                pass
            payload = {
                **self.status(),
                "verified": True,
                "installed_cookie_names": installed,
            }
            self._cleanup_locked(reset_state=False)
            return payload


SERIESSTREAM_VERIFICATION = SerienStreamVerificationManager()
