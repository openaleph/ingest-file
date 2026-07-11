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
ingestors ingest -d my_dataset ./path/to/files`
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

## CLI Reference

[CLI reference](./reference/cli.md)

## Minimal Out-Of-The-Box  Example
Note that supplying a sqlite database is not valid in `OPENALEPH_DB_URI`.
Assuming a postgres database `ingestdb` reachable at `localhost:5432`:

```bash
docker run -it --rm \
    -v "$PWD":/data \
    -e ARCHIVE_PATH=/data/archive \
    -e FTM_STORE_URI=sqlite:////data/followthemoney.store \
    -e OPENALEPH_DB_URI=postgresql://user:password@localhost:5432/ingestdb \
    -e DEBUG=1 \
    --network=host \
    ghcr.io/openaleph/ingest-file \
    ingestors ingest -d my_dataset /data/example.pdf
```

Which does the following:  
Given a file in the current directory called `example.pdf`,
ingest the file and output the resulting dataset to the file `./followthemoney.store`,
an sqlite database.
This also produces the directory `./archive`, which will contain the file
you just ingested.
If you omit

Note, that this still requires setting up the database beforehand using 
```bash
docker run \
    ...    \
    openaleph-procrastinate init-db
```
