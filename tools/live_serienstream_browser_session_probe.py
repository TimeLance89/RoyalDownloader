from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from session_manager import GATE_BLOCKED, ProviderBlockedError, SessionManager

BASE_URL = "https://serienstream.to/"
CASES = [
    ("Breaking Bad S01E01", "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1"),
    ("Game of Thrones S08E06", "https://serienstream.to/serie/game-of-thrones/staffel-8/episode-6"),
    ("Safe S01E01", "https://serienstream.to/serie/safe/staffel-1/episode-1"),
]


def is_external(value: str | None) -> bool:
    if not value or value == GATE_BLOCKED:
        return False
    host = (urlsplit(value).hostname or "").casefold()
    return host not in {"serienstream.to", "www.serienstream.to", "s.to", "www.s.to"}


def cookie_names(session: SessionManager) -> list[str]:
    names = set()
    for cookie in session._curl.cookies.jar:
        domain = str(getattr(cookie, "domain", "") or "").casefold()
        if "serienstream.to" in domain or not domain:
            names.add(str(cookie.name))
    return sorted(names)


def _new_cdp_target(port: int) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?about:blank",
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


class CdpTab:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.ws = None
        self.counter = 0

    async def __aenter__(self):
        import websockets

        self.ws = await websockets.connect(self.websocket_url, max_size=None)
        await self.command("Runtime.enable")
        await self.command("Page.enable")
        await self.command("Network.enable")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.ws is not None:
            await self.ws.close()

    async def command(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        request_id = self.counter
        await self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(await self.ws.recv())
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                raise RuntimeError(f"CDP {method}: {payload['error']}")
            return payload.get("result") or {}

    async def evaluate(self, expression: str):
        result = await self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        return (result.get("result") or {}).get("value")

    async def navigate(self, url: str) -> None:
        await self.command("Page.navigate", {"url": url})
        await asyncio.sleep(4)

    async def content(self) -> str:
        return str(await self.evaluate("document.documentElement ? document.documentElement.outerHTML : ''") or "")

    async def url(self) -> str:
        return str(await self.evaluate("window.location.href") or "")

    async def click_first_hoster(self) -> str:
        value = await self.evaluate(
            """
            (() => {
              const button = document.querySelector('[data-play-url]');
              if (!button) return 'missing';
              button.scrollIntoView({block: 'center', inline: 'center'});
              button.click();
              return 'clicked';
            })()
            """
        )
        return str(value or "unknown")

    async def set_http_cookies(self, session: SessionManager) -> int:
        cookies = []
        for cookie in session._curl.cookies.jar:
            domain = str(getattr(cookie, "domain", "") or "").strip()
            if domain and "serienstream.to" not in domain.casefold():
                continue
            cookies.append(
                {
                    "name": str(cookie.name),
                    "value": str(cookie.value),
                    "domain": domain or "serienstream.to",
                    "path": str(getattr(cookie, "path", "/") or "/"),
                    "secure": bool(getattr(cookie, "secure", True)),
                }
            )
        if cookies:
            await self.command("Network.setCookies", {"cookies": cookies})
        return len(cookies)

    async def pull_cookies_to_http(self, session: SessionManager) -> list[str]:
        result = await self.command("Network.getAllCookies")
        copied = {}
        for cookie in result.get("cookies") or []:
            domain = str(cookie.get("domain") or "")
            if "serienstream.to" not in domain.casefold():
                continue
            name = str(cookie.get("name") or "")
            if not name:
                continue
            value = str(cookie.get("value") or "")
            session._curl.cookies.set(
                name,
                value,
                domain=domain,
                path=str(cookie.get("path") or "/"),
                secure=bool(cookie.get("secure", True)),
            )
            copied[name] = value
        if copied:
            session._cookies.update(copied)
            session._save_cookies()
        return sorted(copied)


def page_state(html: str) -> dict[str, bool]:
    low = (html or "").casefold()
    return {
        "gate_root": "episode-redirect-gate-root" in low,
        "prepare_modal": "playerpreparemodal" in low,
        "turnstile": "turnstile" in low,
        "challenge": "challenges.cloudflare.com" in low,
    }


def write_github_outputs(summary: dict) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    results = summary.get("results") or []
    metrics = {
        "cases": len(results),
        "external_total": int(summary.get("external_total") or 0),
        "external_after_browser": int(summary.get("external_after_browser") or 0),
        "gated_after_browser": sum(r.get("after_browser") == "gate_blocked" for r in results),
        "turnstile_cases": sum(bool((r.get("page_state_after_click") or {}).get("turnstile")) for r in results),
        "gate_root_cases": sum(bool((r.get("page_state_after_click") or {}).get("gate_root")) for r in results),
        "prepare_modal_cases": sum(bool((r.get("page_state_after_click") or {}).get("prepare_modal")) for r in results),
        "challenge_cases": sum(bool((r.get("page_state_after_click") or {}).get("challenge")) for r in results),
        "click_cases": sum(r.get("hoster_click") == "clicked" for r in results),
        "clearance_cases": sum("cf_clearance" in (r.get("browser_cookie_names") or []) for r in results),
    }
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in metrics.items():
            handle.write(f"{key}={value}\n")


async def run() -> int:
    port = int(os.getenv("ROYAL_PROBE_CDP_PORT", "0") or 0)
    if not port:
        raise RuntimeError("ROYAL_PROBE_CDP_PORT is required for this diagnostic")

    session = SessionManager(
        target_domain="serienstream.to",
        log_cb=lambda message: print(f"[royal] {message}", flush=True),
    )
    session.clear_cookies()

    results = []
    for index, (name, episode_url) in enumerate(CASES, 1):
        started = time.monotonic()
        item = {
            "index": index,
            "name": name,
            "hoster": "",
            "initial": "unknown",
            "after_browser": "unknown",
            "final_host": "",
            "http_cookie_names_before": [],
            "browser_cookie_names": [],
            "page_state_before_click": {},
            "page_state_after_click": {},
            "hoster_click": "not_attempted",
            "browser_url_after_click": "",
        }
        try:
            html = session.get(episode_url)
            soup = BeautifulSoup(html, "lxml")
            buttons = soup.select("[data-play-url]")
            if not buttons:
                item["initial"] = "no_hoster_buttons"
                results.append(item)
                print("BROWSER_PROBE " + json.dumps(item, ensure_ascii=False), flush=True)
                continue

            button = buttons[0]
            item["hoster"] = str(button.get("data-provider-name") or "Hoster").strip()
            redirect_url = urljoin(BASE_URL, str(button.get("data-play-url") or "").strip())

            initial_target = session.get_redirect_location(redirect_url, referer=episode_url)
            item["initial"] = (
                "external_embed" if is_external(initial_target)
                else "gate_blocked" if initial_target == GATE_BLOCKED
                else "unresolved"
            )
            if is_external(initial_target):
                item["after_browser"] = "not_needed"
                item["final_host"] = str(urlsplit(initial_target).hostname or "")
                results.append(item)
                print("BROWSER_PROBE " + json.dumps(item, ensure_ascii=False), flush=True)
                continue

            item["http_cookie_names_before"] = cookie_names(session)
            target = await asyncio.to_thread(_new_cdp_target, port)
            async with CdpTab(str(target["webSocketDebuggerUrl"])) as tab:
                item["http_cookies_pushed"] = await tab.set_http_cookies(session)
                await tab.navigate(episode_url)
                item["page_state_before_click"] = page_state(await tab.content())

                # Normal site interaction only. We do not inspect, click or synthesize
                # any CAPTCHA/Turnstile widget or verification response.
                item["hoster_click"] = await tab.click_first_hoster()
                await asyncio.sleep(3)
                item["browser_url_after_click"] = await tab.url()
                item["page_state_after_click"] = page_state(await tab.content())

                for delay_seconds in (5, 10, 15):
                    await asyncio.sleep(delay_seconds)
                    item["browser_cookie_names"] = await tab.pull_cookies_to_http(session)
                    resolved = session.get_redirect_location(redirect_url, referer=episode_url)
                    if is_external(resolved):
                        item["after_browser"] = "external_embed"
                        item["final_host"] = str(urlsplit(resolved).hostname or "")
                        break
                    if resolved == GATE_BLOCKED:
                        item["after_browser"] = "gate_blocked"
                    elif resolved:
                        item["after_browser"] = "still_on_serienstream"
                    else:
                        item["after_browser"] = "unresolved"
        except ProviderBlockedError as exc:
            item["after_browser"] = f"provider_blocked:{exc.reason}:{exc.status}"
        except Exception as exc:
            item["after_browser"] = f"error:{type(exc).__name__}"
            item["error"] = str(exc)[:300]

        item["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(item)
        print("BROWSER_PROBE " + json.dumps(item, ensure_ascii=False), flush=True)

    summary = {
        "cases": len(results),
        "external_after_browser": sum(r.get("after_browser") == "external_embed" for r in results),
        "external_total": sum(
            r.get("initial") == "external_embed" or r.get("after_browser") == "external_embed"
            for r in results
        ),
        "results": results,
    }
    write_github_outputs(summary)
    print("BROWSER_PROBE_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
