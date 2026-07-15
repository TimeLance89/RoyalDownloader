# Royal Downloader – Container-Image für den 24/7-Betrieb (NAS/Docker).
ARG APP_COMMIT_SHA=""
FROM python:3.12-slim AS runtime-base

# System-Abhängigkeiten:
#  - chromium:        echter Browser für nodriver (VOE-Extraktion +
#                     Cloudflare-/Turnstile-Bypass via CDP). Der Extractor
#                     startet ihn im Root-Container explizit ohne Sandbox.
#  - ffmpeg:          von yt-dlp für HLS/M3U8-Streams (VOE u.a.) zwingend nötig.
#  - ca-certificates: TLS-Wurzelzertifikate für curl_cffi/HTTPS.
#  - fonts-liberation: Zeichensatz, damit Chromium headless sauber rendert.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ffmpeg \
        ca-certificates \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/seriendownloader

# Python-Abhängigkeiten zuerst (bessere Layer-Cache-Nutzung).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Die Zwischenstufe darf lokale Git-Metadaten sehen, schreibt daraus aber nur
# die Revision ins Image. Im finalen Image landet kein .git-Verzeichnis.
FROM runtime-base AS source
ARG APP_COMMIT_SHA
ENV APP_COMMIT_SHA=${APP_COMMIT_SHA}
COPY . .
RUN python -c "from update_checker import write_build_commit_marker; write_build_commit_marker('/opt/seriendownloader')" \
    && rm -rf /opt/seriendownloader/.git

FROM runtime-base AS runtime
ARG APP_COMMIT_SHA
COPY --from=source /opt/seriendownloader /opt/seriendownloader

# nodriver 0.50.3 liefert cdp/network.py mit ungültigem UTF-8 aus → reparieren,
# sonst scheitert `import nodriver` (VOE-Extraktion).
RUN python -c "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()" || true

# Betriebsmodus im Container:
#  - SERIENDL_DATA_DIR: persistenter State (Cookies, Hoster-Intel, Einstellungen,
#                       Watchlist) → per Volume gesichert.
#  - DOWNLOAD_DIR:      Ziel der fertigen Downloads → Bind-Mount auf NAS-Medien.
#  - HOST/PORT:         im Netzwerk erreichbar machen (0.0.0.0).
#  - OPEN_BROWSER=0:    im Container KEINEN Browser öffnen.
#  - CHROME_PATH:       Explizites Chromium-Binary für den VOE-Browser-Pool.
ENV SERIENDL_DATA_DIR=/app/data \
    APP_RUNTIME_DIR=/runtime \
    DOWNLOAD_DIR=/movies \
    SERIES_DIR=/serien \
    HOST=0.0.0.0 \
    PORT=8765 \
    OPEN_BROWSER=0 \
    CHROME_PATH=/usr/bin/chromium \
    APP_COMMIT_SHA=${APP_COMMIT_SHA} \
    PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python", "docker_bootstrap.py"]
