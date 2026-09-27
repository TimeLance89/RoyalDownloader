from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_reloads_when_backend_build_changes():
    source = (ROOT / "web/js/features/system/server-build.js").read_text(encoding="utf-8")

    for contract in [
        "async function refresh(current = scope)",
        'client.get("/api/v1/capabilities"',
        'cache: "no-store"',
        "build && build !== nextBuild",
        "location.reload()",
        "schedule(current)",
        'scope.listen(document, "visibilitychange"',
    ]:
        assert contract in source


def test_public_health_contract_remains_unchanged():
    source = (ROOT / "api" / "api_system_router.py").read_text(encoding="utf-8")

    assert 'return {"status": "ok"}' in source
    assert 'return {"status": "ok", "api_version": 1}' in source
    assert "SERVER_INSTANCE" not in source
