!!! info
    This guide is a technical reference and assumes some experience with service deployments, docker setups and security measurements for production setups. _ingest-file_ and [OpenAleph](https://openaleph.org) are complex software systems and don't provide a full-step beginners setup guide, on purpose.


ingest-file needs a file-like _Archive_ to store source files, a database to write [FollowTheMoney data](https://followthemoney.tech) and task queue data, and a runtime cache (key-value store), e.g. Redis.

For simple stand-alone use cases or local development / testing environments, the database can be a simple sqlite and the runtime cache can be in-memory.

For production use, a Postgresql database and Redis cache backend should be used to allow persistence and distributed processing.

## Installation

### Docker

Because ingest-file uses a lot of dependencies, the best way to use it _out of the box_ is to use the pre-build docker container at [ghcr.io/openaleph/ingest-file](https://github.com/openaleph/ingest-file/pkgs/container/ingest-file)

    docker pull ghcr.io/openaleph/ingest-file

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

Office documents are converted to PDF with LibreOffice. By default every document spawns a fresh LibreOffice process, which costs a second or more per document before any work is done. Optionally, the conversion can go through a persistent [unoserver](https://github.com/unoconv/unoserver) listener instead, which keeps LibreOffice running between documents.

The listener is published as its own image, built on the same base image (and so the same LibreOffice and fonts) as ingest-file itself: [ghcr.io/openaleph/ingest-file-unoserver](https://github.com/openaleph/ingest-file/pkgs/container/ingest-file-unoserver). It listens on port `2003`. Point the worker at it:

```bash
INGESTORS_UNOSERVER_URI=http://unoserver:2003
```

The supplied `docker-compose.yml` contains an example service, started with `docker compose --profile unoserver up -d unoserver`. A listener you run yourself needs unoserver 3.5 or newer; older versions reject every conversion.

A few rules for deploying it:

- **One listener per worker.** A listener converts one document at a time, so workers sharing a listener queue up behind each other.
- **Always restart it.** unoserver exits when LibreOffice dies or a conversion runs into its timeout, and expects to be restarted. It exits with status `0` after a timeout, so use `restart: always` / `unless-stopped` (or a Kubernetes Deployment), not `on-failure`.
- **Don't address a separate container as `localhost`.** A `localhost` listener is assumed to share the worker's filesystem and is handed file paths. A listener in another container (including a sidecar in the same Kubernetes pod) must be addressed by its service name or IP so the file contents are sent instead.
- **Keep its timeout below the worker's.** The image kills a conversion after 280 seconds (`--conversion-timeout 280`), below the worker's `INGESTORS_CONVERT_TIMEOUT` (300 seconds), so a stuck document fails once instead of being retried by spawning. Arguments given to the container are appended and override the defaults, e.g. `--conversion-timeout 100`.

If the listener can't be reached, the worker logs a warning and falls back to spawning LibreOffice for that document. A document LibreOffice can't convert fails right away, as spawning would fail the same way.

## Redis

Accepts any valid redis url (including a password). If `REDIS_URL` is not set, an in-memory cache is used which doesn't persist.

```bash
REDIS_URL=redis://localhost
```

## Debug mode

For local development, testing or a quick one-shot usage, this uses an in-memory store for the task queue (which will not persist)

```bash
DEBUG=1
```
