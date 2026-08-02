# Incremental architecture decision

Royal Downloader keeps its public HTTP and WebSocket contracts stable while
the original monolith is split at explicit seams. New code must follow this
dependency direction:

`routers -> services -> providers/persistence -> filesystem or network`

Routers validate and translate HTTP only. Services own runtime state and
locking. Provider and persistence modules do blocking I/O and never import a
router. `server.py` remains the composition root during migration.

## Target modules

| Area | Router | Service ownership |
|---|---|---|
| Auth and setup | `api_auth_router.py` | sessions, first-run transaction |
| Discovery | `api_discovery_router.py` | provider catalogs and metadata |
| Queue | `api_queue_router.py` | claims, scheduler, download lifecycle |
| Jellyfin | `api_jellyfin_router.py` | library snapshots and matching |
| Integrations | `api_integrations_router.py` | Telegram, Seerr, TMDB |
| Administration | `api_system_router.py` | health, diagnostics, updates |
| HTTP security | `api_security.py` | public routes, origin checks, response headers |

The administration router and HTTP security boundary are the first extracted
production modules. Authentication storage remains in the composition root and
is injected into `api_security.py`; the security module therefore owns policy
without depending on server globals. Frontend API transport, mutable store, and
design tokens now live in `api.js`, `store.js`, and `style-tokens.css`;
subsequent screen modules may depend on those files but not on one another.

## Lock ownership and order

When more than one lock is required, acquire only in this order and release in
reverse: `queue_lifecycle -> queue_claim -> download_state -> watchlist`.
Provider locks are acquired outside that chain. Persistence performs its
atomic write entirely in a worker thread; an async handler never awaits while
holding a threading lock. Cache locks are private to each cache and callbacks
used for pin decisions must never acquire cache locks.

Each extraction must retain both legacy and `/api/v1` routes and pass the full
regression suite before the next domain is moved.
