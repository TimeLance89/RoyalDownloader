"""Resolver contracts shared by runtime attribution and Source Sentinel."""
from dataclasses import dataclass, asdict, replace
import re
import hashlib
from urllib.parse import urlsplit

from media.hoster_intel import BASE_SCORE


@dataclass(frozen=True)
class HosterContract:
    hoster: str
    resolver: str
    capabilities: tuple
    markers: tuple = ()
    browser_fallback: bool = False
    probe_mode: str = "http_only"

    def public_dict(self):
        return asdict(self)


SPECIAL = {
    "voe": ("extract_stream_url", ("voe",)),
    "moflix": ("extract_stream_url", ("moflix",)),
    "veev": ("extract_stream_url", ("veev",)),
    "kinoger": ("extract_stream_url", ("fsst", "incvideo", "kinoger.be", "vidhide", "embed4me", "seekplays")),
    "doodstream": ("extract_doodstream_url", ("dood", "vide0", "d000d", "d0o0d", "dooood", "ds2play", "dsvplay", "ds2video")),
    "vidara": ("extract_vidara_url", ("vidara", "vidmatrix", "vidchamp", "vidachamp", "vidavaca", "viewdara", "thebesthost", "kinoger.pw")),
    "vidsonic": ("extract_vidsonic_url", ("vidsonic",)),
    "firestream": ("extract_firestream_url", ("firestream",)),
}
GENERIC = {"streamruby", "upcloud", "vidsrc", "closeload", "rapidrame", "upstream", "vinovo", "luluvid", "netu"}
BROWSER_EMBED_PROVIDERS = frozenset({"megakino", "sflix", "ridomovies", "mkissa"})
CONTRACTS = {}
for name in set(BASE_SCORE) | set(SPECIAL) | GENERIC:
    key = re.sub(r"[^a-z0-9]", "", name)
    if key.startswith("filmfrei24"):
        CONTRACTS[key] = HosterContract(key, "direct", ("recognition", "manifest", "direct_media"), ("filmfrei24",))
    else:
        resolver, markers = SPECIAL.get(key, ("yt_dlp", (key,)))
        browser = resolver == "extract_stream_url"
        CONTRACTS[key] = HosterContract(key, resolver, ("recognition", "embed", "redirect", "player", "resolver", "manifest", "direct_media"), markers, browser, "browser_capable" if browser else "runtime_only" if resolver == "yt_dlp" else "http_only")


def hoster_key(name, url=""):
    label = re.sub(r"[^a-z0-9]", "", str(name).lower())[:50]
    if label in CONTRACTS:
        return label
    domain = (urlsplit(url).hostname or "").lower()
    # Label aliases are used for attribution, never as trust for domain repair.
    for key, contract in CONTRACTS.items():
        if any(marker in label or marker in domain for marker in contract.markers):
            return key
    return label or "unknown"


def runtime_contract(name, url="", provider=""):
    key = hoster_key(name, url)
    contract = CONTRACTS.get(key, HosterContract(key, "yt_dlp", ("recognition", "embed", "redirect", "resolver", "manifest", "direct_media"), probe_mode="runtime_only"))
    # Production dispatches dedicated extractors before provider-specific embeds.
    if contract.resolver == "yt_dlp":
        browser = provider in BROWSER_EMBED_PROVIDERS
        return replace(contract, browser_fallback=browser, probe_mode="browser_capable" if browser else "http_only" if provider else "runtime_only")
    return contract


def source_contract(name, providers=()):
    """Conservative aggregate for a family used through multiple provider paths."""
    contracts = [runtime_contract(name, provider=provider) for provider in providers] or [runtime_contract(name)]
    return next((contract for contract in contracts if contract.browser_fallback), contracts[0])


def canary_identity(url):
    parsed = urlsplit(url)
    return hashlib.sha256(f"{parsed.hostname}{parsed.path}".encode()).hexdigest()[:24]


def media_identity(url):
    parsed = urlsplit(url)
    return hashlib.sha256(f"{parsed.hostname}{parsed.path}".encode()).hexdigest()[:24] if parsed.hostname else ""
