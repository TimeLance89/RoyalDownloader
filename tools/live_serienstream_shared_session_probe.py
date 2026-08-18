"""Diagnostic-only live SerienStream shared-session probe.

Exercises the production SessionManager path against a handful of real episode
pages. It does not extract or download video; it only follows the catalog
hoster redirect until an external embed host is reached or the provider reports
an interactive gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

# Executing this diagnostic file directly sets sys.path[0] to ``tools/`` inside
# the container. Add the repository root explicitly so the production modules
# are imported exactly as they are by Royal itself.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup

from session_manager import GATE_BLOCKED, ProviderBlockedError, SessionManager


CASES = [
    (
        "Breaking Bad S01E01",
        "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1",
    ),
    (
        "Game of Thrones S08E06",
        "https://serienstream.to/serie/game-of-thrones/staffel-8/episode-6",
    ),
    (
        "Bandi S01E01",
        "https://serienstream.to/serie/bandi-unter-geschwistern/staffel-1/episode-1",
    ),
    (
        "Gomorrha S01E01",
        "https://serienstream.to/serie/gomorrha-wie-alles-begann/staffel-1/episode-1",
    ),
    (
        "Safe S01E01",
        "https://serienstream.to/serie/safe/staffel-1/episode-1",
    ),
]


def external_host(value: str) -> str:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or not host:
        return ""
    if host in {"serienstream.to", "www.serienstream.to", "challenges.cloudflare.com"}:
        return ""
    return host


def first_server(html: str) -> tuple[str, str, int]:
    soup = BeautifulSoup(html or "", "lxml")
    buttons = list(soup.select("[data-play-url]"))
    if not buttons:
        return "", "", 0
    button = buttons[0]
    path = str(button.get("data-play-url") or "").strip()
    name = str(button.get("data-provider-name") or button.get_text(" ", strip=True) or "unknown").strip()
    if path.startswith("/"):
        path = "https://serienstream.to" + path
    return name, path, len(buttons)


def main() -> int:
    session = SessionManager(target_domain="serienstream.to")
    results = []

    for label, episode_url in CASES:
        row = {
            "series": label,
            "episode_status": "not_loaded",
            "server_count": 0,
            "server": "",
            "redirect_status": "not_attempted",
            "target_host": "",
        }
        try:
            html = session.get(episode_url, fast=True)
            row["episode_status"] = "loaded"
            server, redirect_url, server_count = first_server(html)
            row["server_count"] = server_count
            row["server"] = server
            if not redirect_url:
                row["redirect_status"] = "no_server"
            else:
                target = session.get_redirect_location(redirect_url, referer=episode_url)
                host = external_host(target or "")
                if host:
                    row["redirect_status"] = "external_embed"
                    row["target_host"] = host
                elif target == GATE_BLOCKED:
                    row["redirect_status"] = "gate_blocked"
                else:
                    row["redirect_status"] = "no_external_redirect"
        except ProviderBlockedError as exc:
            row["episode_status"] = "provider_blocked"
            row["redirect_status"] = exc.reason or "provider_blocked"
        except Exception as exc:  # diagnostic output must survive one bad case
            row["episode_status"] = "error"
            row["redirect_status"] = "error"
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)[:180]
        results.append(row)
        print("LIVE_SHARED_PROBE " + json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)

    summary = {
        "cases": len(results),
        "episode_pages_loaded": sum(row["episode_status"] == "loaded" for row in results),
        "external_embeds": sum(row["redirect_status"] == "external_embed" for row in results),
        "gates_or_blocks": sum(
            row["redirect_status"] in {"gate_blocked", "captcha_gate", "rate_limit"}
            or row["episode_status"] == "provider_blocked"
            for row in results
        ),
        "target_hosts": sorted({row["target_host"] for row in results if row["target_host"]}),
        "results": results,
    }
    print("LIVE_SHARED_PROBE_SUMMARY " + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)

    # Diagnostic PRs must publish their evidence even when the remote site is
    # gated. Only a completely unreachable test surface is an infrastructure
    # failure; functional success/failure is judged from the summary above.
    return 0 if summary["episode_pages_loaded"] >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
