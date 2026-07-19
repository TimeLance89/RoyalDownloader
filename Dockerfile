# Royal Downloader container image for 24/7 NAS and Docker operation.
ARG APP_COMMIT_SHA=""
FROM python:3.12-slim AS runtime-base

# System dependencies:
#  - chromium:         real browser for nodriver and CDP-assisted extraction;
#                      the root container launches it explicitly without a sandbox.
#  - ffmpeg:           required by yt-dlp for HLS/M3U8 streams.
#  - ca-certificates:  root certificates used by curl_cffi and HTTPS.
#  - fonts-liberation: fonts for consistent headless Chromium rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ffmpeg \
        ca-certificates \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/seriendownloader

# Install Python dependencies first for efficient layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The intermediate stage may inspect local Git metadata but writes only the
# revision marker into the image. The final image contains no .git directory.
FROM runtime-base AS source
ARG APP_COMMIT_SHA
ENV APP_COMMIT_SHA=${APP_COMMIT_SHA}
COPY . .
RUN python -c "from update_checker import write_build_commit_marker; write_build_commit_marker('/opt/seriendownloader')" \
    && rm -rf /opt/seriendownloader/.git

FROM runtime-base AS runtime
ARG APP_COMMIT_SHA
COPY --from=source /opt/seriendownloader /opt/seriendownloader

# Repair invalid UTF-8 shipped in nodriver 0.50.3 cdp/network.py.
RUN python -c "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()" || true

# Container runtime:
#  - SERIENDL_DATA_DIR: persistent settings, cookies, subscriptions, and queue state.
#  - DOWNLOAD_DIR:      completed movie destination mounted from the NAS.
#  - HOST/PORT:         expose the service on the container network.
#  - OPEN_BROWSER=0:    never open a desktop browser inside the container.
#  - CHROME_PATH:       explicit Chromium binary for the browser pool.
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
