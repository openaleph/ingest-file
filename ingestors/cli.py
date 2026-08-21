from pathlib import Path
from typing import Optional

import typer
from anystore.cli import ErrorHandler
from anystore.logging import configure_logging, get_logger
from ftmq.io import smart_read_proxies, smart_write_proxies
from ftmq.query import M, Query
from openaleph_procrastinate.repository import get_entity_store
from rich import print
from servicelayer.tags import Tags
from typing_extensions import Annotated

from ingestors import __version__
from ingestors.settings import Settings
from ingestors.tasks import ingest_entity, ingest_path

log = get_logger(__name__)
settings = Settings()
cli = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=True,
    pretty_exceptions_short=not settings.debug,
)

OPT_INPUT_URI = typer.Option("-", "-i", help="Input uri, default stdin")


@cli.callback(invoke_without_command=True)
def cli_base(
    version: Annotated[Optional[bool], typer.Option(..., help="Show version")] = False,
    settings: Annotated[
        Optional[bool], typer.Option(..., help="Show current settings")
    ] = False,
):
    if version:
        print(__version__)
        raise typer.Exit()
    if settings:
        print(Settings())
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
    foreign_id: Annotated[
        Optional[str],
        typer.Option(..., "-f", "--foreign-id", help="Foreign ID of the dataset"),
    ] = None,
    languages: Annotated[
        Optional[list[str]], typer.Option(help="3-letter language code (ISO 639)")
    ] = None,
):
    """Queue a local directory for ingest."""
    with ErrorHandler(log):
        ingest_path(dataset, path, languages or [], foreign_id)

        if settings.debug:
            from openaleph_procrastinate.settings import DeferSettings

            from ingestors.tasks import app

            defer_settings = DeferSettings()
            db = get_entity_store(dataset)
            # db.delete()
            app.run_worker(queues=[defer_settings.ingest.queue], wait=False)
            smart_write_proxies("-", db.iterate())


@cli.command()
def ingest_entities(
    dataset: Annotated[
        str, typer.Option(..., "-d", "--dataset", help="Name of the dataset")
    ],
    uri: str = OPT_INPUT_URI,
    foreign_id: Annotated[
        Optional[str],
        typer.Option(..., "-f", "--foreign-id", help="Foreign ID of the dataset"),
    ] = None,
    languages: Annotated[
        Optional[list[str]], typer.Option(help="3-letter language code (ISO 639)")
    ] = None,
):
    """Queue ingest a stream of entities"""
    with ErrorHandler(log):
        q = Query().where(M(schemata="Document"), ~M(schema="Folder"))
        for entity in smart_read_proxies(uri, q):
            ingest_entity(dataset, entity, languages, foreign_id)

        if settings.debug:
            from openaleph_procrastinate.settings import DeferSettings

            from ingestors.tasks import app

            defer_settings = DeferSettings()
            app.run_worker(queues=[defer_settings.ingest.queue], wait=False)
            db = get_entity_store(dataset)
            db.flush()
            # trigger flush to journal:
            for _ in db.iterate():
                return


@cli.command()
def cache_clear(
    prefix: Annotated[
        str,
        typer.Option(
            default="",
            help="Only delete entries with the given prefix (e.g: 'ocr:', 'pdf:').",
        ),
    ] = "",
):
    """Delete ingest cache entries."""
    with ErrorHandler(log):
        Tags("ingest_cache", uri=settings.tags_database_uri).delete(prefix=prefix)
