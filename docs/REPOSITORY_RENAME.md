# Migrating to `RoyalDownloader`

[← Project overview](../README.md)

The repository was renamed on July 15, 2026:

| Item | Previous | Current |
|---|---|---|
| Product name | SerienDownloader | Royal Downloader |
| Repository | `TimeLance89/SerienDownloader` | `TimeLance89/RoyalDownloader` |
| Clone URL | `https://github.com/TimeLance89/SerienDownloader.git` | `https://github.com/TimeLance89/RoyalDownloader.git` |

The visible product name contains a space. The technical GitHub repository name
does not.

## 1. Update an existing Git remote

```bash
git remote set-url origin https://github.com/TimeLance89/RoyalDownloader.git
git remote -v
git fetch origin
```

With GitHub CLI:

```bash
gh repo view TimeLance89/RoyalDownloader
```

GitHub currently redirects old web and clone URLs. Updating the remote avoids a
permanent dependency on that redirect.

## 2. Update an existing installation

Set the repository in the NAS `.env` file:

```dotenv
UPDATE_GITHUB_REPOSITORY=TimeLance89/RoyalDownloader
UPDATE_GITHUB_BRANCH=main
```

Recreate the container so it reads the changed environment:

```bash
docker compose up -d --build
docker compose logs -f seriendownloader
```

Current builds use `TimeLance89/RoyalDownloader` automatically when no explicit
repository override exists.

## 3. Update external references

Change bookmarks, API integrations, deployment scripts, and private
documentation to:

```text
https://github.com/TimeLance89/RoyalDownloader
https://github.com/TimeLance89/RoyalDownloader.git
```

Do not create a new repository under the old name. Doing so can invalidate
GitHub's redirect.

## 4. Verify the migration

- The new repository URL opens without a redirect.
- `git push origin main` works.
- The updater reports `TimeLance89/RoyalDownloader · main` as reachable.
- An update check resolves the current `main` revision.
- README, issue forms, and documentation links work.
- Docker starts with existing `data` and `runtime` directories.

The internal names `FilmeDownloader` for the persistent configuration directory
and `seriendownloader` for the Compose service remain unchanged for backward
compatibility. Renaming them would break existing NAS volumes and startup
scripts.
