import functools
import gc
from pathlib import Path

from anystore.logging import get_logger
from followthemoney import registry
from followthemoney.dataset.util import dataset_name_check
from followthemoney.proxy import EntityProxy
from ftm_lakehouse.core.conventions import tag
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob
from openaleph_procrastinate.tasks import task
from prometheus_client import Info
from servicelayer.archive.util import ensure_path

from ingestors import __version__
from ingestors.directory import DirectoryIngestor
from ingestors.exc import ProcessingException
from ingestors.manager import Manager
from ingestors.support.cache import CacheSupport
from ingestors.support.ocr import init_ocr

SYSTEM = Info("ingestfile_system", "ingest-file system information")
SYSTEM.info({"ingestfile_version": __version__})

# tasks run in a worker thread, this has to happen here on the main thread
init_ocr()

app = make_app(__loader__.name)
sync_app = make_app(__loader__.name, sync=True)
cache = CacheSupport()


@functools.cache
def _emitted_count_key(dataset: str) -> str:
    return cache.cache_key(dataset, "emitted")


SKIP_ANALYSIS = ("Workbook", "Package", "Folder")


def should_analyze(e: EntityProxy) -> bool:
    if e.schema.is_a("Analyzable"):
        for schema in SKIP_ANALYSIS:
            if e.schema.is_a(schema):
                return False
        for txt in e.get_type_values(registry.text):
            if txt:
                return True
    return False


@task(app=app, retry=defer.tasks.ingest.retries)
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

    emitted = manager.get_emitted()
    if not len(emitted):
        job.log.error("No entities to be emitted!")

    for entity in emitted:
        if should_analyze(entity):
            to_analyze.append(entity)

        to_index.append(entity)

    job.log.info(
        f"Emitted {len(emitted)} entities.",
        emitted=[e.id for e in emitted],
    )
    if to_analyze:
        defer.analyze(app, job.dataset, to_analyze, batch=job.batch, **job.context)
    if to_index:
        defer.index(app, job.dataset, to_index, batch=job.batch, **job.context)

    # FIXME
    gc.collect()

    # exceptions are swallowed earlier, but we want to tell procrastinate
    # that this task fail if it threw any exception
    if manager.error:
        raise ProcessingException(manager.error)


def ingest_path(
    dataset: str,
    path: Path,
    languages: list[str] | None = None,
    foreign_id: str | None = None,
):
    if foreign_id:
        foreign_id = dataset_name_check(foreign_id)
    context = {"languages": languages or [], "namespace": foreign_id or dataset}
    manager = Manager(sync_app, dataset, context)
    path = ensure_path(path)
    log = get_logger(__name__, dataset=dataset, context=context, path=path)
    if path is not None:
        if path.is_file():
            entity = manager.make_entity("Document")
            checksum = manager.store(path, origin=tag.CRAWL_ORIGIN)
            entity.set("contentHash", checksum)
            entity.make_id(checksum)
            entity.set("fileName", path.name)
            log.info(f"Queue: `{path.name}` ({checksum})", entity=entity.to_dict())
            manager.emit_entity(entity, origin=tag.CRAWL_ORIGIN)
            manager.queue_entity(entity)
        if path.is_dir():
            DirectoryIngestor.crawl(manager, path, origin=tag.CRAWL_ORIGIN)
    emitted = manager.get_emitted()
    log.info(f"Emitted {len(emitted)} entities.", emitted=[e.id for e in emitted])
    manager.close()


def ingest_entity(
    dataset: str,
    entity: EntityProxy,
    languages: list[str] | None = None,
    foreign_id: str | None = None,
):
    if foreign_id:
        foreign_id = dataset_name_check(foreign_id)
    context = {"languages": languages or [], "namespace": foreign_id or dataset}
    manager = Manager(sync_app, dataset, context)
    log = get_logger(__name__, dataset=dataset, context=context, entity_id=entity.id)
    if not entity.schema.is_a("Document") or not entity.has("contentHash"):
        log.warn("Skip ingest, not of schema `Document` or missing `contentHash`")
        return
    log.info(f"Queue: `{entity.first('fileName')}` ({entity.first('contentHash')})")
    manager.queue_entity(entity)
    manager.close()
