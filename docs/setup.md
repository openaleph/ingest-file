!!! info
    This guide is a technical reference and assumes some experience with service deployments, docker setups and security measurements for production setups. _ingest-file_ and [OpenAleph](https://openaleph.org) are complex software systems and don't provide a full-step beginners setup guide, on purpose.


ingest-file needs a file-like _Archive_ to store source files, a database to write [FollowTheMoney data](https://followthemoney.tech) and task queue data, and a runtime cache (key-value store), e.g. Redis.

For simple stand-alone use cases or local development / testing environments, the database can be a simple sqlite and the runtime cache can be in-memory.

For production use, a Postgresql database and Redis cache backend should be used to allow persistence and distributed processing.

## Installation

### Docker

Because ingest-file uses a lot of dependencies, the best way to use it _out of the box_ is to use the pre-build docker container at [ghcr.io/openaleph/ingest-file](https://github.com/openaleph/ingest-file/pkgs/container/ingest-file)

    docker pull ghcr.io/openaleph/ingest-file

The image also contains the HTTP api (`ingestors/api.py`: upload files into a dataset as a batch, poll the batch, make the lakehouse dataset).

    docker run -p 8000:8000 ghcr.io/openaleph/ingest-file granian --interface asgi --host 0.0.0.0 ingestors.api:app

It needs `OPENALEPH_LAKEHOUSE=1`, serves its documentation at `/` and has no authentication.

### Debian / Ubuntu

For debian-like (linux) system, it is possible to install all dependencies locally so that docker is not needed. This is especially useful for rapid development / testing.

Clone the github repository:

    git clone https://github.com/openaleph/ingest-file
    cd ingest-file

Install system dependencies via apt:

    ./contrib/install_deb.sh

Install ingest-file python package:

    pip install .

Most likely, this needs to be set as well and adjusted to your system:

```bash
TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
```


## Configuration

All configuration is set via environment variables. [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) is used to parse the settings, so a `.env` file can be used as well.

### Archive

The underlying file archive is implemented via [servicelayer](https://github.com/openaleph/servicelayer) and stores the source files via its SHA1 checksums in a path layout like `ab/cd/ef/abcdef...`.

#### Local directory

```bash
ARCHIVE_TYPE=file
ARCHIVE_PATH=./data
```

#### S3-like storage

```bash
ARCHIVE_TYPE=s3
ARCHIVE_BUCKET=data
ARCHIVE_ENDPOINT_URL=https://my.storage.org  # if not using AWS
# credentials:
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

### FollowTheMoney store

Per default, ingest-file writes Entity data to a local sqlite database:

`sqlite:///followthemoney.store`

For distributed production setup, configure a psql connection string:

```bash
FTM_STORE_URI=postgresql://user:password@host/database
```

!!! warning
    Prior versions of `ingest-file` inferred the FtM store database uri from Aleph environment settings if it was not set explicitly. This behaviour has changed and the `FTM_STORE_URI` has to be set explicitly.

### Task queue

ingest-file uses [openaleph-procrastinate](https://openaleph.org/docs/lib/openaleph-procrastinate/) as a distributed task queue backend which is built on top of [procrastinate](https://procrastinate.readthedocs.io/en/stable/).

Most importantly, the `procrastinate.App` has to be defined:

```bash
PROCRASTINATE_APP=ingestors.tasks.app
```

Configure the database:

```bash
OPENALEPH_DB_URI=postgresql://user:password@host/database

# or to separate task data from other application data:
OPENALEPH_PROCRASTINATE_DB_URI=postgresql://user:password@host/database
```

### LibreOffice listener (unoserver)

Office documents are converted to PDF with LibreOffice, through a [unoserver](https://github.com/unoconv/unoserver) listener that keeps LibreOffice running between documents. Starting LibreOffice for every document instead costs a second or more per document before any work is done.

#### Inline (default)

Without further configuration, every worker thread starts a listener of its own the first time it converts a document, and keeps it for the next ones. It listens on free ports on `127.0.0.1`, has its own LibreOffice profile, and is handed file paths.

- Starting a listener takes about 6 seconds, once per thread. It is started again when it has exited, e.g. after a conversion ran into `INGESTORS_CONVERT_TIMEOUT`.
- Each listener keeps a LibreOffice process in memory, so a worker holds as many of them as jobs it runs at once (`procrastinate worker --concurrency`). They are stopped when the worker exits.
- If a thread's listener can't be started at all, that thread spawns LibreOffice per document instead, and logs a warning once.

The docker image has unoserver installed. Elsewhere, it has to be installed for the Python that has LibreOffice's `uno` bindings, see `Dockerfile.base`.

#### As a service

The listener is also published as its own image, built on the same base image (and so the same LibreOffice and fonts) as ingest-file itself: [ghcr.io/openaleph/ingest-file-unoserver](https://github.com/openaleph/ingest-file/pkgs/container/ingest-file-unoserver). It listens on port `2003`. Point the worker at it, and no listeners are started inline:

```bash
INGESTORS_UNOSERVER_URI=http://unoserver:2003
```

The supplied `docker-compose.yml` contains an example of several listeners behind an HAProxy (`unoserver-lb`, point the worker at `http://unoserver-lb:2003`), started with `docker compose up -d --scale unoserver=4 unoserver unoserver-lb`. A listener you run yourself needs unoserver 3.5 or newer; older versions reject every conversion.

A few rules for deploying it:

- **One conversion per listener.** A listener converts one document at a time, so workers sharing a listener queue up behind each other. Run as many listeners as documents are converted at once, and put a load balancer in front that hands each listener one connection at a time, like `unoserver-lb` in the compose example. Docker's DNS and a Kubernetes Service spread conversions without regard to whether a listener is busy. When the balancer gives up waiting for a free listener it has to drop the connection, not answer with an HTTP error: only a dropped connection makes the worker fall back to spawning.
- **Always restart it.** unoserver exits when LibreOffice dies or a conversion runs into its timeout, and expects to be restarted. It exits with status `0` after a timeout, so use `restart: always` / `unless-stopped` (or a Kubernetes Deployment), not `on-failure`.
- **Don't address a separate container as `localhost`.** A `localhost` listener is assumed to share the worker's filesystem and is handed file paths. A listener in another container (including a sidecar in the same Kubernetes pod) must be addressed by its service name or IP so the file contents are sent instead.
- **Keep its timeout below the worker's.** The image kills a conversion after 280 seconds (`--conversion-timeout 280`), below the worker's `INGESTORS_CONVERT_TIMEOUT` (300 seconds), so a stuck document fails once instead of being retried by spawning. Arguments given to the container are appended and override the defaults, e.g. `--conversion-timeout 100`.

In both modes, if the listener can't be reached, or stops answering, the worker logs a warning and falls back to spawning LibreOffice for that document; an inline listener that stopped answering is replaced for the next one. A document LibreOffice can't convert fails right away, as spawning would fail the same way.

## Redis

Accepts any valid redis url (including a password). If `REDIS_URL` is not set, an in-memory cache is used which doesn't persist.

```bash
REDIS_URL=redis://localhost
```

## Apache Tika

[Apache Tika](https://tika.apache.org/) extracts the files embedded in Excel files and Office Open XML documents (e.g. docx), and it is the text extraction fallback for otherwise unsupported file types (`INGESTORS_TIKA_FALLBACK=1`). ingest-file talks to it via [tika-python](https://github.com/chrismattmann/tika-python), which reads its configuration from environment variables at import time.

### Inline (default)

Without further configuration, tika-python starts a Tika server itself, inside the worker on `localhost:9998`, the first time it is needed. This needs Java, and the server jar (`tika-server.jar` plus its `.md5`) in `TIKA_PATH`:

- The docker image ships the jar in `/ingestors/contrib` and sets `TIKA_PATH` accordingly, nothing is downloaded at runtime.
- Otherwise it is downloaded from Maven Central on first use, into `TIKA_PATH` (default: the system temp directory). It is only checked against the `.md5` next to it, so a jar that is already there is never updated when `TIKA_VERSION` changes.

The inline server is a child process of whichever worker started it, and it keeps running after that worker exits.

### Server (recommended for production)

Run Tika as a service of its own and point the workers to it:

```bash
TIKA_SERVER_ENDPOINT=http://tika:9998
TIKA_CLIENT_ONLY=1
```

`TIKA_CLIENT_ONLY` makes tika-python use the endpoint as it is. Without it, tika-python still tries to start a server of its own if the endpoint is on `localhost` (e.g. a sidecar container that isn't ready yet), and it drops any path from the endpoint url. Any non-empty value enables it, `0` and `false` too, so unset it to go back to the inline server.

With docker compose (as in this repository's `docker-compose.yml`):

```yaml
services:
  tika:
    # pin a 3.x release: tika-python is used with Tika 3, `latest` is Tika 4
    image: apache/tika:3.3.1.0
    command: ["-c", "/tika-config.xml"]
    configs:
      - source: tika-config
        target: /tika-config.xml
    healthcheck:
      # the image has neither curl nor wget
      test: ["CMD", "bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/9998"]
      interval: 2s
      timeout: 5s
      retries: 30

  ingest-file:
    environment:
      TIKA_SERVER_ENDPOINT: http://tika:9998
      TIKA_CLIENT_ONLY: 1
    depends_on:
      tika:
        condition: service_healthy

configs:
  # the parse timeout and the memory of the Tika server
  tika-config:
    content: |
      <?xml version="1.0" encoding="UTF-8"?>
      <properties>
        <server>
          <params>
            <taskTimeoutMillis>300000</taskTimeoutMillis>
            <forkedJvmArgs>
              <arg>-Xmx2g</arg>
            </forkedJvmArgs>
          </params>
        </server>
      </properties>
```

### Concurrency and sizing

One Tika server handles many requests at once: every worker thread in a parse (`procrastinate worker --concurrency`) is one concurrent request, and all of them run in the same forked JVM. That has two consequences:

- Size the heap (`forkedJvmArgs`) for the sum of the concurrency of all workers using the server, not for a single file.
- When a parse runs out of memory or exceeds `taskTimeoutMillis`, the server restarts that JVM, and every request in flight fails with it, not only the offending one. For embedded files, the ingest task then fails and is retried by the task queue; the text fallback marks the file as failed (`processingStatus`) instead, without a retry.

For more throughput or isolation, run several Tika containers behind a load balancer, or one per worker (as a sidecar on `localhost`, where `TIKA_CLIENT_ONLY=1` is essential).

tika-python gives up on a request after 60 seconds, even if the server is still parsing. Very large files can hit this limit before the server's own `taskTimeoutMillis`.

## Debug mode

For local development, testing or a quick one-shot usage, this uses an in-memory store for the task queue (which will not persist)

```bash
DEBUG=1
```
