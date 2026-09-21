# Private personalization

Royal Downloader maintains one isolated taste profile for every household
user. The original `taste_profile.json` remains assigned to the migrated first
administrator. Additional profiles live below `taste_profiles/` under a
SHA-256-derived filename; a new user therefore starts with no inherited
signals. Catalog, library, queue and downloads remain shared household state.
The instance-wide Jellyfin adapter remains attached to that legacy
administrator; its playback history never seeds a newly created account.

## Cold-start onboarding

New users are marked `taste_onboarding_required` until they choose at least
five titles from a diverse 32-title catalog sample. The browser balances media
types, genres and release decades instead of showing a random cluster of
similar titles. “Andere Titel anzeigen” produces another deterministic,
diverse sample.

Each choice is persisted as an `onboarding_like` interaction with a moderate
weight of `2.5`. This creates useful genre, people, tag, decade and media-type
dimensions without outweighing later downloads, explicit likes or completed
plays. Until completion, Royal Intelligence returns no personalized result.

## What Royal learns from

Signals have deliberately different strengths. An accidental open should not
outweigh a deliberate download or an explicit rejection.

| Signal | Base weight | Source examples |
|---|---:|---|
| Search | +0.15 | Web or mobile search |
| Open details | +0.8 | Movie, series, or anime details |
| Remove | -1 | Removing a saved choice |
| Add series to watchlist | +3.5 | Series subscription |
| Subscribe to movie quality | +4 | Movie subscription |
| Download | +5 | Web, API, Telegram, Seerr, or automation |
| Dismiss | -5 | Explicit hide action |
| More like this | +6 | Explicit feedback |
| Watched to completion | -2 to +14 | Jellyfin, adjusted by favorite/rating |
| Favorite | +8 | Explicit feedback or Jellyfin |
| Not for me | -10 | Explicit feedback |
| Rating | -7 to +7 | Rating from 0 to 10 around neutral 5 |

Repeated opens are deduplicated for ten minutes. Downloads, subscriptions, and
watchlist actions are deduplicated for 24 hours. Episode downloads use their
series as the item key, so a large season does not overwhelm other preferences.

## Taste dimensions

Provider, TMDB, and Jellyfin metadata are normalized into these axes:

- genre and media type (movie, series, anime);
- tags and keywords;
- studios, directors, and actors;
- language;
- release decade;
- short, medium, or long runtime.

Each axis has a conservative factor. Genres and directors influence ranking
more than a studio, language, decade, or runtime bucket. Candidate ranking adds
matching positive and negative values, a small community-rating component, and
a stable daily exploration value. Explicitly dismissed items are removed from
home recommendations while remaining discoverable through direct search.

Signals decay with a 180-day half-life. Explicit feedback decays twice as
slowly. Jellyfin data is stored as a replaceable snapshot, not appended on each
daily recommendation run, so it cannot grow or double-count indefinitely.

## Cross-device synchronization and migration

The per-user server file is the source of truth. The browser cache is namespaced
with the authenticated user id. Only `admin-legacy` may import the historic
unnamespaced `royal-discovery-profile-v1` cache; another account never reads it.

All taste endpoints have browser and versioned mobile aliases:

```text
GET    /api[/v1]/taste/profile
POST   /api[/v1]/taste/events
POST   /api[/v1]/taste/feedback
POST   /api[/v1]/taste/import
POST   /api[/v1]/taste/onboarding
POST   /api[/v1]/taste/reset
DELETE /api[/v1]/taste/profile
```

See [ANDROID_API.md](ANDROID_API.md) for request and response examples.

## Privacy and user control

- Data never leaves the self-hosted Royal Downloader instance.
- The file is written atomically and receives owner-only permissions where the
  operating system supports them.
- At most 2,000 interaction events and 1,000 Jellyfin items are retained.
- API profile responses do not expose raw search queries, titles, or the full
  event history.
- All routes use the existing Royal Downloader authentication middleware.
- Settings show the strongest learned genres and can restart taste onboarding.
- Movie and series details provide “More like this” and “Not for me”; pressing
  the active choice again clears it.

Royal Intelligence fingerprints and background jobs include the user id,
profile summary, candidates, model and Reflex version. Download, watchlist and
subscription signals are written only to the requesting user's profile; shared
automation without a requesting user does not become household taste.

Back up the persistent `data` directory if profiles should survive a fresh
installation. Resetting a profile restarts onboarding and does not delete
media, subscriptions, or queue state.
