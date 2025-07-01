from pathlib import Path
from typing import Optional

import typer
from anystore.cli import ErrorHandler
from anystore.logging import configure_logging, get_logger
from ftmq.io import smart_write_proxies
from ftmstore import get_dataset
from rich.console import Console
from servicelayer.tags import Tags
from typing_extensions import Annotated

from ingestors import __version__
from ingestors.settings import Settings
from ingestors.tasks import ingest_path

log = get_logger(__name__)
settings = Settings()
cli = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=True,
    pretty_exceptions_short=not settings.debug,
)
console = Console(stderr=True)


@cli.callback(invoke_without_command=True)
def cli_base(
    version: Annotated[Optional[bool], typer.Option(..., help="Show version")] = False,
):
    if version:
        print(__version__)
        raise typer.Exit()
    configure_logging()


@cli.command("ingest")
def cli_ingest(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            writable=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    dataset: Annotated[
        str, typer.Option(..., "-d", "--dataset", help="Name of the dataset")
    ],
    languages: Annotated[
        Optional[list[str]], typer.Option(help="3-letter language code (ISO 639)")
    ] = None,
):
    """Queue a local directory for ingest."""
    with ErrorHandler(log):
        if settings.debug:
            from ftmstore import settings as fts
            from servicelayer import settings as sls

            fts.DATABASE_URI = "sqlite:///debug.sqlite3"
            sls.TAGS_DATABASE_URI = fts.DATABASE_URI

        ingest_path(dataset, path, languages or [])

        if settings.debug:
            from openaleph_procrastinate.settings import DeferSettings

            from ingestors.tasks import app

            defer_settings = DeferSettings()
            db = get_dataset(dataset)
            db.delete()
            app.run_worker(queues=[defer_settings.ingest.queue], wait=False)
            smart_write_proxies("-", db.iterate())


@cli.command()
def cache_clear(prefix: str = ""):
    """Delete all ingest cache entries.

    Only delete entries with the given prefix (e.g: 'ocr:', 'pdf:').
    """
    with ErrorHandler(log):
        Tags("ingest_cache").delete(prefix=prefix)


@cli.command("settings")
def cli_settings():
    """Show current configuration"""
    with ErrorHandler(log):
        console.print(settings)
