# Jellyfin recommendations

[← Project overview](../README.md) · [Docker and NAS guide](DOCKER.md)

Royal Downloader maintains a global Jellyfin collection named
`Für dich empfohlen` by default. The first calculation starts with the server;
later runs follow the configured interval. Saving changed Jellyfin settings
triggers an immediate recalculation.

## Setup

Save the Jellyfin URL, API key, and user in the web interface. Container
deployments persist this configuration at:

```text
/app/data/FilmeDownloader/settings.ini
```

The default host mount is:

```text
./data/FilmeDownloader/settings.ini
```

Start the normal server:

```bash
docker compose up -d --build
docker compose logs -f seriendownloader
```

Stop any older standalone `jellyfin-recommender` container. Two processes must
not update the same collection.

## Optional environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `COLLECTION_NAME` | `Für dich empfohlen` | Exact collection name |
| `TOP_N` | `20` | Maximum number of recommendations |
| `RECENCY_HALF_LIFE_DAYS` | `180` | Recency weighting; `0` disables it |
| `RECOMMENDER_INTERVAL_SECONDS` | `86400` | Interval between runs; minimum 60 seconds |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Jellyfin read timeout |
| `PAGE_SIZE` | `100` | Page size for metadata-heavy requests; maximum 100 |

The collection ID remains stable across updates. If profile data is missing or
duplicate collections with the same name exist, the current collection is not
modified destructively. Failed runs retry after 15 minutes.

When the collection has no primary image, Royal Downloader sets the poster of
the highest-ranked recommendation once. Existing or manually selected artwork
is preserved.
