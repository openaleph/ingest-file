FROM ghcr.io/openaleph/ingest-file-base:latest

# uncomment when running on Apple Silicon
# ENV LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libgomp.so.1
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libgomp.so.1

COPY . /ingestors
RUN rm -rf /ingestors/tests
WORKDIR /ingestors

RUN pip3 install --no-cache-dir -r /ingestors/requirements.txt
RUN pip3 install --no-deps --no-cache-dir /ingestors

ENV ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

ENV PROCRASTINATE_APP="ingestors.tasks.app"

CMD ["procrastinate", "worker", "-q", "ingest"]
