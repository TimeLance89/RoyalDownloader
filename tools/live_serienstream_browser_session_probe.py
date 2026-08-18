from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from network_guard import safe_proxy_url
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
    for cookie in session._curl.cookies.jar:  # diagnostic only: preserve path/domain data
        domain = str(getattr(cookie, "domain", "") or "").casefold()
        if "serienstream.to" in domain or not domain:
            names.add(str(cookie.name))
    return sorted(names)


async def push_http_cookies_to_browser(session: SessionManager, browser) -> int:
    import nodriver.cdp.network as cdp_network

    params = []
    for cookie in session._curl.cookies.jar:
        domain = str(getattr(cookie, "domain", "") or "").strip()
        if domain and "serienstream.to" not in domain.casefold():
            continue
        params.append(
            cdp_network.CookieParam(
                name=str(cookie.name),
                value=str(cookie.value),
                domain=domain or "serienstream.to",
                path=str(getattr(cookie, "path", "/") or "/"),
                secure=bool(getattr(cookie, "secure", True)),
            )
        )
    if params:
        await browser.cookies.set_all(params)
    return len(params)


async def pull_browser_cookies_to_http(session: SessionManager, browser) -> list[str]:
    raw = await browser.cookies.get_all()
    copied = {}
    for cookie in raw:
        domain = str(getattr(cookie, "domain", "") or "")
        if "serienstream.to" not in domain.casefold():
            continue
        session._curl.cookies.set(
            str(cookie.name),
            str(cookie.value),
            domain=domain,
            path=str(getattr(cookie, "path", "/") or "/"),
            secure=bool(getattr(cookie, "secure", True)),
        )
        copied[str(cookie.name)] = str(cookie.value)
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


async def run() -> int:
    import nodriver as uc
    import nodriver_patch

    nodriver_patch.apply()
    session = SessionManager(
        target_domain="serienstream.to",
        log_cb=lambda message: print(f"[royal] {message}", flush=True),
    )
    session.clear_cookies()

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
    results = []
    try:
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
                "page_state": {},
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
                pushed = await push_http_cookies_to_browser(session, browser)
                item["http_cookies_pushed"] = pushed

                tab = await browser.get(episode_url)
                await asyncio.sleep(4)
                browser_html = await tab.get_content()
                item["page_state"] = page_state(browser_html)

                # Use the site's normal browser verification flow. We never synthesize
                # or inject a challenge response; we only preserve the same session.
                for delay_seconds in (8, 12, 20):
                    await asyncio.sleep(delay_seconds)
                    pulled = await pull_browser_cookies_to_http(session, browser)
                    item["browser_cookie_names"] = pulled
                    target = session.get_redirect_location(redirect_url, referer=episode_url)
                    if is_external(target):
                        item["after_browser"] = "external_embed"
                        item["final_host"] = str(urlsplit(target).hostname or "")
                        break
                    if target == GATE_BLOCKED:
                        item["after_browser"] = "gate_blocked"
                    elif target:
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
    finally:
        browser.stop()

    summary = {
        "cases": len(results),
        "external_after_browser": sum(r.get("after_browser") == "external_embed" for r in results),
        "external_total": sum(
            r.get("initial") == "external_embed" or r.get("after_browser") == "external_embed"
            for r in results
        ),
        "results": results,
    }
    print("BROWSER_PROBE_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
