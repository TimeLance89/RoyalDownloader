"""Stable health vocabulary at the API boundary, independent of media ownership."""

HEALTH_STATES = frozenset({"healthy", "degraded", "offline", "auth_failed", "disabled", "unknown"})


def integration_health(module: dict) -> dict:
    """Normalize explicit controller facts; never classify translated error messages."""
    reported = module.get("health")
    if module.get("enabled") is False:
        state = "disabled"
    elif reported in {"offline", "auth_failed", "disabled", "degraded"}:
        state = reported
    elif reported == "healthy":
        state = "degraded" if module.get("missing_optional") else "healthy"
    elif reported == "unavailable":
        # Existing controllers expose a boolean failure, not its cause. It must
        # not be presented as a network outage or an authentication failure.
        state = "degraded"
    else:
        state = "unknown"
    return {"state": state, "detail": str(module.get("health_detail") or "")}


def with_integration_health(payload: dict) -> dict:
    return {
        **payload,
        "health_schema_version": 1,
        "modules": [
            {**module, "integration_health": integration_health(module)}
            for module in payload.get("modules", [])
        ],
    }
