FROM ghcr.io/openaleph/ingest-file-base:latest

COPY . /ingestors
WORKDIR /ingestors
RUN pip3 install --no-cache-dir -r /ingestors/requirements.txt
RUN pip3 install --no-cache-dir /ingestors

ENV ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    FTM_STORE_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

USER app
CMD ingestors process
