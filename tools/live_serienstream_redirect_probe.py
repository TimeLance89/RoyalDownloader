from __future__ import annotations

import json
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from session_manager import GATE_BLOCKED, ProviderBlockedError, SessionManager

BASE_URL = "https://serienstream.to/"
CASES = [
    ("Breaking Bad S01E01", "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1"),
    ("Game of Thrones S08E06", "https://serienstream.to/serie/game-of-thrones/staffel-8/episode-6"),
    ("Bandi S01E01", "https://serienstream.to/serie/bandi-unter-geschwistern/staffel-1/episode-1"),
    ("Gomorrha Origins S01E01", "https://serienstream.to/serie/gomorrha-wie-alles-begann/staffel-1/episode-1"),
    ("Safe S01E01", "https://serienstream.to/serie/safe/staffel-1/episode-1"),
]


def is_external(value: str | None) -> bool:
    if not value or value == GATE_BLOCKED:
        return False
    host = (urlsplit(value).hostname or "").casefold()
    return host not in {"serienstream.to", "www.serienstream.to", "s.to", "www.s.to"}


def main() -> int:
    session = SessionManager(
        target_domain="serienstream.to",
        log_cb=lambda message: print(f"[royal] {message}", flush=True),
    )
    results = []

    for index, (name, episode_url) in enumerate(CASES, 1):
        started = time.monotonic()
        item = {
            "index": index,
            "name": name,
            "episode_url": episode_url,
            "hoster": "",
            "final_host": "",
            "result": "unknown",
        }
        try:
            html = session.get(episode_url)
            soup = BeautifulSoup(html, "lxml")
            buttons = soup.select("[data-play-url]")
            if not buttons:
                item["result"] = "no_hoster_buttons"
            else:
                button = buttons[0]
                item["hoster"] = str(button.get("data-provider-name") or "Hoster").strip()
                redirect_url = urljoin(BASE_URL, str(button.get("data-play-url") or "").strip())
                target = session.get_redirect_location(redirect_url, referer=episode_url)
                if target == GATE_BLOCKED:
                    item["result"] = "gate_blocked"
                elif target and is_external(target):
                    item["final_host"] = str(urlsplit(target).hostname or "")
                    item["result"] = "external_embed"
                elif target:
                    item["final_host"] = str(urlsplit(target).hostname or "")
                    item["result"] = "still_on_serienstream"
                else:
                    item["result"] = "unresolved"
        except ProviderBlockedError as exc:
            item["result"] = f"provider_blocked:{exc.reason}:{exc.status}"
        except Exception as exc:
            item["result"] = f"error:{type(exc).__name__}"
            item["error"] = str(exc)[:240]
        item["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(item)
        print("PROBE " + json.dumps(item, ensure_ascii=False), flush=True)

    summary = {
        "cases": len(results),
        "external_embeds": sum(r["result"] == "external_embed" for r in results),
        "blocked": sum("blocked" in r["result"] for r in results),
        "results": results,
    }
    print("PROBE_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
