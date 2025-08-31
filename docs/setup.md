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
