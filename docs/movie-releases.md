# Movie releases

Releases provides a regional movie timeline using the **direct Streaming Availability API by Movie of the Night**. It does not use RapidAPI or a paid fallback.

## Setup

1. Create an account at https://developers.movieofthenight.com/ and select the **Free** plan without payment details.
2. Open **Settings → Media → Movie releases** and enter the API key.
3. Select the country and save. Open **Releases** to see the connection result and dates.

The direct Free plan currently includes 1,000 requests per month and access to all endpoints. Its quota is a hard limit without overage billing. Royal additionally persists a local limit of **900 requests per rolling 31 days**. Other applications using the same account consume the provider's shared quota.

Pricing reference, verified September 9, 2026: https://www.movieofthenight.com/about/api/pricing

## Coverage and accuracy

- Upcoming announcements cover up to 31 days. The source supports upcoming changes for Netflix, Disney+, Prime Video, Apple TV, Max and Mubi; actual coverage varies by country and title.
- Recent catalog additions can include other services. These are labelled **observed on the platform**, not confirmed premiere dates.
- Only subscription and free movie entries are included; rentals, purchases and episodes are excluded.
- Missing dates are displayed as unknown. Dates are never inferred from cinema releases or current streaming availability.
- Up to six pages per category are fetched per refresh. Queries are limited to supported subscription and free catalogs of common services in the selected country. Incomplete pagination or a category timeout is visibly labelled as partial coverage while successful results remain available.
- Refresh runs on demand at most daily. Connection tests may refresh after a five-minute cooldown. Network or quota failures retain the last saved data, with an explicit warning.
- No source guarantees a complete future release schedule. An empty selection means no supplied dates, not that the platform has no releases.
- Movie metadata is requested in English because the provider currently accepts only `en`, `es`, `tr` and `fr` for this endpoint. Interface controls remain localized by Royal.

## RD checks

The server rejects checks before the supplied timestamp and for unknown dates. After that time, users can search existing configured RD providers. A confirmed catalog match requires the exact TMDB movie ID. This is a catalog lookup, **not a guarantee that a playable hoster link works**. No download starts automatically. Checks are cached for 15 minutes; failures and timeouts remain inconclusive.

The API key stays in server-side settings and is never returned to the browser. Cached release data and the request ledger survive restarts in `movie_releases_cache.json` in the application data directory.
