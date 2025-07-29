import logging
from pathlib import Path

from anystore.logging import get_logger
from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob
from openaleph_procrastinate.tasks import task
from prometheus_client import Info
from servicelayer.archive.util import ensure_path

from ingestors import __version__
from ingestors.directory import DirectoryIngestor
from ingestors.manager import Manager

SYSTEM = Info("ingestfile_system", "ingest-file system information")
SYSTEM.info({"ingestfile_version": __version__})

app = make_app(__loader__.name)
sync_app = make_app(__loader__.name, sync=True)

log = logging.getLogger(__name__)


@task(app=app)
def ingest(job: DatasetJob) -> None:
    to_analyze: list[EntityProxy] = []
    to_index: list[EntityProxy] = []
    manager = Manager(sync_app, job.dataset, job.context)

    try:
        for entity in job.get_entities():
            job.log.debug(
                f"Ingesting `{entity.first("contentHash")}`", entity=entity.to_dict()
            )
            manager.ingest_entity(entity)
    finally:
        manager.close()

    for entity in manager.iterate_emitted():
        if entity.schema.is_a("Analyzable"):
            to_analyze.append(entity)

        to_index.append(entity)

    job.log.info(f"Emitted {len(manager.emitted)} entities.", emitted=manager.emitted)
    if to_analyze:
        defer.analyze(app, job.dataset, to_analyze, **job.context)
    if to_index:
        defer.index(app, job.dataset, to_index, **job.context)


def ingest_path(
    dataset: str, path: Path, languages: list[str], foreign_id: str | None = None
):
    context = {"languages": languages, "namespace": foreign_id or dataset}
    manager = Manager(sync_app, dataset, context)
    path = ensure_path(path)
    log = get_logger(__name__, dataset=dataset, context=context, path=path)
    if path is not None:
        if path.is_file():
            entity = manager.make_entity("Document")
            checksum = manager.store(path)
            entity.set("contentHash", checksum)
            entity.make_id(checksum)
            entity.set("fileName", path.name)
            log.info(f"Queue: `{path.name}` ({checksum})", entity=entity.to_dict())
            manager.queue_entity(entity)
        if path.is_dir():
            DirectoryIngestor.crawl(manager, path)
    log.info(f"Emitted {len(manager.emitted)} entities.", emitted=manager.emitted)
    manager.close()
