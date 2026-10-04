# Provider language model

## Audit before implementation

Base: Overnight `60c42ec55ff9f73400032e2fc362b2bbe731c543`.

- `providers/catalog.py` exposes one primary `content_language`. Setup/admin,
  `movie_catalog.provider_priority`, server Sentinel selection and settings/nav
  compare that single language with the installation language selection.
- `content_language_policy.py`, movie/series metadata and source resolution use
  explicit title/source languages first, then a legacy provider default. These
  defaults must not become an assertion that every title has every supported language.
- Sentinel service health currently builds one `(media, language)` path per
  provider. Diagnostics do not receive the selected installation languages.
  Provider health and hoster health are provider-wide, not language evidence.
- AniWorld uses `dub=de`, `sub=de`, `eng=en`; its detail API already filters real
  title tracks by the configured languages. Episodes preserve these tracks.
- MKissa browses `dub` and `sub` (English); it additionally supports an explicit
  `raw` (Japanese) episode track. Its episode object currently incorrectly assigns
  `content_language=en` even to raw. Japanisch is not a new global provider-selection
  language in this change; raw remains an explicit additional track.
- The existing runtime adapter observation has the concrete episode result and
  its language. Resolution observation also knows the chosen stream language.
  Small bounded timestamps in the existing diagnostics store can retain this
  evidence without saving titles, episode URLs, credentials or user data.
- Queue jobs persist a single chosen `content_language`; old values/configuration
  must not be rewritten into provider capability lists.

## Migration order

1. Add supported languages and declarative track mappings to the catalog;
   preserve the primary-language getter and old API fields.
2. Use language-set intersection for setup, priorities, monitoring and settings.
3. Feed selected languages and bounded concrete language evidence into existing
   service-health paths; keep provider-wide circuits and repair rules intact.
4. Preserve actual title/episode track metadata; correct raw to Japanese without
   expanding the global DE/EN selector.
5. Show per-language availability only where a media area is affected.
6. Add catalog/setup/routing/evidence/persistence/browser regressions and run CI.

## Contracts

`content_language` / `provider_content_language()` remain the primary/legacy
default. `content_languages` / `provider_content_languages()` describe possible
provider capabilities, never a title's actual tracks. Concrete title translation
counts and episode tracks determine availability. Two German dub/sub tracks still
count as one German provider path.

AniWorld declares DE/EN; `dub` and `sub` both map to DE, `eng` to EN.
MKissa declares EN for global selection; `dub`/`sub` map to EN and `raw` to JA.
JA can be normalized and stored on a concrete raw job but is not advertised in
the global selector. An auxiliary track is permitted only for the explicitly
selected episode slug while its provider matches an enabled global language;
it does not exempt ordinary DE/EN tracks from the language policy.

The provider catalog API adds `primary_language`, `content_languages` and
`language_labels`, retaining `content_language` and `language_label`. Aggregate
movie/series source metadata uses `provider_content_languages` to distinguish
capabilities from a concrete title's `content_languages`. Anime title payloads
derive actual languages from nonzero translation counts; episode payloads carry
the selected track language. Disabling EN removes AniWorld's `eng` option without
removing AniWorld's DE tracks, and vice versa. Removing one global language in
settings retains a multi-language provider if it still matches another selection.

## Service health and evidence

Existing `(media_type, language)` paths are reused and intersected with the
installation selection. Provider IDs are deduplicated per path; DE dub/sub do not
increase redundancy. Provider-wide health/circuits are unchanged. For a provider
with multiple capabilities, a healthy catalog alone confirms neither language.
The path needs fresh concrete episode/source evidence plus a usable associated
video service. A failed provider or all associated video services still takes
precedence. Missing/stale language evidence remains unconfirmed.

The existing Sentinel store retains at most one success timestamp per declared
media/language pair, with 24-hour freshness and at most one write per minute per
pair. Successful existing full-probe episode extraction, runtime episode
extraction with source links, and successful production media resolution refresh
that evidence. No additional network requests, browser probes, scheduler, repair
profile or identity store is introduced. A full probe still samples its existing
track; it does not claim to have tested all tracks listed in title metadata.

Known single-language providers retain their previous health semantics. A lost
MKissa route with a proven AniWorld EN alternative is reduced redundancy, not
functional loss; DE absence is never hidden by a working EN path. The compact
overview only expands languages when a media area's paths are affected.

## Persistence and compatibility

The installation language configuration and provider orders need no migration.
Existing queue jobs keep their single stored language across retry/restart; new
raw jobs store JA. These optional diagnostic timestamps do not alter queue,
session/account or repair formats. Provider/hoster classification, repair
confidence, shadow validation, penalties and rollback rules remain unchanged.

## Strict queue-language contract

A queue job's stored `content_language` is authoritative for the lifetime of
that logical job, including retries and provider/hoster fallbacks. Global
installation languages only define which lanes may be chosen when the job is
created; they do not widen an existing job later.

For multilingual providers, `content_language` is only the provider's primary
catalog language. Concrete hoster `language` / `audio_language` metadata is
required to satisfy a pinned queue lane. Unknown concrete language fails closed
instead of falling back to the provider default.

Series detail uses exact episode checks for multilingual providers before an
episode is committed to the queue. Coarse season-list flags are presentation
hints only. Episodes already local or present in Jellyfin are never relabelled
from remote provider flags.

If HLS/DASH exposes a concrete audio-language tag, yt-dlp is constrained to that
language without a generic foreign-language fallback. A provider/hoster language
label is not fabricated into a manifest language tag, so muxed streams that are
explicitly labelled by the provider remain usable.

Known adapters that can expose more than one language must declare that
capability. This currently includes FilmPalast, Huhu, KinoGer, KinoKing,
SerienStream, AniWorld and the relevant English-provider families.

## Adding a multi-language provider

Declare supported `content_languages`, a primary `content_language` and concrete
`track_languages` in its catalog definition. Have its adapter expose real
translation counts/episode tracks and the chosen source language; never copy
provider capabilities into title availability. Add setup/intersection tests and
fixture-based concrete language evidence tests before advertising verified paths.
