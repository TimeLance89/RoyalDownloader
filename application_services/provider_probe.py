"""Non-download probes through existing provider adapters."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, is_dataclass
from urllib.parse import urlsplit

from core.source_urls import valid_source_link
from providers.catalog import PROVIDER_CATALOG
from providers.probe_contracts import contract, create_adapter
from providers.sentinel_runtime import ProbeFailure, probe_context


def payload(item):
    return asdict(item) if is_dataclass(item) else item if isinstance(item, dict) else {}


def identity(value):
    normalized = str(value).strip()
    if normalized.startswith(("http://", "https://")):
        normalized = urlsplit(normalized).path.strip("/")
    normalized = re.sub(r"^[a-z][a-z0-9_]*:", "", normalized)
    normalized = re.sub(r"^(?:stream/|serie/|anime/stream/)", "", normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]


def reference(item, media_type):
    data = payload(item)
    source = str(data.get("base_slug") or data.get("slug") or data.get("id") or data.get("anime_id") or data.get("url") or "")
    if not source or not re.fullmatch(r"[\w:/.-]{1,240}", source):
        return None
    title = str(data.get("title") or "").strip()[:160]
    if not title or "http" in title.casefold():
        return None
    return {"source": source, "title": title, "media_type": media_type, "identity": identity(source)}


def failure(exc):
    if isinstance(exc, ProbeFailure):
        return exc.code, exc.status
    status = int(getattr(exc, "status", 0) or getattr(getattr(exc, "response", None), "status_code", 0) or 0)
    if status == 429:
        return "rate_limit", status
    if status in {401, 403} or getattr(exc, "reason", "") in {"captcha_gate", "cloudflare_gate", "rate_limit"}:
        return "verification_required", status
    if status == 404:
        return "removed", status
    if status >= 500:
        return "temporary_http", status
    if isinstance(exc, (KeyError, TypeError, ValueError, AttributeError)):
        return "parser_error", status
    return "network_error", status


def title_key(value):
    return re.sub(r"\W+", "", re.sub(r"\s*\[[^\]]+\]\s*$", "", str(value)).casefold())


def episode_source(provider, detail):
    """Use existing episode identifiers, including anime track contracts."""
    data = payload(detail)
    episodes = getattr(detail, "all_episodes", []) or data.get("episodes", [])
    if provider == "aniworld":
        from providers.aniworld import aniworld_episode_slug
        for item in episodes:
            episode = payload(item)
            tracks = episode.get("tracks", ())
            if tracks:
                return aniworld_episode_slug(data["id"], tracks[0], episode["season"], episode["number"])
    elif provider == "mkissa":
        from providers.mkissa import anime_episode_slug
        for track, count in data.get("translations", {}).items():
            if count:
                return anime_episode_slug(data["id"], track, 1)
    return payload(episodes[0]).get("slug") if episodes else None




class ProviderProbe:
    def __init__(self, factory=create_adapter):
        self.factory = factory

    def run(self, provider, intensity="standard", profile=None, canaries=()):
        adapter = self.factory(provider)
        steps, references, details, hoster_candidates = [], [], [], []
        limit = 5 if intensity == "full" else 3

        def step(name, function, check=bool, sample=""):
            started = time.monotonic()
            before = len(context.responses)
            failures_before = len(context.failures)
            try:
                result = function()
                ok = bool(check(result))
                row = {"name": name, "sample": sample, "ok": ok, "code": "ok" if ok else "empty_extraction", "http_status": context.responses[-1]["status"] if len(context.responses) > before else 0}
                if len(context.failures) > failures_before:
                    code, status = context.failures[failures_before]
                    row.update(ok=False, code=code, http_status=status)
            except Exception as exc:
                code, status = failure(exc)
                row = {"name": name, "sample": sample, "ok": False, "code": code, "http_status": status}
                result = None
            row["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
            steps.append(row)
            return result

        try:
            with probe_context(provider, profile, seconds=90 if intensity == "full" else 60, maximum_requests=48 if intensity == "full" else 32) as context:
                homepage = f"https://{PROVIDER_CATALOG[provider].domains[0]}/"
                step("connectivity", lambda: adapter.session.get(homepage), lambda response: bool(response))
                # A failed/blocked connectivity check does not trigger another recovery mechanism.
                if not steps[-1]["ok"]:
                    return {"steps": steps, "canaries": [], "details": [], "responses": context.responses}
                for media_type in contract(provider).media_types:
                    if media_type == "anime":
                        rows = step("catalog", lambda: adapter.browse(mode="latest", limit=8), lambda data: bool(data.get("results")), sample=media_type)
                        rows = (rows or {}).get("results", [])
                    else:
                        rows = step("catalog", lambda: adapter.list_movies("new", 1) if media_type == "movies" else adapter.list_series(1), sample=media_type) or []
                    refs = [ref for item in rows[:8] if (ref := reference(item, media_type))]
                    if rows and not refs:
                        steps[-1].update(ok=False, code="invalid_reference")
                    references.extend(refs)
                    if intensity == "light":
                        continue
                    candidates = [ref for ref in canaries if ref.get("media_type") == media_type] + refs
                    seen = set()
                    candidates = [ref for ref in candidates if not (ref["identity"] in seen or seen.add(ref["identity"]))][:limit]
                    if refs:
                        query = refs[0]["title"]
                        step("search", lambda: adapter.browse(mode="search", query=query, limit=8) if media_type == "anime" else adapter.search(query) if media_type == "movies" else adapter.search_series(query), lambda data: bool(data.get("results")) if isinstance(data, dict) else bool(data), sample=media_type)
                    for ref in candidates:
                        sample = ref["identity"]
                        detail = step("detail", lambda: adapter.get_anime(ref["source"], force=True) if media_type == "anime" else adapter.get_movie(ref["source"]) if media_type == "movies" else adapter.get_series(ref["source"]), sample=sample)
                        detail_code = steps[-1]["code"]
                        data = payload(detail)
                        match = bool(data.get("title")) and title_key(data["title"]) == title_key(ref["title"])
                        metadata = {field: bool(data.get(field)) for field in ("title", "cover_url", "description", "genres", "year")}
                        metadata_ok = match and all(not expected or metadata.get(field) for field, expected in ref.get("metadata", {}).items())
                        unavailable = not detail and detail_code in {"removed", "budget_exhausted", "rate_limit", "network_error", "temporary_http", "verification_required", "response_too_large"}
                        steps.append({"name": "metadata", "sample": sample, "ok": None if unavailable else metadata_ok, "code": detail_code if unavailable else "ok" if metadata_ok else "metadata_changed" if match else "identity_mismatch", "duration_ms": 0, "fields": metadata, "http_status": 0})
                        hosters = data.get("hosters") or []
                        languages = []
                        if media_type != "movies" and intensity == "full" and detail:
                            source = episode_source(provider, detail)
                            if source:
                                episode = step("episode_detail", lambda: adapter.get_episode(source) if media_type == "anime" else adapter.get_movie(source), sample=sample)
                                hosters = payload(episode).get("hosters") or []
                                if metadata_ok and any(valid_source_link(payload(h).get("url") or "") for h in hosters):
                                    language = payload(episode).get("content_language")
                                    if language in PROVIDER_CATALOG[provider].content_languages:
                                        languages = [language]
                        if metadata_ok:
                            hoster_candidates.extend({"name": str(payload(hoster).get("name") or ""), "url": str(payload(hoster).get("url") or "")} for hoster in hosters[:20])
                        if (media_type == "movies" or intensity == "full") and not unavailable:
                            valid = [payload(hoster) for hoster in hosters if valid_source_link(payload(hoster).get("url") or "")]
                            steps.append({"name": "hoster_structure", "sample": sample, "ok": bool(valid), "code": "ok" if valid else "missing_hosters", "count": len(valid), "duration_ms": 0, "http_status": 0})
                            steps.append({"name": "source_structure", "sample": sample, "ok": bool(valid), "code": "links_only" if valid else "missing_links", "duration_ms": 0, "http_status": 0})
                        else:
                            steps.append({"name": "hoster_structure", "sample": sample, "ok": None, "code": detail_code if unavailable else "full_probe_required", "duration_ms": 0, "http_status": 0})
                        details.append({**ref, "ok": metadata_ok and bool(detail), "metadata": metadata,
                                        "content_languages": languages,
                                        "cover_identity": identity(data["cover_url"]) if data.get("cover_url") else "",
                                        "hoster_count": len(hosters), "hoster_names": sorted({str(payload(h).get("name") or "")[:50] for h in hosters})[:20]})
                return {"steps": steps, "canaries": references, "details": details, "responses": context.responses, "hoster_candidates": hoster_candidates[:100]}
        finally:
            close = getattr(adapter.session, "close", None)
            if close:
                close()


def diagnose(result, previous=None):
    failed = [step for step in result["steps"] if step.get("ok") is False and step["code"] != "removed"]
    codes = {step["code"] for step in failed}
    if "domain_offline" in codes:
        return "offline"
    if "verification_required" in codes:
        return "blocked"
    if codes & {"rate_limit", "network_error", "temporary_http", "budget_exhausted", "response_too_large"}:
        return "degraded"
    if not failed:
        return "healthy"
    bad_details = {step["sample"] for step in failed if step["name"] in {"detail", "metadata", "hoster_structure"} and step["code"] != "removed"}
    if len(bad_details) >= 2 or (previous and any(step["name"] == "catalog" for step in failed)):
        return "broken"
    return "degraded"
