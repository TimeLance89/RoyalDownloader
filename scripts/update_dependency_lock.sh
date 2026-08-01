#!/usr/bin/env bash
set -euo pipefail

command -v uv >/dev/null || {
  echo "uv is required to regenerate the reviewed dependency locks." >&2
  exit 1
}

uv pip compile requirements.in \
  --python-version 3.12 \
  --generate-hashes \
  --output-file requirements.lock
uv pip compile requirements-dev.in \
  --python-version 3.12 \
  --generate-hashes \
  --output-file requirements-dev.lock
uv run --with pip-audit pip-audit --require-hashes -r requirements.lock
