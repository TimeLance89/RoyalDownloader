# v1.2.0 release delta audit

Audit date: 2026-09-27, before modifying application/version files.

## Source of truth

- Latest published Stable: GitHub `v1.1.0`, published 2026-09-24 06:42:39 UTC.
- Actual tag target: `31d91417c4d45bb054140de60b7125ac6b7dbd78` (the existing tag
  is lightweight). Its application metadata is 1.0.0. The old tag is not moved.
- Audited Overnight: `e5c82699648b0c0d89f36709c9b25fa6abfd0fe8`.
- Main before promotion: `3b991cc40772aa8c09cd11ef9477a2a31da97070`.
- Main/Overnight: 0 main-only commits, 60 Overnight-only commits.
- Actual published-tag-to-Overnight diff: 322 files, 45,179 additions,
  20,559 deletions; these totals include audit JSON, tests and moved modules,
  and must not be interpreted as newly written application code.

## Evidence by area

| Area | Inspected implementation/evidence | Release classification |
|---|---|---|
| Frontend foundation | Removed `web/screens`/runtime scripts; new `web/js/core`, shared components, feature owners and lifecycle tests | New native-module architecture; preserved application/design |
| Dependency hardening | Domain composition modules, feature actions, layer/cycle tests and hardening audit/result | Registry removal and explicit dependency boundaries |
| Integration health | `api/integration_health.py`, module router, frontend health adapter | New additive health contract |
| Live persistence events | Actual `api/api_library_router.py` diff and persistence tests | Broadcast only committed movie-subscription/watchlist snapshots |
| Personal requests | `core/personal_requests.py` present in v1.1.0; no backend diff | Existing persistent user history, retained in migrated views |
| Household/personalization | No delta in `core/users.py`, `core/auth.py`, `features/taste_profile.py` | Existing v1.1.0 capability, not newly introduced |
| Carousel/mobile | Rail renderer, shared carousel geometry/input code, scrim fix, native gesture tests | Fewer clones, native interaction and stable anchors |
| Performance/visuals | Frozen baseline d3aada9, paired raw measurements, CSS comparison and populated visual fixtures | Measured DOM/blocking/layout reduction without content reduction |
| Upgrade archive | Compatibility i18n marker and `test_frontend_update_archive.py` | Preserve installed validator compatibility |
| Quality | Actual Quality workflow delta, new WebKit workflow and browser/performance harnesses | Required real-browser/visual/budget gates |
| Providers/storage/deployment | No production provider, updater, storage or deployment delta since v1.1.0 | Do not reannounce earlier provider/storage features or claim new backend migrations |

The old Unreleased bullets already exist unchanged in the published v1.1.0
tree. They are retained under the historical v1.1.0 heading, not misrepresented
as the v1.2.0 delta. Historical release documents remain untouched.

## Version and compatibility decision

Use 1.2.0: there is no intentional breaking public API, persistence, deployment
or update change. Both permanent branches enforce PRs, strict up-to-date `verify`
checks, resolved conversations and administrator enforcement; force pushes are
disabled. Promotion preserves history with a merge commit. Version/docs and an
additive v1.1.0 upgrade gate follow on a main-based release-preparation branch.

The official Publish release workflow runs Quality, validates main ancestry,
creates an annotated version tag, and publishes notes from
`docs/releases/v1.2.0.md`. CodeQL and the entire promotion/preparation pipelines
must pass before merging. Main release commits are then merged back to Overnight
through its protected PR path; neither permanent branch is force-pushed.
