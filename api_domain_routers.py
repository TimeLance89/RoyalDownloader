"""Incremental ownership boundary for legacy API handlers.

Handlers are still moved out of the composition root one domain at a time,
but every route is already owned by an explicit FastAPI router. This keeps the
public contract unchanged and makes later source extraction mechanical.
"""

from fastapi import APIRouter, FastAPI


DOMAIN_ROUTERS = {
    "auth_setup": APIRouter(tags=["auth-setup"]),
    "discovery": APIRouter(tags=["discovery"]),
    "queue": APIRouter(tags=["queue"]),
    "jellyfin": APIRouter(tags=["jellyfin"]),
    "integrations": APIRouter(tags=["integrations"]),
    "administration": APIRouter(tags=["administration"]),
}

_PREFIXES = {
    "auth_setup": (
        "/api/auth", "/api/v1/auth", "/api/setup", "/api/v1/setup",
    ),
    "queue": (
        "/api/queue", "/api/v1/queue", "/api/download", "/api/v1/download",
        "/ws", "/api/v1/ws",
    ),
    "jellyfin": ("/api/jellyfin", "/api/v1/jellyfin"),
    "integrations": (
        "/api/telegram", "/api/v1/telegram", "/api/seerr", "/api/v1/seerr",
        "/api/tmdb/config", "/api/v1/tmdb/config",
    ),
    "discovery": (
        "/api/genres", "/api/v1/genres", "/api/movies", "/api/v1/movies",
        "/api/movie", "/api/v1/movie", "/api/series", "/api/v1/series",
        "/api/anime", "/api/v1/anime", "/api/home", "/api/v1/home",
        "/api/search", "/api/v1/search", "/api/tmdb/movie",
        "/api/tmdb/movies", "/api/tmdb/series",
    ),
}


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _domain(path: str) -> str | None:
    for name, prefixes in _PREFIXES.items():
        if any(_matches(path, prefix) for prefix in prefixes):
            return name
    return "administration" if path.startswith("/api/") else None


def install_domain_routers(app: FastAPI) -> dict[str, int]:
    """Move directly registered API routes into domain routers once."""
    counts = {name: 0 for name in DOMAIN_ROUTERS}
    for route in tuple(app.router.routes):
        path = getattr(route, "path", "")
        domain = _domain(path)
        if domain is None:
            continue
        app.router.routes.remove(route)
        DOMAIN_ROUTERS[domain].routes.append(route)
        counts[domain] += 1
    # Keep the same route objects visible on ``app.routes`` for compatibility
    # with diagnostics and tests that enumerate the legacy application, while
    # the domain routers remain their explicit owners during source migration.
    for router in DOMAIN_ROUTERS.values():
        app.router.routes.extend(router.routes)
    return counts
