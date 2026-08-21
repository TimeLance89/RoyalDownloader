# Royal Downloader container image for 24/7 NAS and Docker operation.
ARG APP_COMMIT_SHA=""
FROM python:3.12.14-slim-bookworm AS runtime-base
ARG APP_UID=1000
ARG APP_GID=1000
ARG CHROMIUM_SECURITY_FLOOR="151.0.7922.169-1~deb12u1"

# System dependencies:
#  - chromium:         real browser for CDP-assisted extraction and verification.
#  - xvfb:             private virtual display for the user-driven browser view.
#  - ffmpeg:           required by yt-dlp for HLS/M3U8 streams.
#  - ca-certificates:  root certificates used by curl_cffi and HTTPS.
#  - fonts-liberation: fonts for consistent Chromium rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        ffmpeg \
        ca-certificates \
        fonts-liberation \
    && chromium_version="$(dpkg-query -W -f='${Version}' chromium)" \
    && chromium_common_version="$(dpkg-query -W -f='${Version}' chromium-common)" \
    && dpkg --compare-versions "${chromium_version}" ge "${CHROMIUM_SECURITY_FLOOR}" \
    && dpkg --compare-versions "${chromium_common_version}" ge "${CHROMIUM_SECURITY_FLOOR}" \
    && rm -rf /var/lib/apt/lists/*

RUN test "${APP_UID}" -gt 0 && test "${APP_GID}" -gt 0 \
    && groupadd --non-unique --gid "${APP_GID}" royal \
    && useradd --non-unique --uid "${APP_UID}" --gid royal --create-home --home-dir /home/royal royal \
    && install -d -o royal -g royal /runtime /app/data /movies /serien

WORKDIR /opt/seriendownloader

# Install Python dependencies first for efficient layer caching.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

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
COPY --from=source --chown=royal:royal /opt/seriendownloader /opt/seriendownloader

# Repair invalid UTF-8 shipped in nodriver 0.50.3 cdp/network.py.
RUN python -c "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()" || true

# Container runtime:
#  - SERIENDL_DATA_DIR: persistent settings, cookies, browser profile, subscriptions, and queue state.
#  - DOWNLOAD_DIR:      completed movie destination mounted from the NAS.
#  - HOST/PORT:         expose the service on the container network.
#  - OPEN_BROWSER=0:    never open a host desktop browser inside the container.
#  - CHROME_PATH:       explicit Chromium binary for the browser pool/verifier.
ENV SERIENDL_DATA_DIR=/app/data \
    APP_RUNTIME_DIR=/runtime \
    DOWNLOAD_DIR=/movies \
    SERIES_DIR=/serien \
    HOST=0.0.0.0 \
    PORT=8765 \
    OPEN_BROWSER=0 \
    CHROME_PATH=/usr/bin/chromium \
    HOME=/home/royal \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

USER royal
CMD ["python", "container_entrypoint.py"]
