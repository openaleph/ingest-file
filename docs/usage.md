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
