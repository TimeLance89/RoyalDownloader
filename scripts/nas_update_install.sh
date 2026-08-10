#!/bin/bash
# Installiert ein mit build_nas_update.py erzeugtes Paket auf einer bestehenden
# NAS-/Docker-Installation. Persistente Daten, .env, Runtime und Medien bleiben
# unangetastet. Bei einem fehlgeschlagenen Start wird der Quellstand restauriert.
set -Eeuo pipefail

bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target_arg="${1:-}"
legacy_container="${2:-}"
if [ -z "$target_arg" ]; then
    echo "Verwendung: bash install.sh /pfad/zu/RoyalDownloader [alter-container]" >&2
    exit 2
fi
target="$(cd -- "$target_arg" && pwd -P)"
case "$target" in
    /|/home|/volume1|/volume2) echo "Zu breites Installationsziel: $target" >&2; exit 2 ;;
esac
if [ -n "$legacy_container" ] && [[ ! "$legacy_container" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Ungültiger alter Containername" >&2
    exit 2
fi

for required in docker-compose.yml data runtime; do
    if [ ! -e "$target/$required" ]; then
        echo "Ungültige Installation: $target/$required fehlt" >&2
        exit 2
    fi
done
for required in payload.tar.gz payload.sha256 commit.txt; do
    if [ ! -f "$bundle_dir/$required" ]; then
        echo "Updatepaket unvollständig: $required fehlt" >&2
        exit 2
    fi
done
command -v docker >/dev/null || { echo "Docker fehlt" >&2; exit 2; }
command -v sha256sum >/dev/null || { echo "sha256sum fehlt" >&2; exit 2; }
docker compose version >/dev/null

commit="$(tr -d '\r\n' < "$bundle_dir/commit.txt")"
if [[ ! "$commit" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "Ungültige Zielrevision im Updatepaket" >&2
    exit 2
fi
expected_hash="$(tr -d '\r\n' < "$bundle_dir/payload.sha256")"
printf '%s  %s\n' "$expected_hash" "$bundle_dir/payload.tar.gz" | sha256sum --check --status

staging="$(mktemp -d "$target/.nas-update-staging.XXXXXX")"
backup_root="$target/.nas-update/backups"
backup="$backup_root/$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
mkdir -p "$backup"
rollback_needed=0
legacy_stopped=0

cleanup() {
    rm -rf -- "$staging"
}

rollback() {
    code=$?
    trap - ERR
    if [ "$rollback_needed" = "1" ]; then
        echo "Update fehlgeschlagen; vorheriger Quellstand wird restauriert." >&2
        if [ -f "$staging/.nas_managed_files" ]; then
            while IFS= read -r relative; do
                case "$relative" in
                    ""|/*|../*|*/../*|data/*|runtime/*|downloads/*|.env|.env.*) continue ;;
                esac
                rm -f -- "$target/$relative"
            done < "$staging/.nas_managed_files"
        fi
        tar -xzf "$backup/source-before-update.tar.gz" -C "$target"
        if [ "$legacy_stopped" = "1" ]; then
            (
                cd "$target"
                docker compose stop seriendownloader
            ) || true
            docker start "$legacy_container" || true
        else
            (
                cd "$target"
                docker compose up -d --build --force-recreate seriendownloader
            ) || true
        fi
    fi
    cleanup
    exit "$code"
}
trap rollback ERR
trap cleanup EXIT

tar -xzf "$bundle_dir/payload.tar.gz" -C "$staging"
for required in Dockerfile docker-compose.yml server.py self_updater.py update_checker.py .app_commit_sha .nas_managed_files; do
    if [ ! -f "$staging/$required" ]; then
        echo "Payload unvollständig: $required fehlt" >&2
        false
    fi
done
if [ "$(tr -d '\r\n' < "$staging/.app_commit_sha")" != "$commit" ]; then
    echo "Payload und Zielrevision stimmen nicht überein" >&2
    false
fi

tar \
    --exclude='./.git' \
    --exclude='./.env' \
    --exclude='./.env.*' \
    --exclude='./data' \
    --exclude='./runtime' \
    --exclude='./downloads' \
    --exclude='./Filme' \
    --exclude='./Serien' \
    --exclude='./debug' \
    --exclude='./.nas-update' \
    -czf "$backup/source-before-update.tar.gz" -C "$target" .

rollback_needed=1
if [ -f "$target/.nas_managed_files" ]; then
    while IFS= read -r relative; do
        case "$relative" in
            ""|/*|../*|*/../*|data/*|runtime/*|downloads/*|.env|.env.*) continue ;;
        esac
        if ! grep -Fqx -- "$relative" "$staging/.nas_managed_files"; then
            rm -f -- "$target/$relative"
        fi
    done < "$target/.nas_managed_files"
fi
(cd "$staging" && tar -cf - .) | (cd "$target" && tar -xf -)

(
    cd "$target"
    docker compose config --quiet
    APP_COMMIT_SHA="$commit" docker compose build seriendownloader
)
if [ -n "$legacy_container" ]; then
    docker inspect "$legacy_container" >/dev/null
    docker stop "$legacy_container"
    legacy_stopped=1
fi
(
    cd "$target"
    APP_COMMIT_SHA="$commit" docker compose up -d --no-build --force-recreate seriendownloader
)

healthy=0
for _attempt in $(seq 1 60); do
    if (
        cd "$target"
        docker compose exec -T \
            -e EXPECTED_COMMIT="$commit" \
            seriendownloader python -c \
            'import os; from pathlib import Path; active=Path("/proc/1/cwd").resolve(); actual=(active/".app_commit_sha").read_text().strip(); assert actual == os.environ["EXPECTED_COMMIT"], (actual, os.environ["EXPECTED_COMMIT"])'
    ) >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 2
done
if [ "$healthy" != "1" ]; then
    echo "Neue Zielrevision wurde nicht aktiv" >&2
    false
fi

rollback_needed=0
trap - ERR
echo "NAS-Update aktiv: ${commit:0:12}"
if [ "$legacy_stopped" = "1" ]; then
    echo "Alter Container bleibt gestoppt als Rückfalloption: $legacy_container"
fi
