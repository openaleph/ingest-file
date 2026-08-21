# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

1. Don’t assume. Don’t hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.

## Environment

Always use the virtualenv at `.venv` when running commands (e.g. `.venv/bin/python`, `.venv/bin/pytest`).

## Project Overview

**ingest-file** extracts structured information from diverse file types (documents, spreadsheets, emails, archives, media) and formats them as Follow the Money (FtM) entities for import into OpenAleph. It preserves folder hierarchies across directories, compressed archives, and emails.

## Build and Development Commands

```bash
# Install dependencies
poetry install --with dev --all-extras

# Setup pre-commit hooks
pre-commit install

# Build Docker containers (one multi-stage Dockerfile: deps -> source -> runtime/test)
make build

# Start services (Postgres, Redis) and enter shell
make services
make shell

# Run tests (in virtualenv, not Docker). The suite picks its storage
# backend from `OPENALEPH_LAKEHOUSE`, unset means the legacy stores
pytest -s tests/
OPENALEPH_LAKEHOUSE=1 pytest -s tests/

# Run the containerised suite against both storage backends
make test              # both
make test-store        # OPENALEPH_LAKEHOUSE=0
make test-lakehouse    # OPENALEPH_LAKEHOUSE=1

# Code quality
make format          # Auto-format with Black
make format-check    # Check formatting
make lint            # Lint with Ruff

# Run pre-commit on all files
pre-commit run --all-files
```

### CLI Usage (inside Docker shell)

```bash
# Debug a file (useful during development)
ingestors debug /path/to/file

# Ingest a file into a dataset
ingestors ingest -d dataset /path/to/file
```

### Release Workflow

```bash
git pull --rebase
make build
make test
poetry run bump2version {patch,minor,major}
git push
```

## Architecture

### Plugin System

Ingestors are registered as entry points in `pyproject.toml` under `[project.entry-points."ingestors"]`. The system uses an auction-based selection mechanism where each ingestor scores its ability to handle a file, and the highest-scoring ingestor wins.

### Core Components

- **`Manager` (manager.py)**: Central orchestrator handling file type detection, ingestor selection (auction), entity lifecycle, and storage. It holds `self.archive` and `self.writer`, both obtained from `openaleph_procrastinate.repository` so it never talks to a concrete backend
- **`Ingestor` (ingestor.py)**: Base class all ingestors inherit from. Key attributes: `MIME_TYPES`, `EXTENSIONS`, `SCORE`
- **Support mixins (`support/*.py`)**: Reusable extraction logic (PDFSupport, OCRSupport, TableSupport, etc.) composed into ingestors

### Storage Backends

Files and entities are reached through `openaleph_procrastinate.repository`, which
puts the legacy stores (servicelayer archive + FtM fragments) and the ftm-lakehouse
behind the same `Archive` / `EntityStore` protocols. `OPENALEPH_LAKEHOUSE` picks one;
nothing in this repo branches on it except where the two genuinely differ:

- `get_archive(dataset)` is cached, `get_entity_store(dataset, origin)` deliberately
  is not (the stores buffer writes and sync tasks run in a thread pool)
- Fragments must be strings — the lakehouse writes them into an Arrow string column —
  so `Manager.emit_entity` coerces them with `stringify`
- The lakehouse takes entities from the job payload rather than re-fetching them, so
  `OpenAlephSettings` forces `procrastinate_dehydrate_entities` off when it is active
- Content hashes differ between the backends: servicelayer uses sha1, the lakehouse
  sha256
- `ingestors/tasks.py` counts emitted entities and flushes the lakehouse journal to
  parquet once `INGESTORS_LAKEHOUSE_FLUSH_SIZE` is reached; the legacy store is
  unaffected

### Ingestor Pattern

```python
class MyIngestor(Ingestor, SomeSupport):
    MIME_TYPES = ["application/x-something"]
    EXTENSIONS = ["ext"]
    SCORE = 3  # Higher scores win auction

    def ingest(self, file_path, entity):
        # Extract data, populate entity
        pass
```

### Key Directories

- `ingestors/documents/` - Document formats (PDF, HTML, Office, etc.)
- `ingestors/tabular/` - Spreadsheets and databases (CSV, Excel, SQLite, etc.)
- `ingestors/email/` - Email formats (PST, MSG, MBOX, etc.)
- `ingestors/packages/` - Archives (ZIP, RAR, TAR, 7z, etc.)
- `ingestors/media/` - Images, audio, video
- `ingestors/support/` - Mixin classes for shared functionality
- `tests/fixtures/` - Test files for various formats

## Testing

Tests use `unittest.TestCase` with a custom `TestCase` base class in `tests/support.py`:

```python
class MyTest(TestCase):
    def test_something(self):
        path, entity = self.fixture("sample.pdf")  # Load from tests/fixtures/
        self.manager.ingest(path, entity)
        self.assertSuccess(entity)

        entities = self.get_emitted()  # Get all emitted FtM entities
```

`self.dataset` is the `EntityStore` for the test dataset, so reads go through the
active backend (`self.dataset.iterate(entity_ids=...)`, `self.dataset.get(id)`).
`setUp` points `LAKEHOUSE_URI` at a fresh tmp dir per test and clears the cached
factories; set `TEST_LAKEHOUSE_URI` to run the suite against a shared location
instead. Tests that only hold for one backend guard on `Settings().lakehouse`.

Run tests:
```bash
# Run all tests
pytest -s tests/

# Run specific test file
pytest -s tests/test_doc.py -xvs

# Run specific test
pytest -s tests/test_doc.py::TestClass::test_method -xvs
```

## Configuration

Settings managed via `ingestors/settings.py` using Pydantic. Environment variables prefixed with `INGESTORS_`:

- `INGESTORS_CONVERT_TIMEOUT` - LibreOffice conversion timeout (default: 300s)
- `INGESTORS_TIKA_FALLBACK` - Enable Apache Tika fallback for unknown formats
- `INGESTORS_LAKEHOUSE_FLUSH_SIZE` - Emitted entities until the lakehouse journal is
  flushed to parquet (default: 10000)

Inherited from OpenAleph (`OpenAlephSettings` in `openaleph-procrastinate`):
- `OPENALEPH_DB_URI` - Postgres connection
- `OPENALEPH_LAKEHOUSE` - Use the ftm-lakehouse storage backend instead of servicelayer
  archive + ftm fragments; the switch and both implementations live upstream in
  `openaleph_procrastinate.repository`, the suite runs both ways

Backend specific, read by the libraries themselves:
- `FTM_STORE_URI` / `FTM_FRAGMENTS_URI` - FtM fragments database (legacy backend)
- `ARCHIVE_TYPE`, `ARCHIVE_PATH` - servicelayer file storage (legacy backend)
- `LAKEHOUSE_URI` / `LAKEHOUSE_JOURNAL_URI` - Lakehouse storage location and journal
  (the repositories resolve them themselves, they take no explicit uri). The journal
  uri goes to `create_engine` as-is, so Postgres has to be spelled
  `postgresql+psycopg://` — we only ship psycopg 3. It defaults to an in-memory
  sqlite, which is invisible to any other process
- `TEST_LAKEHOUSE_URI` - Test-only: run against this location instead of a per-test
  tmp dir
