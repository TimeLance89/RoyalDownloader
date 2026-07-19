#!/bin/bash
# Bootstrap entrypoint for NAS deployments that mount the source directory into
# a generic Python container. It installs dependencies, then starts the server.
#
# NAS setup:
#   1. Copy the repository to the NAS, for example /Deluxe.
#   2. Mount it into a Python container such as python:3.12.
#   3. Set the command to: bash /Deluxe/start.sh
#
# Persistent state and downloads remain in the mounted data/ and downloads/ folders.
set -e
cd "$(dirname "$0")"

# --- DNS for NAS deployments and provider blocking --------------------------
# The container uses ordinary resolvers. A local resolver may encrypt its
# upstream connection. DNS_OVERRIDE=0 preserves Docker's existing resolv.conf.
export DNS_OVERRIDE="${DNS_OVERRIDE:-1}"
export DNS_PRIMARY="${DNS_PRIMARY:-1.1.1.1}"
export DNS_SECONDARY="${DNS_SECONDARY:-9.9.9.9}"

if [ "$DNS_OVERRIDE" = "1" ] && [ -w /etc/resolv.conf ]; then
    # Accept IP characters only to prevent invalid or injected resolver lines.
    if [[ "$DNS_PRIMARY" =~ ^[0-9A-Fa-f:.]+$ ]] && \
       [[ "$DNS_SECONDARY" =~ ^[0-9A-Fa-f:.]+$ ]]; then
        resolver_options="$(grep -E '^(search|domain|options)[[:space:]]' /etc/resolv.conf 2>/dev/null || true)"
        if {
            printf 'nameserver %s\n' "$DNS_PRIMARY"
            printf 'nameserver %s\n' "$DNS_SECONDARY"
            if [ -n "$resolver_options" ]; then
                printf '%s\n' "$resolver_options"
            fi
        } > /etc/resolv.conf; then
            echo "[start.sh] DNS: ${DNS_PRIMARY}, ${DNS_SECONDARY}"
        else
            echo "[start.sh] WARNING: DNS configuration could not be written." >&2
        fi
    else
        echo "[start.sh] WARNING: DNS_PRIMARY or DNS_SECONDARY is not a valid IP address." >&2
    fi
elif [ "$DNS_OVERRIDE" = "1" ]; then
    echo "[start.sh] WARNING: /etc/resolv.conf is not writable; configure DNS in the container settings." >&2
fi

# Non-fatal diagnostic showing whether the configured resolver is effective.
python -c "import socket; print('[start.sh] DNS check serienstream.to:', socket.gethostbyname('serienstream.to'))" \
    || echo "[start.sh] WARNING: serienstream.to could not be resolved." >&2

# --- System dependencies; skip installation on later starts -----------------
#  chromium: real browser for nodriver and CDP-assisted extraction.
#  ffmpeg:   required by yt-dlp for HLS/M3U8 streams.
need_apt=0
command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || need_apt=1
command -v ffmpeg   >/dev/null 2>&1 || need_apt=1
if [ "$need_apt" = "1" ]; then
    echo "[start.sh] Installing chromium and ffmpeg …"
    apt-get update
    apt-get install -y --no-install-recommends \
        chromium ffmpeg ca-certificates fonts-liberation
    rm -rf /var/lib/apt/lists/*
fi

# --- Python dependencies; idempotent ----------------------------------------
echo "[start.sh] Installing Python dependencies …"
pip install --no-cache-dir -r requirements.txt

# Repair the invalid UTF-8 byte shipped in nodriver 0.50.3 cdp/network.py.
echo "[start.sh] Checking nodriver encoding …"
python -c "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()" || true

# --- Container runtime; docker-compose and .env may override these values ---
export HOST="${HOST:-0.0.0.0}"                       # reachable on the container network
export PORT="${PORT:-8765}"
export OPEN_BROWSER="${OPEN_BROWSER:-0}"             # do not open a local desktop browser
export SERIENDL_DATA_DIR="${SERIENDL_DATA_DIR:-$(pwd)/data}"       # cookies, routing data, settings
export DOWNLOAD_DIR="${DOWNLOAD_DIR:-$(pwd)/downloads}"            # completed movie destination
export CHROME_PATH="${CHROME_PATH:-$(command -v chromium || command -v chromium-browser)}"

if [ ! -x "$CHROME_PATH" ]; then
    echo "[start.sh] ERROR: Chromium binary is not executable: ${CHROME_PATH}" >&2
    exit 1
fi
echo "[start.sh] Chromium: ${CHROME_PATH} ($("$CHROME_PATH" --version))"

echo "[start.sh] Starting Royal Downloader on ${HOST}:${PORT} …"
exec python server.py
