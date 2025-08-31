[![Docs](https://img.shields.io/badge/docs-live-brightgreen)](https://openaleph.org/docs/lib/ingest-file/)
[![Python test and package](https://github.com/openaleph/ingest-file/actions/workflows/build.yml/badge.svg)](https://github.com/openaleph/ingest-file/actions/workflows/build.yml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Coverage Status](https://coveralls.io/repos/github/openaleph/ingest-file/badge.svg?branch=main)](https://coveralls.io/github/openaleph/ingest-file?branch=main)
[![AGPLv3+ License](https://img.shields.io/pypi/l/ftmq)](./LICENSE)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://pydantic.dev)

# ingest-file

``ingest-file`` extract useful information from documents of different types in a structured standard format. It retains folder structures across directories, compressed archives and emails. The extracted data is formatted as [Follow the Money (FtM)](https://followthemoney.tech) entities, ready for import into [OpenAleph](https://openaleph.org), or processing as an object graph.

## Supported file types:

* Plain text
* Images
* Web pages, XML documents
* PDF files
* Emails (Outlook, plain text)
* Archive files (ZIP, Rar, etc.)
* Audio and Video text extraction via [ftm-transcribe](https://github.com/openaleph/ftm-transcribe)

[See all mime types](./reference/mime.md)

## Other features:

* Extendable and composable using classes and mixins.
* Generates [FollowTheMoney](https://followthemoney.tech) objects to a database as result objects.
* Queue support for distributed processing based on [procrastinate](https://procrastinate.readthedocs.io/en/stable/)
* Thoroughly tested.

## Usage

- [Setup](./setup.md)
- [Usage](./usage.md)
- [Explainer: What exactly does ingest-file do?](./pipeline.md)


## License

As of release version 3.18.4 `ingest-file` is licensed under the AGPLv3 or later license. Previous versions were released under the MIT license.
