# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/openaleph/ingest-file-base:main
# latest 3.x: tika-python is pinned <4, and its default TIKA_VERSION is 3.3.2
ARG TIKA_VERSION=3.3.2

# --- tika: the server jar tika-python starts inline when no external server is
# configured (see TIKA_CLIENT_ONLY in docker-compose.yml). ---
FROM ${BASE_IMAGE} AS tika
ARG TIKA_VERSION

RUN set -eux; \
    url="https://repo1.maven.org/maven2/org/apache/tika/tika-server-standard/${TIKA_VERSION}/tika-server-standard-${TIKA_VERSION}.jar"; \
    mkdir /tika; \
    curl -fsSL -o /tika/tika-server.jar "$url"; \
    curl -fsSL -o /tika/tika-server.jar.md5 "$url.md5"; \
    echo "$(cat /tika/tika-server.jar.md5)  /tika/tika-server.jar" | md5sum -c -

# --- deps: python dependencies only, so source edits don't invalidate them ---
FROM ${BASE_IMAGE} AS deps
ARG TIKA_VERSION

WORKDIR /ingestors

COPY requirements.txt ./
RUN pip3 install --no-cache-dir --no-deps -r requirements.txt

COPY --from=tika /tika ./contrib

# a bare soname is resolved by ld.so on both x86_64 and aarch64
ENV LD_PRELOAD=libgomp.so.1 \
    ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    LAKEHOUSE_URI=/data \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    PROCRASTINATE_APP=ingestors.tasks.app \
    TIKA_PATH=/ingestors/contrib \
    TIKA_VERSION=${TIKA_VERSION}

# --- source: application code, without tests or the rest of the repo ---
FROM deps AS source

COPY pyproject.toml README.md LICENSE ./
COPY ingestors ./ingestors

# --- runtime: the published image ---
FROM source AS runtime

RUN pip3 install --no-cache-dir --no-deps .

CMD ["procrastinate", "worker", "-q", "ingest"]

# --- test: dev dependencies, installed editable so a bind mount takes effect ---
FROM source AS test

COPY requirements-dev.txt ./
RUN pip3 install --no-cache-dir --no-deps -r requirements-dev.txt
RUN pip3 install --no-cache-dir --no-deps -e .

COPY tests ./tests

RUN chown -R app:app /ingestors

ENV DEBUG=1

CMD ["pytest", "tests"]
