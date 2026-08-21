"""Shared SerienStream browser session used by HTTP and Chromium.

This module mirrors the useful StreamFlix design principle: browser state and
normal HTTP requests are one provider session. Chromium uses a persistent
profile, receives the current HTTP cookies, performs only normal page
navigation/user-equivalent hoster clicks, and returns the resulting cookies to
curl_cffi. It deliberately does not solve or synthesize Turnstile/CAPTCHA.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from websockets.sync.client import connect

from network_guard import safe_proxy_url
from runtime_paths import data_dir
from serienstream_session_identity import (
    SERIESSTREAM_ACCEPT_LANGUAGE,
    SERIESSTREAM_HOSTS,
    SERIESSTREAM_USER_AGENT,
)

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
_BROWSER_LOCK = threading.Lock()
_EPISODE_PATH_RE = re.compile(r"^/serie/[^/?#]+/staffel-\d+/episode-\d+/?$")
_SAFE_PAGE_PATH_RE = re.compile(
    r"^(?:/|/serie(?:/[^/?#]+(?:/staffel-\d+(?:/episode-\d+)?)?)?|/suche|/serien|/beliebte-serien|/genre/[^/?#]+)$"
)


@dataclass
class SharedBrowserResult:
    html: str = ""
    target: str = ""
    cookies: list[dict] = field(default_factory=list)
    gated: bool = False
    markers: dict[str, bool] = field(default_factory=dict)
    error: str = ""


def _provider_url(value: str) -> bool:
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
    )


def valid_episode_url(value: str) -> bool:
    if not _provider_url(value):
        return False
    parsed = urlparse(value)
    return bool(_EPISODE_PATH_RE.fullmatch(parsed.path or "")) and not parsed.query and not parsed.fragment


def valid_provider_page_url(value: str) -> bool:
    if not _provider_url(value):
        return False
    parsed = urlparse(value)
    if parsed.fragment:
        return False
    return bool(_SAFE_PAGE_PATH_RE.fullmatch(parsed.path or ""))


def valid_redirect_url(value: str) -> bool:
    if not _provider_url(value):
        return False
    parsed = urlparse(value)
    if parsed.path != "/r" or parsed.fragment:
        return False
    query = parse_qs(parsed.query, keep_blank_values=False)
    return set(query) == {"t"} and len(query.get("t") or []) == 1 and bool(query["t"][0])


def _external_http_url(value: str) -> str:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold().rstrip(".")
    if host in SERIESSTREAM_HOSTS or host == "challenges.cloudflare.com":
        return ""
    return str(value)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_endpoint(port: int, path: str) -> Any:
    if not str(path).startswith("/json/"):
        raise ValueError("Only Chromium DevTools JSON endpoints are allowed.")
    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Chromium DevTools returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


class _Cdp:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self._counter = 0

    def command(self, method: str, params: dict | None = None) -> dict:
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
        result = self.command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        })
        return (result.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self.command("Page.navigate", {"url": url})

    def cookies(self) -> list[dict]:
        return list(self.command("Network.getAllCookies").get("cookies") or [])

    def set_cookies(self, cookies: list[dict]) -> None:
        if cookies:
            self.command("Network.setCookies", {"cookies": cookies})

    def current_url(self) -> str:
        return str(self.evaluate("window.location.href") or "")

    def html(self) -> str:
        return str(self.evaluate(
            "document.documentElement ? document.documentElement.outerHTML : ''"
        ) or "")

    def markers(self) -> dict[str, bool]:
        low = self.html().casefold()
        return {
            "turnstile": "turnstile" in low,
            "gate_root": "episode-redirect-gate-root" in low,
            "prepare_modal": "playerpreparemodal" in low,
            "challenge": "challenges.cloudflare.com" in low or "cf-chl" in low,
        }

    def click_hoster(self, redirect_url: str) -> bool:
        parsed = urlparse(redirect_url)
        wanted = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        expression = f"""
            (() => {{
              const wanted = {json.dumps(wanted)};
              const buttons = Array.from(document.querySelectorAll('[data-play-url]'));
              const button = buttons.find((candidate) => {{
                const raw = candidate.getAttribute('data-play-url') || '';
                try {{
                  const resolved = new URL(raw, window.location.origin);
                  return resolved.pathname + resolved.search === wanted;
                }} catch (_error) {{
                  return raw === wanted;
                }}
              }});
              if (!button) return false;
              button.scrollIntoView({{block: 'center', inline: 'center'}});
              button.click();
              return true;
            }})()
        """
        return bool(self.evaluate(expression))


def _profile_dir() -> Path:
    return data_dir() / "serienstream-browser-profile"


def _filtered_cookies(cookies: list[dict]) -> list[dict]:
    return [
        cookie for cookie in cookies
        if cookie.get("name")
        and "serienstream.to" in str(cookie.get("domain") or "").casefold()
    ]


def _page_target(port: int) -> dict | None:
    targets = _json_endpoint(port, "/json/list")
    return next(
        (
            target for target in targets
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl")
        ),
        None,
    )


def _external_target(port: int) -> str:
    try:
        for target in _json_endpoint(port, "/json/list"):
            if target.get("type") != "page":
                continue
            external = _external_http_url(str(target.get("url") or ""))
            if external:
                return external
    except Exception:
        return ""
    return ""


class _BrowserRuntime:
    def __init__(self):
        self.xvfb: subprocess.Popen | None = None
        self.chrome: subprocess.Popen | None = None
        self.port = 0
        self.display = ""
        self.cdp: _Cdp | None = None

    def start(self) -> _Cdp:
        chrome = (
            os.environ.get("CHROME_PATH", "").strip()
            or shutil.which("chromium")
            or shutil.which("google-chrome")
        )
        xvfb = shutil.which("Xvfb")
        if not chrome:
            raise RuntimeError("Chromium ist auf dieser Royal-Instanz nicht verfügbar.")
        if not xvfb:
            raise RuntimeError("Xvfb ist auf dieser Royal-Instanz nicht verfügbar.")

        profile = _profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        display_number = 80 + (_free_local_port() % 100)
        self.display = f":{display_number}"
        self.xvfb = subprocess.Popen(
            [xvfb, self.display, "-screen", "0", f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.port = _free_local_port()
        args = [
            chrome,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile}",
            f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
            f"--user-agent={SERIESSTREAM_USER_AGENT}",
        ]
        proxy = safe_proxy_url()
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.append("about:blank")
        self.chrome = subprocess.Popen(
            args,
            env={**os.environ, "DISPLAY": self.display},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 15
        page = None
        while time.monotonic() < deadline:
            if self.chrome.poll() is not None:
                raise RuntimeError("Chromium wurde beim Aufbau der SerienStream-Sitzung beendet.")
            try:
                page = _page_target(self.port)
                if page:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not page:
            raise RuntimeError("Chromium DevTools konnte nicht gestartet werden.")

        self.cdp = _Cdp(str(page["webSocketDebuggerUrl"]))
        self.cdp.command("Network.enable")
        self.cdp.command("Page.enable")
        self.cdp.command("Runtime.enable")
        self.cdp.command("Emulation.setDeviceMetricsOverride", {
            "width": VIEWPORT_WIDTH,
            "height": VIEWPORT_HEIGHT,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        self.cdp.command("Network.setUserAgentOverride", {
            "userAgent": SERIESSTREAM_USER_AGENT,
            "acceptLanguage": SERIESSTREAM_ACCEPT_LANGUAGE,
            "platform": "Win32",
        })
        return self.cdp

    def close(self) -> None:
        for process in (self.chrome, self.xvfb):
            if process is None or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self.chrome = None
        self.xvfb = None
        self.cdp = None


def _wait_for_page(cdp: _Cdp, timeout: float = 8.0) -> tuple[str, dict[str, bool]]:
    deadline = time.monotonic() + timeout
    last_html = ""
    last_markers: dict[str, bool] = {}
    while time.monotonic() < deadline:
        try:
            last_html = cdp.html()
            last_markers = cdp.markers()
            if last_html and not any(last_markers.values()):
                return last_html, last_markers
        except Exception:
            pass
        time.sleep(0.35)
    return last_html, last_markers


def fetch_provider_html(url: str, seed_cookies: list[dict]) -> SharedBrowserResult:
    """Load a SerienStream page through the persistent real-browser profile."""
    if not valid_provider_page_url(url):
        return SharedBrowserResult(error="unsafe_provider_url")
    with _BROWSER_LOCK:
        runtime = _BrowserRuntime()
        try:
            cdp = runtime.start()
            cdp.set_cookies(seed_cookies)
            cdp.navigate(url)
            html, markers = _wait_for_page(cdp)
            cookies = _filtered_cookies(cdp.cookies())
            gated = bool(markers.get("turnstile") or markers.get("gate_root") or markers.get("challenge"))
            return SharedBrowserResult(
                html="" if gated else html,
                cookies=cookies,
                gated=gated,
                markers=markers,
            )
        except Exception as exc:
            return SharedBrowserResult(error=str(exc)[:300])
        finally:
            runtime.close()


def resolve_provider_redirect(
    redirect_url: str,
    referer: str,
    seed_cookies: list[dict],
) -> SharedBrowserResult:
    """Resolve one /r token from the same persistent browser session.

    The episode page is loaded first and the exact existing hoster button is
    clicked. No challenge element is clicked or completed by this code.
    """
    if not valid_redirect_url(redirect_url) or not valid_episode_url(referer):
        return SharedBrowserResult(error="unsafe_redirect_context")

    with _BROWSER_LOCK:
        runtime = _BrowserRuntime()
        try:
            cdp = runtime.start()
            cdp.set_cookies(seed_cookies)
            cdp.navigate(referer)
            _html, initial_markers = _wait_for_page(cdp, timeout=5.0)
            if initial_markers.get("turnstile") or initial_markers.get("challenge"):
                return SharedBrowserResult(
                    cookies=_filtered_cookies(cdp.cookies()),
                    gated=True,
                    markers=initial_markers,
                )

            clicked = cdp.click_hoster(redirect_url)
            if not clicked:
                # Safe fallback: navigate the already validated provider /r URL
                # in the same browser profile instead of dropping back to curl.
                cdp.navigate(redirect_url)

            deadline = time.monotonic() + 10.0
            last_markers: dict[str, bool] = {}
            while time.monotonic() < deadline:
                external = _external_target(runtime.port)
                if not external:
                    external = _external_http_url(cdp.current_url())
                if external:
                    return SharedBrowserResult(
                        target=external,
                        cookies=_filtered_cookies(cdp.cookies()),
                        markers=last_markers,
                    )
                try:
                    last_markers = cdp.markers()
                except Exception:
                    last_markers = {}
                time.sleep(0.35)

            gated = bool(
                last_markers.get("turnstile")
                or last_markers.get("gate_root")
                or last_markers.get("challenge")
                or last_markers.get("prepare_modal")
            )
            return SharedBrowserResult(
                cookies=_filtered_cookies(cdp.cookies()),
                gated=gated,
                markers=last_markers,
                error="browser_redirect_not_resolved" if not gated else "",
            )
        except Exception as exc:
            return SharedBrowserResult(error=str(exc)[:300])
        finally:
            runtime.close()
