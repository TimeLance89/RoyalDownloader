from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
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
    for cookie in session._curl.cookies.jar:  # diagnostic only
        domain = str(getattr(cookie, "domain", "") or "").casefold()
        if "serienstream.to" in domain or not domain:
            names.add(str(cookie.name))
    return sorted(names)


async def push_http_cookies_to_browser(session: SessionManager, browser) -> int:
    import nodriver.cdp.network as cdp_network
    import nodriver.cdp.storage as cdp_storage

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
        # CookieJar.set_all() iterates Browser.main_tab internally. An attached
        # CDP browser can have no nodriver-registered page target yet, so set
        # cookies directly through the browser-level Storage domain.
        await browser.send(cdp_storage.set_cookies(params))
    return len(params)


async def pull_browser_cookies_to_http(session: SessionManager, browser) -> list[str]:
    import nodriver.cdp.storage as cdp_storage

    raw = await browser.send(cdp_storage.get_cookies())
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


async def click_normal_hoster(tab) -> str:
    """Click only the site's own first hoster button; never touch challenge UI."""
    result = await tab.evaluate(
        """
        (() => {
          const button = document.querySelector('[data-play-url]');
          if (!button) return 'missing';
          button.scrollIntoView({block: 'center', inline: 'center'});
          button.click();
          return 'clicked';
        })()
        """,
        return_by_value=True,
    )
    return str(result or "unknown")


async def current_browser_url(tab) -> str:
    result = await tab.evaluate("window.location.href", return_by_value=True)
    return str(result or "")


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
        "error_cases": sum(str(r.get("after_browser") or "").startswith("error:") for r in results),
    }
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in metrics.items():
            handle.write(f"{key}={value}\n")


async def run() -> int:
    import nodriver as uc
    import nodriver_patch

    nodriver_patch.apply()
    session = SessionManager(
        target_domain="serienstream.to",
        log_cb=lambda message: print(f"[royal] {message}", flush=True),
    )
    session.clear_cookies()

    cdp_port = int(os.getenv("ROYAL_PROBE_CDP_PORT", "0") or 0)
    if cdp_port:
        browser = await uc.start(host="127.0.0.1", port=cdp_port)
    else:
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
            sandbox=False,
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
                item["http_cookies_pushed"] = await push_http_cookies_to_browser(session, browser)

                # Creating a fresh target avoids Browser.get() depending on an
                # initial page target that may not exist on an attached Chrome.
                tab = await browser.get(episode_url, new_tab=True)
                await asyncio.sleep(4)
                item["page_state_before_click"] = page_state(await tab.get_content())

                # Reproduce the normal site action only. Any challenge widget is
                # deliberately left untouched.
                item["hoster_click"] = await click_normal_hoster(tab)
                await asyncio.sleep(3)
                item["browser_url_after_click"] = await current_browser_url(tab)
                item["page_state_after_click"] = page_state(await tab.get_content())

                for delay_seconds in (5, 10, 15):
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
                item["traceback"] = traceback.format_exc()[-1600:]

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
    write_github_outputs(summary)
    print("BROWSER_PROBE_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
