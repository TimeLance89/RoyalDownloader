from fastapi.testclient import TestClient

import server
from api_domain_routers import DOMAIN_ROUTERS


def test_every_target_domain_owns_routes():
    assert all(router.routes for router in DOMAIN_ROUTERS.values())


def test_router_extraction_preserves_public_health_contract():
    client = TestClient(server.app)
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {
        "status": "ok", "api_version": 1,
    }
