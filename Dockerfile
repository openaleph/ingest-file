FROM ghcr.io/openaleph/ingest-file-base:latest

# uncomment when running on Apple Silicon
# ENV LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libgomp.so.1
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libgomp.so.1

COPY . /ingestors
RUN rm -rf /ingestors/tests
WORKDIR /ingestors

# force compile tesserocr 2.6.2 with C++ 14
# to make it compatible with Tesseract 5
RUN pip download --no-binary=:all: "tesserocr==2.6.2" \
    && tar -xzf tesserocr-2.6.2.tar.gz \
    && sed -i "s/-std=c++11/-std=c++14/" tesserocr-2.6.2/setup.py \
    && cd tesserocr-2.6.2 \
    && CXXFLAGS="-std=c++14" pip install --no-cache-dir .

RUN pip3 install --no-cache-dir -r /ingestors/requirements.txt
RUN pip3 install --no-deps --no-cache-dir /ingestors

ENV ARCHIVE_TYPE=file \
    ARCHIVE_PATH=/data \
    OPENALEPH_DB_URI=postgresql://aleph:aleph@postgres/aleph \
    REDIS_URL=redis://redis:6379/0 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

ENV PROCRASTINATE_APP="ingestors.tasks.app"

RUN chmod +x /ingestors/docker-entrypoint.sh

ENTRYPOINT [ "/ingestors/docker-entrypoint.sh" ]
CMD ["procrastinate", "worker", "-q", "ingest"]
