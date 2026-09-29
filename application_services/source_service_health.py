"""Presentation-only source availability; never changes routing or repair eligibility."""

MEDIA_TYPES = ("movies", "series", "anime")
UNAVAILABLE = {"broken", "offline", "blocked"}


def fresh(timestamp, now):
    return bool(timestamp) and 0 <= now - timestamp < 86400


def video_state(row, now):
    state = row.get("diagnosis", "unknown")
    metric = row.get("metrics_24h", {})
    # A successful real browser resolve outweighs an incomplete HTTP probe.
    if state not in UNAVAILABLE and fresh(row.get("last_success_at"), now) and metric.get("attempts", 0) and (metric.get("success_rate") or 0) >= .5:
        return "available"
    if state == "healthy" and fresh(row.get("last_check_at"), now):
        return "available"
    if state in UNAVAILABLE and fresh(max(row.get("last_check_at") or 0, row.get("last_failure_at") or 0), now):
        return "unavailable"
    if state in {"needs_attention", "repair_available", "repairing"}:
        runtime_failed = fresh(row.get("last_failure_at"), now) and metric.get("attempts", 0) >= 3 and metric.get("success_rate") is not None and metric["success_rate"] < .3
        failed_samples = {step.get("sample") for step in row.get("steps", []) if step.get("name") == "resolver" and step.get("ok") is False and step.get("code") in {"parser_error", "media_invalid"} and step.get("sample")}
        complete_http_failed = row.get("contract", {}).get("probe_mode") == "http_only" and fresh(row.get("last_check_at"), now) and len(failed_samples) >= 5
        if runtime_failed or complete_http_failed:
            return "unavailable"
    return "unconfirmed"


def source_service_health(providers, hosters, now, enabled_languages=None):
    """Evaluate configured media/language paths, not counts of red diagnostic badges.

    Unknown or stale evidence is not a confirmed outage or confirmed availability.
    Associations are observed provider/hoster edges, not proof of every title's
    availability. This summary describes tested paths and explicitly retains that
    limitation; it never guarantees a particular download.
    """
    active = [p for p in providers if p.get("enabled")]
    video = {h["hoster"]: video_state(h, now) for h in hosters}
    paths, provider_states = {}, {}
    for provider in active:
        key = provider["provider"]
        runtime = provider.get("runtime", {})
        current_success = fresh(runtime.get("last_runtime_success_at", runtime.get("last_success_at")), now)
        confirmed = runtime.get("state") == "healthy" and (current_success or provider.get("diagnosis") == "healthy" and fresh(provider.get("last_check_at"), now))
        # Diagnostics alone cannot remove a production route. The circuit
        # breaker/routing contract is authoritative for provider availability.
        routable = provider.get("routing", {}).get("allowed", runtime.get("state") not in {"blocked", "cooldown", "probing"})
        unavailable = not routable
        related = [h for h in hosters if key in h.get("providers", [])]
        # Missing observed edges remain unconfirmed rather than presumed working.
        states = [video[h["hoster"]] for h in related]
        route = "unavailable" if unavailable or states and all(s == "unavailable" for s in states) else "available" if confirmed and "available" in states else "unconfirmed"
        provider_states[key] = route
        for media in provider.get("enabled_media_types", provider["contract"]["media_types"]):
            if media in MEDIA_TYPES:
                supported = tuple(dict.fromkeys(provider.get("content_languages") or [provider.get("content_language", "default")]))
                for language in supported:
                    if enabled_languages is not None and language not in enabled_languages:
                        continue
                    path_route = route
                    # Provider-wide health does not prove every track capability.
                    if len(supported) > 1 and route != "unavailable":
                        proven = fresh(provider.get("language_evidence", {}).get(media, {}).get(language), now)
                        path_route = "available" if proven and "available" in states else "unconfirmed"
                    paths.setdefault((media, language), []).append((key, path_route))
    coverage, path_rows = {}, []
    for (media, language), routes in paths.items():
        good = sum(state == "available" for _, state in routes)
        unknown = sum(state == "unconfirmed" for _, state in routes)
        if good >= min(2, len(routes)):
            state = "healthy"
        elif good:
            state = "healthy" if good + unknown == len(routes) else "degraded"
        else:
            state = "unconfirmed" if unknown else "action_required"
        path_rows.append({"media_type": media, "language": language, "state": state, "available_sources": good, "configured_sources": len(routes), "unconfirmed_sources": unknown})
    severity = {"not_configured": -1, "healthy": 0, "unconfirmed": 1, "degraded": 2, "action_required": 3}
    for media in MEDIA_TYPES:
        rows = [p for p in path_rows if p["media_type"] == media]
        coverage[media] = max((p["state"] for p in rows), key=severity.get, default="not_configured")
    overall = max(coverage.values(), key=severity.get)
    if not paths:
        overall = "action_required"
    service = "healthy" if overall == "healthy" else "action_required" if overall == "action_required" else "degraded"
    source_impacts = {"providers": {}, "hosters": {}}
    for provider in active:
        related = [p for p in path_rows if provider["provider"] in {key for key, _ in paths[(p["media_type"], p["language"])]}]
        impact = "blocking" if any(p["state"] == "action_required" for p in related) else "relevant" if any(p["state"] == "degraded" for p in related) else "unconfirmed" if any(p["state"] == "unconfirmed" for p in related) else "none"
        if provider_states[provider["provider"]] == "available":
            impact = "none"
        source_impacts["providers"][provider["provider"]] = {"availability": provider_states[provider["provider"]], "impact": impact, "action_required": impact == "blocking", "routable": provider.get("routing", {}).get("allowed", provider.get("runtime", {}).get("state") not in {"blocked", "cooldown", "probing"})}
    for hoster in hosters:
        related = [source_impacts["providers"][key] for key in hoster.get("providers", []) if key in source_impacts["providers"]]
        impact = max((p["impact"] for p in related), key={"none": 0, "unconfirmed": 1, "relevant": 2, "blocking": 3}.get, default="none")
        if video[hoster["hoster"]] == "available":
            impact = "none"
        source_impacts["hosters"][hoster["hoster"]] = {"availability": video[hoster["hoster"]], "impact": impact, "action_required": impact == "blocking"}
    return {"service_health": service, "user_impact": "none" if service == "healthy" else "blocking" if service == "action_required" else "unconfirmed" if overall == "unconfirmed" else "reduced_redundancy",
            "action_required": service == "action_required", "coverage": coverage, "paths": path_rows, "sources": source_impacts,
            "active_sources": len(active), "available_video_services": sum(video[h["hoster"]] == "available" and any(p["provider"] in h.get("providers", []) for p in active) for h in hosters),
            "last_check_at": max((p.get("last_check_at") or 0 for p in active), default=0)}
