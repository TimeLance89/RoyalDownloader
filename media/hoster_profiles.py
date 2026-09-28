"""Non-executable player profiles: bounded selectors and JSON key/index paths."""
import copy
import json
import re
import ipaddress
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from core.source_urls import valid_source_link


def validate_profile(_hoster, profile):
    allowed = {"player_selector", "player_attribute", "player_json_path", "media_kind", "embed_domain", "embed_path_prefix"}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise ValueError("Nicht unterstütztes Hosterprofil")
    if "embed_domain" in profile:
        domain = profile["embed_domain"]
        if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,250})[a-z0-9]", domain) or "." not in domain or domain.endswith((".local", ".internal", ".localhost", ".lan", ".home")):
            raise ValueError("Ungültige Embed-Domain")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError("Embed-Domain darf keine IP-Adresse sein")
    if "embed_path_prefix" in profile and (not isinstance(profile["embed_path_prefix"], str) or not re.fullmatch(r"/(?:[a-zA-Z0-9_-]{1,20}/){0,3}", profile["embed_path_prefix"])):
        raise ValueError("Ungültiger Embed-Pfad")
    if "player_selector" in profile and (not isinstance(profile["player_selector"], str) or not re.fullmatch(r"(?:script|video|source|div)(?:[.#][A-Za-z_][\w-]{0,60})?", profile["player_selector"])):
        raise ValueError("Ungültiger Player-Selektor")
    if "player_attribute" in profile and (not isinstance(profile["player_attribute"], str) or not re.fullmatch(r"(?:src|data-[a-z][a-z0-9-]{0,40})", profile["player_attribute"])):
        raise ValueError("Ungültiges Player-Attribut")
    if "player_json_path" in profile:
        path = profile["player_json_path"]
        if not isinstance(path, list) or not 1 <= len(path) <= 8 or not all((type(key) is int and 0 <= key <= 10) or (isinstance(key, str) and re.fullmatch(r"[A-Za-z_][\w-]{0,40}", key)) for key in path):
            raise ValueError("Ungültiger Player-JSON-Pfad")
    if profile.get("media_kind", "hls") not in {"hls", "mp4", "dash"}:
        raise ValueError("Ungültiger Medientyp")
    return copy.deepcopy(profile)


def profile_url(url, profile):
    validate_profile("", profile)
    parsed = urlsplit(url)
    path = parsed.path
    if profile.get("embed_path_prefix"):
        path = profile["embed_path_prefix"] + parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return urlunsplit(("https" if profile.get("embed_domain") else parsed.scheme, profile.get("embed_domain") or parsed.netloc, path, parsed.query, ""))


def media_result(value, base="", kind=None):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    url = urljoin(base, value.strip())
    if not valid_source_link(url):
        return None
    path = urlsplit(url).path.lower()
    detected = "hls" if path.endswith(".m3u8") else "dash" if path.endswith(".mpd") else "mp4" if path.endswith(".mp4") else None
    if not detected or (kind and kind != detected):
        return None
    from media.extractor import _is_test_url
    return None if _is_test_url(url) else (url, detected)


def extract_profile(text, base, profile):
    profile = validate_profile("", profile)
    if not profile or not (profile.get("player_selector") or profile.get("player_json_path")) or len(text) > 2_000_000:
        return None
    if any(marker in text.lower() for marker in ("captcha", "turnstile", "cf-chl-", "widevine", "drm_license", 'type="password"')):
        return None
    soup = BeautifulSoup(text, "lxml")
    nodes = soup.select(profile.get("player_selector", "script"))
    if len(nodes) != 1:
        return None
    node = nodes[0]
    value = node.get(profile["player_attribute"]) if profile.get("player_attribute") else node.get_text()
    if profile.get("player_json_path"):
        try:
            value = json.loads(value)
            for key in profile["player_json_path"]:
                value = value[key]
        except (ValueError, TypeError, KeyError, IndexError):
            return None
    return media_result(value, base, profile.get("media_kind"))


def discover_profiles(text, base):
    """Return only unique structured media paths; ambiguity stays manual."""
    if len(text) > 2_000_000:
        return []
    soup = BeautifulSoup(text, "lxml")
    found = []

    def visit(value, path=(), depth=0):
        if depth > 7:
            return []
        result = media_result(value, base)
        if result:
            return [(list(path), result[1])]
        if isinstance(value, dict):
            return [match for key, child in list(value.items())[:64] if re.fullmatch(r"[A-Za-z_][\w-]{0,40}", str(key)) for match in visit(child, (*path, key), depth + 1)]
        if isinstance(value, list):
            return [match for index, child in enumerate(value[:11]) for match in visit(child, (*path, index), depth + 1)]
        return []

    for node in soup.find_all(["script", "video", "source", "div"], limit=128):
        ident = str(node.get("id", ""))
        selector = f"{node.name}#{ident}" if re.fullmatch(r"[A-Za-z_][\w-]{0,60}", ident) else node.name
        if len(soup.select(selector)) != 1:
            continue
        for attr, value in list(node.attrs.items())[:16]:
            if re.fullmatch(r"(?:src|data-[a-z][a-z0-9-]{0,40})", attr) and (result := media_result(value, base)):
                found.append({"player_selector": selector, "player_attribute": attr, "media_kind": result[1]})
        if node.name == "script":
            try:
                matches = visit(json.loads(node.get_text()))
            except (ValueError, TypeError, RecursionError):
                continue
            if len(matches) == 1 and matches[0][0]:
                found.append({"player_selector": selector, "player_json_path": matches[0][0], "media_kind": matches[0][1]})
    return [validate_profile("", profile) for profile in found[:3]]
