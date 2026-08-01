# Dependency and image updates

Production installs use `requirements.lock`; Docker and native startup do not
resolve from the looser input file. The current reviewed runtime includes
Python 3.12.13, FastAPI 0.141.1, Uvicorn 0.52.0, yt-dlp 2026.7.4, curl-cffi
0.16.0, and cryptography 48.0.1. Seerr defaults to v3.4.1.

To propose an update, edit only the direct constraints in `requirements.txt`,
run `scripts/update_dependency_lock.sh`, review every direct and transitive
change plus the vulnerability audit, and commit both input and generated lock.
CI installs the reviewed lock, audits it, and publishes critical-module
coverage. Image-version changes follow the same reviewed commit flow.

Automatic yt-dlp mutation is disabled by default. When explicitly enabled,
the updater accepts only a stable version and verifies the downloaded wheel
against the SHA-256 digest published in PyPI metadata before installation.

Before updating a NAS deployment, back up `data` and retain `runtime/previous`.
The application status reports the target commit, and the rollback action
atomically returns to the previous versioned source and dependency directory.
After a rollback, confirm the build revision and the versions listed in the
updater status before resuming downloads.
