FROM ghcr.io/openaleph/ingest-file-base:latest

COPY . /ingestors
RUN rm -rf /ingestors/tests
WORKDIR /ingestors
RUN pip3 install --no-cache-dir -r /ingestors/requirements.txt
RUN pip3 install --no-cache-dir /ingestors

ENV ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

ENV PROCRASTINATE_APP="ingestors.tasks.app"

RUN chmod +x /ingestors/docker-entrypoint.sh

USER app
ENTRYPOINT [ "/ingestors/docker-entrypoint.sh" ]
CMD ["procrastinate", "worker", "-q", "ingest"]
