# Provider Sentinel: inventory and migration

## Existing ownership

`providers/catalog.py` defines 15 providers. Twelve expose movie catalogs,
nine expose series catalogs, and AniWorld/MKissa expose anime browsing. Some
movie adapters contain empty series methods: declarations must follow catalog
media types rather than method presence. Adapters use curl_cffi sessions,
requests sessions, or SessionManager (Filmpalast/SerienStream). MKissa has a
specific GraphQL/token protocol; that protocol is not automatically repairable.

`media/provider_health.py` owns the persisted healthy/cooldown/probing/blocked
runtime contract. Download routing currently consults it primarily for
SerienStream. `application_services/movie_catalog.py` owns configured priority,
language and enablement; series routing lives in `series_catalog.py`. Sentinel
must retain configured provider lists and filter only runtime eligibility.
HosterIntel owns hoster outcomes separately; finding a hoster link is not proof
that the hoster can deliver a stream.

Background services start after setup in `server.start_background_services` and
stop with the FastAPI lifespan. Settings providers are a native ES-module
feature, composed by `composition/settings.js`. API security already separates
administrator operations from household/media APIs.

## Integration order

1. Bounded atomic diagnostics/repair store, capability contracts and tests.
2. Adapter session instrumentation: request budgets, HTTP-only probe mode,
   structural summaries, validated domain overrides, real-request observations.
3. Existing-adapter probes with independent current catalog canaries, separate
   failure classifications and conservative ProviderHealth isolation/recovery.
4. Deterministic repair candidates and shadow validation. Only constrained
   extraction parameters are executable; no generated source or token repair.
5. Staggered scheduler and administrator API. Runtime state does not change
   provider enablement. Disabled sources are never scheduled automatically.
6. Settings source monitor with lifecycle cancellation, history, repair evidence,
   explicit rollback confirmation and configuration.
7. Offline fixtures, mutation tests, browser/security/full regression gates.

## Repair boundaries

An unfamiliar domain is not trusted merely because its TLS certificate is valid.
Domain recovery requires an observed HTTPS redirect from a catalogued origin,
unchanged identities on multiple previously successful independent detail pages,
and successful catalog/metadata/hoster shadow validation. Unproven domains remain
candidates. Cross-provider, local-network and credential-bearing targets fail
closed. Existing protected-provider browser verification remains user-driven;
Sentinel never invokes browser recovery or CAPTCHA handling.

Selector recovery uses semantic evidence, unique matching and several known
media identities, not a guessed percentage. Unsupported fields/protocols remain
`needs_attention`. A repair is versioned with validation evidence and its prior
profile; subsequent independent real failures roll it back. No raw HTTP headers,
cookies, pages or credential-bearing URLs enter the diagnostics store.

Normal CI uses deterministic provider fixtures exclusively. Live probes run
only inside an initialized installation. Monitor response/hoster measurements
must say exactly what was tested; extracted links never count as live downloads.
