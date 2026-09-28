"""Deterministic candidate discovery, shadow validation and versioned rollback."""
from __future__ import annotations

import copy
import re
import time
import uuid
import ipaddress
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from application_services.provider_probe import diagnose, title_key
from providers.catalog import PROVIDER_CATALOG
from providers.probe_contracts import contract


def validate_profile(provider, profile):
    if not isinstance(profile, dict) or set(profile) - set(contract(provider).repair_fields):
        raise ValueError("Nicht unterstütztes Reparaturprofil")
    for key, value in profile.items():
        if key == "domain":
            if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,250})[a-z0-9]", value) or "." not in value:
                raise ValueError("Ungültige Reparaturdomain")
            try:
                ipaddress.ip_address(value)
            except ValueError:
                pass
            else:
                raise ValueError("Reparaturdomain darf keine IP-Adresse sein")
            if any(value in definition.domains for name, definition in PROVIDER_CATALOG.items() if name != provider):
                raise ValueError("Domain eines anderen Providers")
        elif key == "catalog_json_path":
            if not isinstance(value, list) or not 1 <= len(value) <= 4 or not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z_][\w-]{0,40}", x) for x in value):
                raise ValueError("Ungültiger JSON-Pfad")
        elif not isinstance(value, str) or not re.fullmatch(r"(?:article|h1|h2|img)(?:[.#][A-Za-z_][\w-]{0,60})?", value):
            raise ValueError("Ungültiger Selektor")
    return copy.deepcopy(profile)


def selector(node):
    if node.get("id") and re.fullmatch(r"[A-Za-z_][\w-]{0,60}", str(node["id"])):
        return f"{node.name}#{node['id']}"
    for name in node.get("class") or []:
        if re.fullmatch(r"[A-Za-z_][\w-]{0,60}", str(name)):
            return f"{node.name}.{name}"
    return node.name


def discover_candidates(provider, result, canaries):
    candidates = []
    catalog_failed = any(step["name"] == "catalog" and step.get("ok") is False for step in result["steps"])
    metadata_failed = any(step["name"] == "metadata" and step.get("ok") is False for step in result["steps"])
    known_titles = {title_key(ref["title"]) for ref in canaries}
    # Trusted-origin HTTPS redirects are evidence, never sufficient validation.
    trusted = {f"https://{host}/" for host in PROVIDER_CATALOG[provider].domains}
    redirects = [r for r in result["responses"] if r["origin"] in trusted and r["origin"] != r["final_origin"] and r["status"] == 200]
    hosts = {urlsplit(r["final_origin"]).hostname for r in redirects if r["final_origin"]}
    if len(hosts) == 1 and any(urlsplit(r["url"]).path in {"", "/"} for r in redirects):
        host = hosts.pop()
        if host not in PROVIDER_CATALOG[provider].domains:
            candidates.append({"domain": host})
    if provider == "filmpalast":
        votes, poster_votes = {}, {}
        for response in result["responses"]:
            soup = BeautifulSoup(response["text"], "lxml")
            for node in soup.find_all(["h1", "h2"]):
                if "/stream/" not in response["url"]:
                    continue
                key = title_key(node.get_text(" ", strip=True))
                if key in known_titles and len([n for n in soup.find_all(["h1", "h2"]) if title_key(n.get_text(" ", strip=True)) == key]) == 1:
                    votes.setdefault(selector(node), set()).add(key)
            articles = [node for node in soup.find_all("article") if node.select('h2 a[href*="/stream/"]')]
            if "/stream/" in response["url"]:
                posters = [node for node in soup.find_all("img") if not node.get("src") and "/files/movies/" in str(node.get("data-original") or "")]
                if len(posters) == 1:
                    poster_votes.setdefault(selector(posters[0]), set()).add(urlsplit(response["url"]).path)
            if catalog_failed and len(articles) >= 3 and len({selector(node) for node in articles}) == 1:
                choice = selector(articles[0])
                if choice != "article.liste":
                    candidates.append({"catalog_selector": choice})
        choices = [choice for choice, titles in votes.items() if len(titles) >= 3 and choice != "h2.bgDark"]
        if metadata_failed and len(choices) == 1:
            candidates.append({"title_selector": choices[0]})
        poster_choices = [choice for choice, pages in poster_votes.items() if len(pages) >= 3]
        if metadata_failed and len(poster_choices) == 1:
            candidates.append({"poster_selector": poster_choices[0]})
    if provider == "megakino" and catalog_failed:
        import json

        def paths(value, path=()):
            if len(path) > 4:
                return []
            if isinstance(value, list) and len(value) >= 3 and all(isinstance(row, dict) and row.get("_id") and row.get("title") for row in value):
                return [list(path)]
            if isinstance(value, dict):
                return [found for key, child in value.items() if re.fullmatch(r"[A-Za-z_][\w-]{0,40}", str(key)) for found in paths(child, (*path, key))]
            return []

        for response in result["responses"]:
            if "/data/browse/" not in response["url"]:
                continue
            try:
                choices = paths(json.loads(response["text"]))
            except ValueError:
                continue
            if len(choices) == 1 and choices[0] != ["movies"]:
                candidates.append({"catalog_json_path": choices[0]})
    unique = []
    for candidate in candidates:
        try:
            candidate = validate_profile(provider, candidate)
        except ValueError:
            continue
        if candidate not in unique:
            unique.append(candidate)
    if len(unique) > 1 and len({key for candidate in unique for key in candidate}) == sum(len(candidate) for candidate in unique):
        unique.insert(0, {key: value for candidate in unique for key, value in candidate.items()})
    return unique[:3]


class ProviderRepair:
    def __init__(self, store, probe):
        self.store, self.probe = store, probe

    def profile(self, provider):
        try:
            return validate_profile(provider, self.store.entry(provider, ("profile",)).get("profile", {}))
        except ValueError:
            return {}

    def validate(self, provider, candidate, current, canaries):
        profile = validate_profile(provider, {**self.profile(provider), **candidate})
        shadow = self.probe.run(provider, "full", profile, canaries)
        known = {ref["identity"] for ref in canaries}
        successful = {ref["identity"] for ref in shadow["details"] if ref["ok"] and ref["identity"] in known}
        prior_success = {ref["identity"] for ref in current["details"] if ref["ok"]}
        metadata_preserved = all(
            all(not present or ref.get("metadata", {}).get(field) for field, present in expected.get("metadata", {}).items())
            and ref.get("hoster_count", 0) >= expected.get("hoster_count", 0)
            and (not expected.get("cover_identity") or ref.get("cover_identity") == expected["cover_identity"])
            for ref in shadow["details"] if ref["ok"]
            for expected in [*canaries, *current["details"]] if expected["identity"] == ref["identity"]
        )
        hosters_ok = all(step.get("ok") is True for step in shadow["steps"] if step["name"] == "hoster_structure")
        current_catalog = sum(step.get("ok") is True for step in current["steps"] if step["name"] == "catalog")
        candidate_catalog = sum(step.get("ok") is True for step in shadow["steps"] if step["name"] == "catalog")
        improved = len(successful) > len(prior_success) or candidate_catalog > current_catalog
        if "domain" in candidate:
            improved = True
        passed = len(successful) >= 3 and prior_success <= successful and hosters_ok and metadata_preserved and diagnose(shadow) == "healthy" and improved
        evidence = {"known_detail_pages": len(known), "validated_detail_pages": len(successful), "current_detail_pages": len(prior_success),
                    "catalog_before": current_catalog, "catalog_after": candidate_catalog, "hosters_valid": hosters_ok,
                    "metadata_preserved": metadata_preserved, "shadow_passed": passed, "steps": shadow["steps"]}
        return profile, evidence

    def propose(self, provider, current, canaries):
        output = []
        if any(step["code"] in {"verification_required", "rate_limit"} for step in current["steps"]):
            return output
        for candidate in discover_candidates(provider, current, canaries):
            profile, evidence = self.validate(provider, candidate, current, canaries)
            repair = {"id": uuid.uuid4().hex, "version": 1, "created_at": time.time(), "reason": "validated_structure_change",
                      "previous_profile": self.profile(provider), "profile": profile, "validation": evidence,
                      "confidence": "high" if evidence["shadow_passed"] else "low", "state": "available" if evidence["shadow_passed"] else "needs_attention"}
            self.store.add_repair(provider, repair)
            output.append(repair)
            if evidence["shadow_passed"]:
                break
        return output

    def activate(self, provider, repair_id):
        with self.store.lock:
            entry = self.store.entry(provider)
            repair = next((r for r in entry.get("repairs", []) if r["id"] == repair_id), None)
            if not repair or repair["confidence"] != "high" or not repair["validation"]["shadow_passed"]:
                raise ValueError("Reparatur ist nicht eindeutig validiert")
            if repair["state"] != "available" or repair["previous_profile"] != self.profile(provider):
                raise ValueError("Reparatur ist nicht mehr aktuell; erneut prüfen")
            if entry.get("active_repair"):
                raise ValueError("Aktive Reparatur zuerst zurücksetzen")
            repair["state"] = "active"
            repair["activated_at"] = time.time()
            self.store.update(provider, profile=validate_profile(provider, repair["profile"]), active_repair=repair_id,
                              repairs=entry["repairs"], repair_failures=[])
            self.store.record(provider, {"event": "repair_activated", "repair_id": repair_id, "reason": "shadow_validation_passed"})

    def rollback(self, provider, repair_id, reason="administrator"):
        with self.store.lock:
            entry = self.store.entry(provider)
            if entry.get("active_repair") != repair_id:
                raise ValueError("Reparatur ist nicht aktiv")
            repair = next(r for r in entry["repairs"] if r["id"] == repair_id)
            repair["state"] = "rolled_back"
            self.store.update(provider, profile=repair["previous_profile"], active_repair=None, repairs=entry["repairs"], repair_failures=[])
            self.store.record(provider, {"event": "repair_rolled_back", "repair_id": repair_id, "reason": reason})
