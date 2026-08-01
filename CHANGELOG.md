# Changelog

This file records user-visible Royal Downloader changes. The project currently
ships continuously from `main`; entries are therefore grouped by date instead
of a separately maintained release version.

## 2026-08-01

### Reliability and security

- Hardened the public translation endpoint with bounded request payloads,
  work-unit rate limiting, a fixed client-tracking cap, and one global outbound
  concurrency budget.
- Made generated media names portable across NAS, Linux, and Windows filesystems
  and prevented finalization from overwriting an existing media file.
- Clarified that the Android client source is maintained separately and added a
  CI-backed check for broken relative documentation links.

### Providers and routing

- Added **Huhu** as a German provider for movies and series.
- Set the default German movie order to start with **Filmpalast**, followed by
  **Huhu**. **FilmFrei24** now comes last in the movie fallback chain.
- Kept **SerienStream** as the primary German series source. Huhu is available
  as the first fallback, followed by Moflix, MegaKino, and Filmpalast.
- Added persistent SerienStream health states with increasing cooldowns,
  restart-safe waiting episodes, a single controlled recovery probe, and a
  manual one-shot retry. CAPTCHA and rate-limit responses are respected; no
  automated CAPTCHA solving or protection bypass is used.
- Improved exact cross-provider series, season, and episode matching and cached
  fallback discovery so unavailable providers do not stall every queued item.

### Queue and downloads

- Movie jobs are no longer held behind a paused series backlog and can start as
  soon as a transfer slot is available.
- Provider searches and episode preparation no longer occupy active download
  slots unnecessarily. Already resolved transfers continue in parallel.
- Queue entries now distinguish provider waiting, preparation, and active file
  transfer more clearly in the download plan and progress display.

### Jellyfin and subscriptions

- Series details now query only the matched Jellyfin series instead of waiting
  for the complete episode library index.
- Added provider-independent subscription matching using stable TMDB IDs,
  titles, and aliases. A series opened through another provider therefore keeps
  its existing subscription state.
- Added short-lived targeted Jellyfin caches with immediate invalidation after
  library updates, configuration changes, and Jellyfin deletions.
- A failed live check preserves the last known result as explicitly stale
  instead of presenting it as current or silently allowing duplicate downloads.
- Added `/api/series/jellyfin-status` and its authenticated mobile v1 alias for
  fast native and web detail updates.

### Personalization

- Added one private, cross-device taste profile shared by the web interface and
  native clients.
- The profile learns from discovery, detail views, downloads, subscriptions,
  explicit positive/negative feedback, and Jellyfin playback history.
- Added profile inspection and reset controls plus API endpoints for native
  clients. Personalization data remains stored on the self-hosted instance.

### Validation

- Added regression coverage for provider-independent subscriptions, ambiguous
  title protection, targeted Jellyfin queries, caching, and API aliases.
- The completed 2026-08-01 state passed the full automated suite with **75
  tests** plus Python and JavaScript syntax checks.
