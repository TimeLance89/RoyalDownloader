#!/usr/bin/env bash
# Additive published-Stable gate; the RC3 gate remains unchanged.
set -euo pipefail
stable_sha=31d91417c4d45bb054140de60b7125ac6b7dbd78
test "$(git rev-list -n 1 v1.1.0)" = "$stable_sha"
stable_dir="$(mktemp -d "${RUNNER_TEMP}/royal-stable-source.XXXXXX")"
git archive "$stable_sha" | tar -x -C "$stable_dir"
docker build --build-arg APP_COMMIT_SHA="$stable_sha" \
  --tag royal-downloader:published-stable "$stable_dir"
suffix="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
fixture="royal-stable-fixture-${suffix}"
backup="royal-stable-backup-${suffix}"
recovery="royal-stable-recovery-${suffix}"
cleanup() { docker volume rm -f "$fixture" "$backup" "$recovery" >/dev/null 2>&1 || true; }
trap cleanup EXIT
for volume in "$fixture" "$backup" "$recovery"; do
  docker volume create "$volume" >/dev/null
  docker run --rm --user 0 -v "$volume:/fixture" --entrypoint sh \
    royal-downloader:quality -c 'chown 1000:1000 /fixture'
done
run_gate() {
  docker run --rm -v "$1:/fixture" \
    -e SERIENDL_DATA_DIR=/fixture/data -e ROYAL_GATE_RUNTIME=/fixture/runtime \
    -v "${GITHUB_WORKSPACE}/scripts:/gate:ro" --entrypoint python \
    "$2" /gate/stable_upgrade_gate.py "$3"
}
copy_volume() {
  docker run --rm --user 0 -v "$1:/source:ro" -v "$2:/destination" \
    --entrypoint sh royal-downloader:quality -c 'cp -a /source/. /destination/'
}
run_gate "$fixture" royal-downloader:published-stable seed
copy_volume "$fixture" "$backup"
run_gate "$fixture" royal-downloader:quality upgrade
run_gate "$fixture" royal-downloader:quality upgrade
run_gate "$fixture" royal-downloader:published-stable rollback
copy_volume "$backup" "$recovery"
run_gate "$recovery" royal-downloader:published-stable rollback
