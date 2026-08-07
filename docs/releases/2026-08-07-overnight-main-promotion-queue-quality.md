# Overnight → Main Promotion — 2026-08-07 (Queue, Identity, and Subscription Quality)

This document summarizes the tested Overnight changes prepared for promotion to the Stable `main` branch after the previous Stable promotion in PR #87 (`2e82f7d0fe93bd921147286a71b74b9bb6bac80e`).

## Highlights

This promotion focuses on three major areas: keeping Royal responsive with very large download backlogs, making movie identity and provider fallback decisions more reliable, and replacing advertised movie-subscription quality with measured technical quality. It also introduces a more polished Download Dock and Subscription Center while preserving existing API, WebSocket, queue, persistence, updater, and provider contracts.

## Royal Download Dock

- The persistent bottom download area has been redesigned as the Royal Download Dock without changing queue or backend contracts.
- Active, completed, cancelled, and failed downloads have clearer visual states and hierarchy.
- Queue entries are presented as compact media-center cards with position, title, language, provider/hoster route, metrics, progress, status, and actions.
- The expanded queue is presented as one coherent slide-up surface instead of a disconnected technical panel.
- Recent activity, queue history, and provider-health states use a cleaner presentation.
- The mobile queue is now a rounded, safe-area-aware bottom sheet.
- Existing queue element IDs, JavaScript hooks, REST fields, and WebSocket payloads remain unchanged.

## Royal Subscription Center

- The former subscription inbox has been redesigned as the Royal Subscription Center without changing watchlist or subscription contracts.
- New episodes and real problems have separate visual indicators instead of sharing one undifferentiated badge.
- The center exposes live summary metrics for new episodes, problems, and total subscriptions.
- Series backdrop artwork is used where available, with a deterministic fallback when artwork is missing.
- Notifications are separated into clear new-content and attention-required sections.
- Status pills distinguish queued items, blocked sources, failed checks, cleanup problems, and newly available episodes.
- Refresh feedback and the all-up-to-date empty state now explain the current monitoring state more clearly.
- Desktop and mobile layouts were polished without changing existing watchlist actions or backend behavior.

## Canonical media identity and Jellyfin matching

- Royal now uses a central media-identity policy across TMDB lookup, Jellyfin matching, local duplicate detection, and final media naming.
- Conservative title aliases handle localized provider titles, separator variants, and numbered franchise titles more reliably.
- Stable TMDB IDs remain authoritative when Jellyfin already contains a correctly identified copy.
- Historical Royal filenames with legacy `~<8-hex>` suffixes are recognized as the same media identity so old files do not trigger duplicate downloads.
- Local duplicate detection can find legacy Royal movie files before a new download is allowed.
- New filenames no longer receive hashes merely because punctuation or filesystem-forbidden characters were normalized.
- Canonical TMDB movie title and year are preferred for new movie filenames when identity resolution succeeds.
- Deterministic suffixes remain limited to real byte-length truncation or actual filesystem collisions.
- Existing library files are not automatically renamed or deleted.

## Exhaustive movie-provider fallback

- Cached movie fallback data is now treated only as a fast seed and never as proof that provider discovery is complete.
- After the primary source and cached fallbacks fail, Royal performs one live search across every still-untried active movie provider before declaring terminal failure.
- Provider matching uses canonical and original TMDB titles, Royal media-identity aliases, and release year.
- The authoritative fallback pass no longer stops at an arbitrary small provider cap.
- The selected queue language lane remains authoritative during fallback and recovery.
- A movie reaches terminal failure only after all usable matching sources discovered across the active provider set have been exhausted.
- Series/episode fallback semantics remain unchanged.

## Large queue and backlog performance

- The queue scheduler now has O(1)/host-group fast paths that avoid repeatedly scanning large pending lists when no compatible preparation or download slot can start.
- Pending preparation/download counts and host-group state are maintained incrementally as jobs are added, removed, cancelled, retried, or started.
- Queue persistence is deduplicated by restart-relevant structure so transient progress and active-state updates no longer rewrite the complete persistent queue unnecessarily.
- Durable transitions such as add, cancel, retry, claims, and terminal state changes remain fail-closed and synchronously persisted.
- Direct-download progress events are rate-limited to a bounded frequency per job/attempt while errors, diagnostics, and final 100% updates remain immediate.
- Persistent progress snapshots and full `queue_update` broadcasts are coalesced to prevent large queues from amplifying disk I/O and WebSocket work.
- Logical `job_id` / `attempt_id` semantics, retry protection, stale-callback protection, restart recovery, and existing REST/WebSocket schemas remain unchanged.

## Movie-subscription quality truth

- Jellyfin's observed video height is now authoritative for the currently installed subscribed movie instead of stale optimistic provider metadata.
- Stored quality can move downward again when Jellyfin proves the existing file is lower quality, allowing a real future upgrade to be detected.
- Successfully downloaded subscription upgrades are measured with `ffprobe` and the measured result is stored instead of trusting an advertised provider label.
- The stored subscription state records whether quality came from Jellyfin or `ffprobe`.
- Provider/hoster quality parsing was hardened so explicit UHD/2160p/1080p markers take precedence over generic labels such as `HD`.

## Repeated false-upgrade protection

- Subscription candidates that advertise a higher tier but repeatedly deliver no measured improvement are remembered with a stable, privacy-preserving fingerprint.
- Provider/hoster URLs are not persisted directly in this rejected-candidate state; candidate identity is stored as a SHA-256-derived fingerprint.
- A candidate is rejected only after a completed download is independently measured and confirmed not to improve the existing file.
- Network errors or failed measurements do not blacklist a source.
- Rotating or changed hoster sources can still be evaluated as new candidates.
- If the local library quality later falls below the real quality previously delivered by a rejected source, the source can become eligible again.
- Rejected-candidate history is bounded per movie subscription.

## Real stream-quality inventory across providers

- Movie subscriptions no longer choose upgrades primarily from provider or hoster quality labels.
- Royal resolves all reachable hosters from all provider sources for the subscribed movie and measures the actual stream before downloading it.
- Measured profiles can include resolution, video codec, bitrate, bit depth, SDR/HDR10/HLG/Dolby Vision indicators, frame rate, audio codec, channels, bitrate, and sample rate where available.
- Resolution remains the primary quality tier, while real HDR, 10-bit, codec, and audio improvements can distinguish candidates within the same resolution when the local profile is sufficiently known.
- The configured subscription target (`720p`, `1080p`, `2160p`, or `best`) is applied to measured resolution rather than provider advertising.
- Successful stream probes are cached for two hours and failed probes for a shorter period, with bounded per-subscription cache size.
- Stable candidate identity ignores rotating URL query strings and fragments so signed-token changes do not look like entirely new releases.
- Recently resolved streams can be reused for the subsequent download to avoid repeating expensive browser/embed resolution unnecessarily.

## Safe pre-commit upgrade guard

- A subscription upgrade remains in its isolated staging directory after download.
- The complete downloaded staging file is independently measured again with `ffprobe` before publication.
- The existing library file is replaced only when the fully downloaded file is reliably proven to be better than the pre-download baseline.
- Equal, lower-quality, or unmeasurable staging files are discarded before commit.
- When another already measured candidate remains available, Royal can continue with the next candidate instead of publishing a non-upgrade.
- A technically working hoster is not penalized in hoster health merely because its delivered file failed the upgrade threshold.
- The actual collision-safe committed path is propagated to queue history and subscription completion logic so post-download quality state follows the file that was really published.

## Manifest-first bounded quality probing

- HLS master manifests are inspected first using a bounded read of at most 256 KiB.
- Clearly inferior HLS variants can be rejected without launching a deeper `ffprobe` stream analysis.
- Only plausible upgrade candidates proceed to the expensive deep probe.
- Deep probes run with bounded parallelism of at most four workers, preventing serial latency without creating uncontrolled probe fan-out.
- For a configured target such as 1080p, Royal selects the best HLS variant within that target instead of accidentally probing a higher 2160p variant from the same master.
- Manifest metadata can supplement missing information, but measured `ffprobe` data remains authoritative whenever it is available.
- Subscription probe/skip counters provide diagnostics for the optimized inventory path.
- Subscription downloads use the measured target resolution so a verified 2160p candidate is not accidentally downloaded with the previous global 1080p preference.
- Normal non-subscription downloads keep their existing behavior.

## Compatibility

- No existing Legacy or `/api/v1` response field is removed or renamed by this promotion.
- Existing WebSocket event schemas remain compatible.
- Existing logical queue identity, retry, cancel, recovery, and persistence semantics remain compatible.
- Existing Stable/Overnight updater behavior remains unchanged.
- No migration or automatic rename of existing media files is required.
- Provider priority remains authoritative where provider order is relevant.
- The subscription manifest layer is an optimization only; it does not replace the measured-quality or final pre-commit safety checks.
- No force-push, protected-branch bypass, or branch-protection change is required for this promotion.

## Validation and regression coverage

The promoted Overnight work adds or expands regression coverage for:

- Download Dock and Subscription Center presentation contracts;
- canonical TMDB/Jellyfin/local-file identity and legacy Royal filename recognition;
- exhaustive provider fallback and language-lane preservation;
- large pending queues, per-host limits, persistence deduplication, and progress/event coalescing;
- authoritative Jellyfin and `ffprobe` quality synchronization;
- persistent rejected-candidate protection against repeated false upgrades;
- cross-provider real stream-quality ranking and stable candidate identity;
- staging-file pre-commit rejection for equal, worse, or unmeasurable downloads;
- HDR/codec/audio profile construction from `ffprobe` and Jellyfin media sources;
- HLS manifest parsing, target-variant selection, manifest/deep-probe profile merging, and bounded four-worker parallelism;
- measured subscription download target selection.

The final promotion must pass the repository `verify` workflow before merge to protected `main`, including Python compilation, JavaScript checks, frontend contract tests, correctness/security baselines, dependency audit, Docker Compose validation, the full test/coverage suite, container build, and fresh/persistent startup and restart smoke tests.
