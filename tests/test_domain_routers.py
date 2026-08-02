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


def _walk_routes(routes):
    for route in routes:
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            yield from _walk_routes(nested_router.routes)
        else:
            yield route


def test_api_route_method_pairs_are_unique_and_explicitly_owned():
    pairs = []
    domain_owned_routes = {
        id(route)
        for router in DOMAIN_ROUTERS.values()
        for route in router.routes
    }
    for route in _walk_routes(server.app.routes):
        path = getattr(route, "path", "")
        if not path.startswith(("/api/", "/ws")):
            continue
        # Extracted routers are represented by FastAPI as nested router nodes;
        # legacy handlers remain explicitly assigned to a domain router.
        assert id(route) in domain_owned_routes or path in {
            "/api/health",
            "/api/v1/health",
            "/api/v1/diagnostics/caches",
        }
        for method in getattr(route, "methods", ()) or ("WEBSOCKET",):
            pairs.append((method, path))

    assert len(pairs) == len(set(pairs))
    assert {
        ("GET", "/api/health"),
        ("GET", "/api/v1/health"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/queue/add"),
        ("POST", "/api/v1/queue/add"),
        ("WEBSOCKET", "/ws"),
        ("WEBSOCKET", "/api/v1/ws"),
    }.issubset(pairs)
