# Test tooling only; never deploy this image to the NAS.
FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS node-tooling
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg git libatomic1 && rm -rf /var/lib/apt/lists/*
COPY --from=node-tooling /usr/local/bin/node /usr/local/bin/node
RUN node --version
WORKDIR /test
COPY requirements-dev.lock /tmp/requirements-dev.lock
RUN python -m pip install --no-cache-dir -r /tmp/requirements-dev.lock pytest-timeout==2.4.0
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python"]
