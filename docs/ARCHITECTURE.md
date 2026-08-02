# Incremental architecture decision

Royal Downloader keeps its public HTTP and WebSocket contracts stable while
the original monolith is split at explicit seams. New code must follow this
dependency direction:

`routers -> services -> providers/persistence -> filesystem or network`

Routers validate and translate HTTP only. Services own runtime state and
locking. Provider and persistence modules do blocking I/O and never import a
router. `server.py` remains the composition root during migration.

`app_state.py` is the single owner of mutable process state and its associated
locks. The composition root creates one `AppState`; routers and services receive
that instance and must not create parallel state containers.
Bounded per-client event delivery is owned by `websocket_manager.py`; producers
publish structural events without waiting on a slow browser connection.

## Target modules

| Area | Router | Service ownership |
|---|---|---|
| Auth and setup | `api_auth_router.py`, `api_setup_router.py` | sessions, first-run transaction |
| Discovery | `api_discovery_router.py` | provider catalogs and metadata |
| Queue | `api_queue_router.py` | claims, scheduler, download lifecycle |
| Library | `api_library_router.py` | subscriptions, watchlist, cleanup |
| Jellyfin settings | `api_administration_router.py` | library snapshots and matching |
| Integration settings | `api_administration_router.py` | Telegram, Seerr, TMDB |
| Administration | `api_administration_router.py`, `api_system_router.py` | config, health, diagnostics, updates |
| HTTP security | `api_security.py` | public routes, origin checks, response headers |

The administration, authentication, and setup routers plus the HTTP security
boundary are the first extracted production modules. Authentication storage
and the atomic setup transaction remain in the composition root and are
injected into their HTTP modules. Persistent media-path validation lives in
`media_paths.py`. These modules therefore own their policy without importing
server globals. Frontend API transport, mutable store, and design tokens now
live in `api.js`, `store.js`, and `style-tokens.css`. Shared navigation, live
updates, and queue UI live in `core.js`; individual feature areas live below
`web/screens/`, and `app.js` only performs final event binding and startup.
Screen modules may depend on core and earlier domain modules but do not perform
startup themselves.

The discovery router is physically extracted and receives a migration facade
from the composition root. Calls are resolved dynamically to retain provider
test seams. New discovery services should be injected explicitly; they must not
add reverse imports from the router into `server.py`.
The same transitional facade pattern is used by `api_queue_router.py`, whose
service helpers remain re-exported by the composition root for Telegram, Seerr,
watchlist, and compatibility tests.
`api_library_router.py` owns the cover proxy, movie subscriptions, watchlist,
and watched-media cleanup as one persistence and queue-coordination boundary.
`api_administration_router.py` owns all runtime configuration mutations and
their validation, including setup completion and integration settings.

CSS cascade order is declared only in `style.css`. Design tokens load first,
followed by the historical `legacy` layer split across focused files, followed
by ordered feature overrides in `web/styles/`. Moving a rule between files must
preserve that phase unless the cascade change is intentional and tested.

## Lock ownership and order

When more than one lock is required, acquire only in this order and release in
reverse: `queue_lifecycle -> queue_claim -> download_state -> watchlist`.
Provider locks are acquired outside that chain. Persistence performs its
atomic write entirely in a worker thread; an async handler never awaits while
holding a threading lock. Cache locks are private to each cache and callbacks
used for pin decisions must never acquire cache locks.

Each extraction must retain both legacy and `/api/v1` routes and pass the full
regression suite before the next domain is moved.
