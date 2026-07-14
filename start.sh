#!/bin/bash
# Boot-Entrypoint für den NAS-Docker-Betrieb (Code wird in den Container
# gemountet) – Muster wie beim Game-/d365-bot-Projekt: Abhängigkeiten + Browser
# beim Start installieren, dann den Server starten.
#
# So nutzt du es auf dem NAS:
#   1. Diesen Projektordner ins NAS ziehen (z.B. nach /Deluxe).
#   2. Einen Python-Container (z.B. python:3.12) darauf mounten, sodass der Ordner
#      im Container z.B. unter /Deluxe liegt.
#   3. Als Ausführungsbefehl setzen:  /Deluxe/start.sh   (bzw. bash /Deluxe/start.sh)
#
# Persistenz + Downloads landen direkt im gemounteten Ordner (data/ + downloads/).
set -e
cd "$(dirname "$0")"

# --- DNS für NAS/Provider-Sperren -------------------------------------------
# Der Container nutzt den lokalen Resolver; dessen Upstream kann verschlüsselt
# per DNS-over-TLS zu dnsforge laufen. Der zweite Server ist der Fallback.
# DNS_OVERRIDE=0 lässt die von Docker vorgegebene resolv.conf unverändert.
export DNS_OVERRIDE="${DNS_OVERRIDE:-1}"
export DNS_PRIMARY="${DNS_PRIMARY:-1.1.1.1}"
export DNS_SECONDARY="${DNS_SECONDARY:-9.9.9.9}"

if [ "$DNS_OVERRIDE" = "1" ] && [ -w /etc/resolv.conf ]; then
    # Nur IP-Zeichen zulassen; verhindert ungültige/injizierte resolv.conf-Zeilen.
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
            echo "[start.sh] WARNUNG: DNS-Konfiguration konnte nicht geschrieben werden." >&2
        fi
    else
        echo "[start.sh] WARNUNG: DNS_PRIMARY/DNS_SECONDARY enthalten keine gültige IP." >&2
    fi
elif [ "$DNS_OVERRIDE" = "1" ]; then
    echo "[start.sh] WARNUNG: /etc/resolv.conf ist nicht beschreibbar – DNS im Container-Dialog setzen." >&2
fi

# Diagnose ohne Startabbruch: zeigt sofort, ob der alternative Resolver greift.
python -c "import socket; print('[start.sh] DNS-Test serienstream.to:', socket.gethostbyname('serienstream.to'))" \
    || echo "[start.sh] WARNUNG: serienstream.to konnte nicht aufgelöst werden." >&2

# --- System-Abhängigkeiten (nur wenn noch nicht vorhanden → schneller Neustart) ---
#  chromium: echter Browser für nodriver (VOE-Extraktion + Cloudflare-/Turnstile-
#            Bypass). Der Extractor deaktiviert die Sandbox im Root-Container.
#  ffmpeg:   von yt-dlp für HLS/M3U8-Streams (VOE u.a.) zwingend nötig.
need_apt=0
command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || need_apt=1
command -v ffmpeg   >/dev/null 2>&1 || need_apt=1
if [ "$need_apt" = "1" ]; then
    echo "[start.sh] Installiere chromium + ffmpeg …"
    apt-get update
    apt-get install -y --no-install-recommends \
        chromium ffmpeg ca-certificates fonts-liberation
    rm -rf /var/lib/apt/lists/*
fi

# --- Python-Abhängigkeiten (idempotent) ---
echo "[start.sh] Installiere Python-Abhängigkeiten …"
pip install --no-cache-dir -r requirements.txt

# nodriver 0.50.3 liefert cdp/network.py mit ungültigem UTF-8 (± als Latin-1-Byte)
# aus → sonst scheitert `import nodriver` und damit die VOE-Extraktion. Reparieren.
echo "[start.sh] Prüfe/repariere nodriver-Encoding …"
python -c "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()" || true

# --- Betriebsmodus im Container (Env aus docker-compose/.env überschreibbar) ---
export HOST="${HOST:-0.0.0.0}"                       # im Netzwerk erreichbar
export PORT="${PORT:-8765}"
export OPEN_BROWSER="${OPEN_BROWSER:-0}"             # kein lokaler Browser
export SERIENDL_DATA_DIR="${SERIENDL_DATA_DIR:-$(pwd)/data}"       # Cookies/Intel/Config
export DOWNLOAD_DIR="${DOWNLOAD_DIR:-$(pwd)/downloads}"            # Ziel der Downloads
export CHROME_PATH="${CHROME_PATH:-$(command -v chromium || command -v chromium-browser)}"

if [ ! -x "$CHROME_PATH" ]; then
    echo "[start.sh] FEHLER: Chromium-Binary nicht ausführbar: ${CHROME_PATH}" >&2
    exit 1
fi
echo "[start.sh] Chromium: ${CHROME_PATH} ($("$CHROME_PATH" --version))"

echo "[start.sh] Starte Royal Downloader auf ${HOST}:${PORT} …"
exec python server.py
