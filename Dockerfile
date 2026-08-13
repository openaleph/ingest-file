# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/openaleph/ingest-file-base:main

# --- deps: python dependencies only, so source edits don't invalidate them ---
FROM ${BASE_IMAGE} AS deps

WORKDIR /ingestors

COPY requirements.txt ./
RUN pip3 install --no-cache-dir --no-deps -r requirements.txt

# a bare soname is resolved by ld.so on both x86_64 and aarch64
ENV LD_PRELOAD=libgomp.so.1 \
    ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    PROCRASTINATE_APP=ingestors.tasks.app

# --- source: application code, without tests or the rest of the repo ---
FROM deps AS source

COPY pyproject.toml README.md LICENSE ./
COPY ingestors ./ingestors

# Create contrib directory for tika download
RUN mkdir ./contrib

# --- runtime: the published image ---
FROM source AS runtime

RUN pip3 install --no-cache-dir --no-deps .

CMD ["procrastinate", "worker", "-q", "ingest"]

# --- test: dev dependencies, installed editable so a bind mount takes effect ---
FROM source AS test

COPY requirements-dev.txt ./
RUN pip3 install --no-cache-dir --no-deps -r requirements-dev.txt \
    && pip3 install --no-cache-dir --no-deps -e .

COPY tests ./tests

RUN chown -R app:app /ingestors

ENV DEBUG=1 \
    LAKEHOUSE_URI=/data

CMD ["pytest", "tests"]
