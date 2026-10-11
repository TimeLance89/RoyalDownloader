# Test tooling only; never deploy this image to the NAS.
FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS node-tooling
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg git libatomic1 && rm -rf /var/lib/apt/lists/*
COPY --from=node-tooling /usr/local/bin/node /usr/local/bin/node
RUN node --version
WORKDIR /test
COPY requirements-dev.lock /tmp/requirements-dev.lock
RUN python -m pip install --no-cache-dir -r /tmp/requirements-dev.lock pytest-timeout==2.4.0
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python"]
