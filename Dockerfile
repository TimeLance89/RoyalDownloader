# Royal Downloader container image for 24/7 NAS and Docker operation.
ARG APP_COMMIT_SHA=""
# Build the local speech verifier without shipping compiler tools in the image.
FROM python:3.12.15-slim-bookworm AS audio-language
RUN apt-get -o Acquire::Retries=0 update \
    && apt-get -o Acquire::Retries=0 install -y --no-install-recommends build-essential cmake ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN python -c "from urllib.request import urlretrieve; urlretrieve('https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.8.2', 'whisper.tar.gz'); urlretrieve('https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin', 'ggml-tiny.bin')" \
    && echo 'bcee25589bb8052d9e155369f6759a05729a2022d2a8085c1aa4345108523077  whisper.tar.gz' | sha256sum -c - \
    && echo 'be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21  ggml-tiny.bin' | sha256sum -c - \
    && tar -xzf whisper.tar.gz \
    && cmake -S whisper.cpp-1.8.2 -B build -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
        -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF \
    && cmake --build build --target whisper-cli -j 2 \
    && install -D -m 0755 build/bin/whisper-cli /audio-language/whisper-cli \
    && install -D -m 0644 ggml-tiny.bin /audio-language/ggml-tiny.bin \
    && install -D -m 0644 whisper.cpp-1.8.2/LICENSE /audio-language/LICENSE \
    && /audio-language/whisper-cli --help >/dev/null 2>&1

FROM python:3.12.15-slim-bookworm AS runtime-base
ARG APP_UID=1000
ARG APP_GID=1000
ARG CHROME_SECURITY_FLOOR="151.0.7922.169-1"
ARG DEBIAN_CHROMIUM_SECURITY_FLOOR="151.0.7922.169-1~deb12u1"
ARG DEBIAN_PERL_SECURITY_FLOOR="5.36.0-7+deb12u4"
ARG DEBIAN_OPENSSL_SECURITY_FLOOR="3.0.22-1~deb12u2"
ARG DEBIAN_APT_SECURITY_FLOOR="2.6.2"

# System dependencies:
#  - Chrome/Chromium:  real browser for CDP-assisted extraction and verification.
#  - xvfb:             private virtual display for the user-driven browser view.
#  - ffmpeg:           required by yt-dlp for HLS/M3U8 streams.
#  - ca-certificates:  root certificates used by curl_cffi and HTTPS.
#  - fonts-liberation: fonts for consistent browser rendering.
#
# Debian bookworm-security can temporarily lag Chromium security releases. On
# amd64 we therefore use Google's signed Stable APT repository and enforce the
# minimum browser build containing the current security fixes. Other
# architectures keep Debian Chromium, but fail closed until Debian publishes
# the same fixed security baseline.
RUN set -eux; \
    # CVE-2026-109518 is triggered by download retries in the inherited APT.
    apt-get -o Acquire::Retries=0 update; \
    apt-get -o Acquire::Retries=0 install -y --no-install-recommends --only-upgrade apt libapt-pkg6.0; \
    for package in apt libapt-pkg6.0; do \
        installed_version="$(dpkg-query -W -f='${Version}' "${package}")"; \
        dpkg --compare-versions "${installed_version}" ge "${DEBIAN_APT_SECURITY_FLOOR}"; \
    done; \
    apt-get install -y --no-install-recommends \
        apt \
        libapt-pkg6.0 \
        tini \
        xvfb \
        ffmpeg \
        ca-certificates \
        perl-base \
        openssl \
        libssl3 \
        libpcre2-8-0 \
        fonts-liberation; \
    # CVE-2026-109518: the pinned Bookworm base contains APT 2.6.1.
    # Upgrade both packages and fail the build if security mirrors lag behind.
    for package in apt libapt-pkg6.0; do \
        installed_version="$(dpkg-query -W -f='${Version}' "${package}")"; \
        dpkg --compare-versions "${installed_version}" ge "${DEBIAN_APT_SECURITY_FLOOR}"; \
    done; \
    # Explicitly upgrade inherited OpenSSL packages and reject unfixed mirrors.
    # Debian bookworm's CVE-2026-84782 fix ships in deb12u2.
    for package in openssl libssl3; do \
        installed_version="$(dpkg-query -W -f='${Version}' "${package}")"; \
        dpkg --compare-versions "${installed_version}" ge "${DEBIAN_OPENSSL_SECURITY_FLOOR}"; \
    done; \
    # Upgrade the inherited Perl runtime to Debian's CVE-2026 security fixes.
    perl_version="$(dpkg-query -W -f='${Version}' perl-base)"; \
    dpkg --compare-versions "${perl_version}" ge "${DEBIAN_PERL_SECURITY_FLOOR}"; \
    architecture="$(dpkg --print-architecture)"; \
    if [ "${architecture}" = "amd64" ]; then \
        python -c "import urllib.request; urllib.request.urlretrieve('https://dl.google.com/linux/linux_signing_key.pub', '/usr/share/keyrings/google-chrome.asc')"; \
        printf '%s\n' 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.asc] https://dl.google.com/linux/chrome/deb/ stable main' > /etc/apt/sources.list.d/google-chrome.list; \
        apt-get update; \
        apt-get install -y --no-install-recommends google-chrome-stable; \
        chrome_version="$(dpkg-query -W -f='${Version}' google-chrome-stable)"; \
        dpkg --compare-versions "${chrome_version}" ge "${CHROME_SECURITY_FLOOR}"; \
        ln -sfn /usr/bin/google-chrome-stable /usr/local/bin/royal-chrome; \
    else \
        apt-get install -y --no-install-recommends chromium; \
        chromium_version="$(dpkg-query -W -f='${Version}' chromium)"; \
        chromium_common_version="$(dpkg-query -W -f='${Version}' chromium-common)"; \
        dpkg --compare-versions "${chromium_version}" ge "${DEBIAN_CHROMIUM_SECURITY_FLOOR}"; \
        dpkg --compare-versions "${chromium_common_version}" ge "${DEBIAN_CHROMIUM_SECURITY_FLOOR}"; \
        ln -sfn /usr/bin/chromium /usr/local/bin/royal-chrome; \
    fi; \
    ln -sfn /usr/local/bin/royal-chrome /usr/local/bin/chromium; \
    /usr/local/bin/royal-chrome --version; \
    rm -f /etc/apt/sources.list.d/google-chrome.list /usr/share/keyrings/google-chrome.asc; \
    rm -rf /var/lib/apt/lists/*

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
COPY --from=audio-language /audio-language /opt/royal-audio-language
COPY --from=source --chown=royal:royal /opt/seriendownloader /opt/seriendownloader

# Repair invalid UTF-8 shipped in nodriver 0.50.3 cdp/network.py.
RUN python -c "import core.nodriver_patch; core.nodriver_patch.ensure_cdp_utf8()" || true

# Container runtime:
#  - SERIENDL_DATA_DIR: persistent settings, cookies, browser profile, subscriptions, and queue state.
#  - DOWNLOAD_DIR:      completed movie destination mounted from the NAS.
#  - HOST/PORT:         expose the service on the container network.
#  - OPEN_BROWSER=0:    never open a host desktop browser inside the container.
#  - CHROME_PATH:       architecture-neutral browser entry point created above.
ENV SERIENDL_DATA_DIR=/app/data \
    APP_RUNTIME_DIR=/runtime \
    DOWNLOAD_DIR=/movies \
    SERIES_DIR=/serien \
    HOST=0.0.0.0 \
    PORT=8765 \
    OPEN_BROWSER=0 \
    CHROME_PATH=/usr/local/bin/royal-chrome \
    HOME=/home/royal \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

USER royal
ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["python", "container_entrypoint.py"]
