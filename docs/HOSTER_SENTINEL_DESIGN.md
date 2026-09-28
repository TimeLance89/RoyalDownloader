# Source Sentinel: Hoster audit and migration

Baseline: overnight `5847ed739a2ad7db165aab31129875c8f95aa8d3` (PR #376).

## Existing ownership

`ProviderMonitor` owns the two-slot executor, staggered scheduler, settings,
diagnostic store, notification callback and shutdown generation. `ProviderProbe`
checks all 15 adapters under bounded transport contexts. `ProviderRepair` discovers
allowlisted domain/selector/JSON candidates and validates known independent pages
before activation. The atomic store retains 120 events / 30 days and 20 repairs.
Admin APIs use existing auth and write middleware. The settings monitor owns one
lifecycle scope and polls only while visible. These owners are extended, not copied.

## Real resolution inventory

`source_resolution._extract_from_movie` selects VOE/Moflix/Veev/KinoGer via
`extract_stream_url`, Doodstream, Vidara, Vidsonic and FireStream via dedicated
extractors, Filmfrei24 via direct HLS, and other embeds via yt-dlp. Provider adapters
also emit StreamRuby, Streamtape, Vidoza, Vidmoly, Filemoon, Flyfile, UpCloud,
Vidsrc, Closeload and Rapidrame. Provider redirects are resolved before entering
the hoster stage. HosterIntel owns static/learned ranking and download circuits.
Unknown runtime families must remain observable without pretending that a parser
or browser-only mechanism is deterministically repairable.

## Migration order

1. Extend the same store with a hoster namespace and reuse the repair journal.
2. Declare resolver contracts used by inventory/probes/runtime attribution.
3. Add bounded passive aggregates and ephemeral independent canaries. Persist only
   identity hashes, domain, provider and fixed technical codes, never embed/media
   URLs, tokens, titles, users, response bodies or exception text.
4. Add staged probes through existing extractors, sharing the scheduler/executor.
   HTTP responses and redirects are bounded and public-network guarded. No media
   download or unbounded browser startup. Unavailable browser-only proof is
   inconclusive, never evidence that the hoster is broken.
5. Add deterministic JSON/HTML profile recovery, current/candidate validation,
   conservative activation and independent runtime rollback.
6. Feed health into ranking as a fail-open additive factor; keep provider health
   separate. Extend the existing monitor/API, fixtures and operational documentation.

## Boundaries

Single dead embeds cannot establish family failure. Challenge, login, rate limit,
DRM and new token/encryption protocols require human attention. A new redirect
domain alone cannot establish hoster identity. Domain candidates need independent
known-canary resolver identity evidence; ambiguous origins cannot auto-activate.
Canaries are memory-only and expire; after restart fresh runtime/provider evidence
is needed. Monitoring failures cannot stop normal resolution.
