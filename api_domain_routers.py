"""Incremental ownership boundary for legacy API handlers.

Handlers are still moved out of the composition root one domain at a time,
but every route is already owned by an explicit FastAPI router. This keeps the
public contract unchanged and makes later source extraction mechanical.
"""

from fastapi import APIRouter, FastAPI

from api_automation_policy_router import router as automation_policy_router
from api_serienstream_verification_router import router as serienstream_verification_router
from api_storage_router import router as storage_router

# Administration already owns the storage router. Attach supplemental admin
# surfaces before the legacy composition root migrates routes into this owner.
for supplemental_router in (
    serienstream_verification_router,
    automation_policy_router,
):
    for route in supplemental_router.routes:
        if route not in storage_router.routes:
            storage_router.routes.append(route)

DOMAIN_ROUTERS = {
    "discovery": APIRouter(tags=["discovery"]),
    "queue": APIRouter(tags=["queue"]),
    "library": APIRouter(tags=["library"]),
    "administration": storage_router,
    "live_updates": APIRouter(tags=["live-updates"]),
}

_PREFIXES = {
    "queue": (
        "/api/queue", "/api/v1/queue", "/api/download", "/api/v1/download",
        "/api/taste", "/api/v1/taste",
    ),
    "live_updates": ("/ws", "/api/v1/ws"),
    "library": (
        "/api/cover", "/api/v1/cover", "/api/movie-subscriptions",
        "/api/v1/movie-subscriptions", "/api/watchlist", "/api/v1/watchlist",
    ),
    "discovery": (
        "/api/genres", "/api/v1/genres", "/api/movies", "/api/v1/movies",
        "/api/movie", "/api/v1/movie", "/api/series", "/api/v1/series",
        "/api/series-calendar", "/api/v1/series-calendar",
        "/api/anime", "/api/v1/anime", "/api/home", "/api/v1/home",
        "/api/aniworld", "/api/v1/aniworld",
        "/api/daily-top", "/api/v1/daily-top", "/api/search", "/api/v1/search",
        "/api/tmdb/movie", "/api/v1/tmdb/movie", "/api/tmdb/movies",
        "/api/v1/tmdb/movies", "/api/tmdb/series", "/api/v1/tmdb/series",
        "/api/jellyfin/matches", "/api/v1/jellyfin/matches",
    ),
}


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _domain(path: str) -> str | None:
    for name, prefixes in _PREFIXES.items():
        if any(_matches(path, prefix) for prefix in prefixes):
            return name
    return "administration" if path.startswith("/api/") else None


def register_domain_router(name: str, router: APIRouter) -> None:
    """Replace a transitional owner while preserving supplemental domain routes."""
    if name not in DOMAIN_ROUTERS:
        raise KeyError(f"Unknown API domain: {name}")
    existing = DOMAIN_ROUTERS[name]
    if existing is not router:
        for route in existing.routes:
            if route not in router.routes:
                router.routes.append(route)
    DOMAIN_ROUTERS[name] = router


def install_domain_routers(app: FastAPI) -> dict[str, int]:
    """Move directly registered API routes into domain routers once."""
    counts = {name: 0 for name in DOMAIN_ROUTERS}
    for route in tuple(app.router.routes):
        path = getattr(route, "path", "")
        domain = _domain(path)
        if domain is None:
            continue
        app.router.routes.remove(route)
        if route not in DOMAIN_ROUTERS[domain].routes:
            DOMAIN_ROUTERS[domain].routes.append(route)
        counts[domain] += 1
    # Keep the same route objects visible on ``app.routes`` for compatibility
    # with diagnostics and tests that enumerate the legacy application, while
    # the domain routers remain their explicit owners during source migration.
    for router in DOMAIN_ROUTERS.values():
        app.router.routes.extend(router.routes)
    return counts
