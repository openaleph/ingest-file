[![Docs](https://img.shields.io/badge/docs-live-brightgreen)](https://openaleph.org/docs/lib/ingest-file/)
[![Python test and package](https://github.com/openaleph/ingest-file/actions/workflows/build.yml/badge.svg)](https://github.com/openaleph/ingest-file/actions/workflows/build.yml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Coverage Status](https://coveralls.io/repos/github/openaleph/ingest-file/badge.svg?branch=main)](https://coveralls.io/github/openaleph/ingest-file?branch=main)
[![AGPLv3+ License](https://img.shields.io/pypi/l/ftmq)](./LICENSE)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://pydantic.dev)

# ingest-file

``ingest-file`` extract useful information from documents of different types in a structured standard format. It retains folder structures across directories, compressed archives and emails. The extracted data is formatted as [Follow the Money (FtM)](https://followthemoney.tech) entities, ready for import into [OpenAleph](https://openaleph.org), or processing as an object graph.

## Documentation

https://openaleph.org/docs/lib/ingest-file

## Development environment

For local development use [poetry](https://python-poetry.org/)

```bash
poetry install --with dev --all-extras
```

### pre-commit

```bash
pre-commit install
```

## Release procedure

```bash
# on main branch
git pull --rebase
make build
make test
poetry run bump2version {patch,minor,major} # pick the appropriate one
git push
```

## Usage

Ingestors are usually called in the context of Aleph. In order to run them
stand-alone, you can use the supplied docker compose environment. To enter
a working container, run:

```bash
make build
make shell
```

Inside the shell, you will find the `ingestors` command-line tool. During
development, it is convenient to call its debug mode using files present
in the user's home directory, which is mounted at `/host`:

```bash
ingestors debug /host/Documents/sample.xlsx
```

## License

As of release version 3.18.4 `ingest-file` is licensed under the AGPLv3 or later license. Previous versions were released under the MIT license.
