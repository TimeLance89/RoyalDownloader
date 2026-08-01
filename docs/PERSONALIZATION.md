# Private personalization

Royal Downloader maintains one persistent taste profile for the single user of
an installation. The profile is stored locally beside the other application
state and is shared by the web UI, mobile API, Telegram, Seerr, subscriptions,
the download queue, and Jellyfin.

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

`taste_profile.json` in the persistent application data directory is the source
of truth. The browser keeps an optimistic cache so clicks feel immediate. On
startup it refreshes from the server. An existing `royal-discovery-profile-v1`
browser profile is imported exactly once, after which the server profile wins.

All taste endpoints have browser and versioned mobile aliases:

```text
GET    /api[/v1]/taste/profile
POST   /api[/v1]/taste/events
POST   /api[/v1]/taste/feedback
POST   /api[/v1]/taste/import
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
- Settings show the strongest learned genres and provide a full reset button.
- Movie and series details provide “More like this” and “Not for me”; pressing
  the active choice again clears it.

Back up the persistent `data` directory if the profile should survive a fresh
installation. Removing or resetting the profile is immediate and does not
delete media, subscriptions, or queue state.
