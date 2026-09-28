"""Conservative structured-player recovery on the shared repair journal."""
import uuid
from urllib.parse import urlsplit
from application_services.source_repair_journal import SourceRepairJournal
from media.hoster_profiles import validate_profile, discover_profiles, profile_url


class HosterRepair(SourceRepairJournal):
    validate_profile = staticmethod(validate_profile)

    def __init__(self, store, probe):
        self.store, self.probe = store, probe

    def profile(self, hoster):
        try:
            return validate_profile(hoster, self.store.entry(hoster, ("profile",)).get("profile", {}))
        except ValueError:
            return {}

    def validate(self, hoster, candidate, current, canaries):
        profile = validate_profile(hoster, candidate)
        shadow = self.probe.run(hoster, "full", profile, canaries)
        known = {row["identity"] for row in canaries}
        before = {row["identity"] for row in current["details"] if row["ok"]}
        after = {row["identity"] for row in shadow["details"] if row["ok"]}
        # Independent success-established identities; no voting from unknown pages.
        proven = {row["identity"] for row in canaries if row.get("proven")}
        identities_preserved = all(row.get("media_signature") and row["media_signature"] == expected.get("media_signature") for row in shadow["details"] for expected in canaries if row["identity"] == expected["identity"])
        routing = bool(candidate.get("embed_domain") or candidate.get("embed_path_prefix"))
        domain_identity = True
        if candidate.get("embed_domain"):
            with self.store.lock:
                domain_identity = not any(candidate["embed_domain"] in entry.get("domains", []) for key, entry in self.store.store.data["hosters"].items() if key != hoster)
        routing_proven = {row["identity"] for row in current["responses"] if row.get("original_url") and urlsplit(row["original_url"]).scheme == "https" and urlsplit(row["url"]).scheme == "https" and profile_url(row["original_url"], candidate).split("?", 1)[0] == row["url"].split("?", 1)[0]}
        improvement = before < after or routing
        passed = bool(len(known) >= 5 and known <= proven and after == known and improvement and identities_preserved and domain_identity and (not routing or known <= routing_proven))
        return profile, {"known_detail_pages": len(known), "validated_detail_pages": len(after), "current_detail_pages": len(before), "shadow_passed": passed, "identity_preserved": identities_preserved, "steps": shadow["steps"]}

    def propose(self, hoster, current, canaries):
        if any(row["code"] in {"blocked", "rate_limit", "removed", "timeout", "network_error", "budget_exhausted"} for row in current["details"]):
            return []
        votes = {}
        domain_votes = {}
        for response in current["responses"]:
            original = urlsplit(response.get("original_url", response["url"]))
            final = urlsplit(response["url"])
            if original.scheme == final.scheme == "https" and (original.hostname != final.hostname or original.path != final.path) and original.path.rstrip("/").rsplit("/", 1)[-1] == final.path.rstrip("/").rsplit("/", 1)[-1]:
                prefix = final.path.rsplit("/", 1)[0] + "/" if original.path != final.path else ""
                domain_votes.setdefault((final.hostname, prefix), set()).add(response["identity"])
            for profile in discover_profiles(response["text"], response["url"]):
                key = repr(sorted(profile.items()))
                item = votes.setdefault(key, [profile, set()])
                item[1].add(response["identity"])
        candidates = [profile for profile, identities in votes.values() if len(identities) >= 3]
        domains = [domain for domain, identities in domain_votes.items() if len(identities) >= 5]
        if len(domains) == 1:
            try:
                domain = validate_profile(hoster, {"embed_domain": domains[0][0], **({"embed_path_prefix": domains[0][1]} if domains[0][1] else {})})
                from providers.catalog import PROVIDER_CATALOG
                if not any(domains[0][0] in definition.domains for definition in PROVIDER_CATALOG.values()):
                    candidates = [{**profile, **domain} for profile in candidates] if candidates else [domain]
            except ValueError:
                pass
        output = []
        for candidate in candidates[:3]:
            profile, evidence = self.validate(hoster, candidate, current, canaries)
            # More than one credible interpretation is ambiguous, even if both work.
            high = evidence["shadow_passed"] and len(candidates) == 1
            evidence["shadow_passed"] = high
            repair = {"id": uuid.uuid4().hex, "version": 1, "created_at": self.store.clock(), "reason": "player_structure_changed", "previous_profile": self.profile(hoster), "profile": profile, "validation": evidence, "confidence": "high" if high else "low", "state": "available" if high else "needs_attention"}
            self.store.add_repair(hoster, repair)
            output.append(repair)
        return output
