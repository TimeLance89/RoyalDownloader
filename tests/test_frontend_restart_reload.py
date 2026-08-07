import asyncio
from pathlib import Path

from api_system_router import SERVER_INSTANCE, legacy_health, v1_health


ROOT = Path(__file__).resolve().parents[1]


def test_health_endpoints_expose_current_server_instance():
    legacy = asyncio.run(legacy_health())
    v1 = asyncio.run(v1_health())

    assert legacy == {"status": "ok", "instance": SERVER_INSTANCE}
    assert v1 == {"status": "ok", "api_version": 1, "instance": SERVER_INSTANCE}
    assert SERVER_INSTANCE


def test_frontend_reloads_when_server_process_changes():
    source = (ROOT / "web" / "api.js").read_text(encoding="utf-8")

    for contract in [
        "async function checkRoyalServerInstance()",
        'fetch("/api/health"',
        'cache: "no-store"',
        "royalServerInstance && royalServerInstance !== instance",
        "location.reload()",
        "scheduleRoyalServerHeartbeat",
        'document.addEventListener("visibilitychange"',
    ]:
        assert contract in source
