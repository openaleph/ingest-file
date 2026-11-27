Ingest file can be used stand-alone or in the context of [OpenAleph](https://openaleph.org)

!!! info
    This guide assumes a proper [setup](./setup.md)

Depending on [setup](./setup.md), the commands have to be run with or without the docker container. When using docker, make sure to mount the volumes needed and attach to a running postgres container if needed.

**docker**

    docker run -it ghcr.io/openaleph/ingest-file ingestors ...

**locally**

    ingestors ...

## Directory or File Ingestion

Store files in archive and dispatch tasks. This accepts as well a single file as path argument.

```bash
ingestors ingest -d my_dataset ./path/to/files
```

### Resuming an ingest

With the [lakehouse](https://openaleph.org/docs/lib/ftm-lakehouse) storage backend (`OPENALEPH_LAKEHOUSE=1`), `--resume` skips the files a previous run already crawled. They are looked up in the dataset's documents crawl export (`exports/documents.crawl.csv`) by their path below the crawl root, so run it against the same (relative) root as before.

```bash
ingestors ingest -d my_dataset --resume ./path/to/files
```

### Start worker(s)

```bash
procrastinate worker -q ingest --concurrency 8
```

### One-shot ingestion

Instead of having long-running workers, run the worker in sync mode. It will stop after all tasks are processed:

```bash
procrastinate worker -q ingest --one-shot --concurrency 8
```

### debug mode

This will run the worker in-memory, so no additional worker command needed:

```bash
DEBUG=1 ingestors ingest -d my_dataset ./path/to/files
```

## Minimal docker example

Ingest `example.pdf` from the current directory. The task queue needs postgres (a sqlite file doesn't work as `OPENALEPH_DB_URI`), and the image expects it and redis at the hosts `postgres` and `redis`, so run both as containers of these names in a shared network:

```bash
docker network create ingest
docker run -d --network ingest --name postgres \
    -e POSTGRES_USER=aleph -e POSTGRES_PASSWORD=aleph -e POSTGRES_DB=aleph \
    postgres:17
docker run -d --network ingest --name redis redis:alpine
```

Once postgres is up, initialize the database:

```bash
docker run --rm --network ingest ghcr.io/openaleph/ingest-file openaleph-procrastinate init-db
```

Ingest the file:

```bash
docker run -it --rm --network ingest \
    -v "$PWD":/data \
    -e ARCHIVE_PATH=/data/archive \
    -e FTM_STORE_URI=sqlite:////data/followthemoney.store \
    -e DEBUG=1 \
    ghcr.io/openaleph/ingest-file \
    ingestors ingest -d my_dataset /data/example.pdf
```

The file is stored in `./archive`, and its entities are written to the sqlite database `./followthemoney.store` and printed to stdout.

## CLI Reference

[CLI reference](./reference/cli.md)
