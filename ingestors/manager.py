import logging
from datetime import datetime
from functools import cache
from tempfile import mkdtemp
from timeit import default_timer
from typing import Any

import magic
from banal import ensure_list
from followthemoney import model
from followthemoney.helpers import entity_filename
from followthemoney.namespace import Namespace
from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.utils import safe_fragment
from ftmq.store.memory import MemoryStore
from normality import stringify
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import App
from openaleph_procrastinate.util import make_checksum_entity
from prometheus_client import Counter, Histogram
from rigour.mime import normalize_mimetype
from servicelayer.archive import init_archive
from servicelayer.archive.archive import Archive
from servicelayer.archive.util import ensure_path
from servicelayer.extensions import get_extensions

from ingestors import __version__
from ingestors.directory import DirectoryIngestor
from ingestors.exc import ENCRYPTED_MSG, ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.misc.tika import TikaIngestor
from ingestors.settings import Settings
from ingestors.util import filter_text, remove_directory

log = logging.getLogger(__name__)

OP_INGEST = "ingest"

INGESTIONS_SUCCEEDED = Counter(
    "ingestfile_ingestions_succeeded_total",
    "Successful ingestions",
    ["ingestor"],
)
INGESTIONS_FAILED = Counter(
    "ingestfile_ingestions_failed_total",
    "Failed ingestions",
    ["ingestor"],
)
INGESTION_DURATION = Histogram(
    "ingestfile_ingestion_duration_seconds",
    "Ingest duration by ingestor",
    ["ingestor"],
    # The bucket sizes are a rough guess right now, we might want to adjust
    # them later based on observed durations
    buckets=[
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        5,
        15,
        60,
        5 * 60,
        15 * 60,
    ],
)
INGESTED_BYTES = Counter(
    "ingestfile_ingested_bytes_total",
    "Total number of bytes ingested",
    ["ingestor"],
)


@cache
def get_archive() -> Archive:
    from servicelayer import settings

    return init_archive(
        archive_type=settings.ARCHIVE_TYPE,
        path=settings.ARCHIVE_PATH,
        bucket=settings.ARCHIVE_BUCKET,
        publication_bucket=settings.PUBLICATION_BUCKET,
    )


class Manager:
    """Handles the lifecycle of an ingestor. This can be subclassed to embed it
    into a larger processing framework."""

    #: Indicates that during the processing no errors or failures occurred.
    STATUS_SUCCESS = "success"
    #: Indicates occurrence of errors during the processing.
    STATUS_FAILURE = "failure"

    MAGIC = magic.Magic(mime=True)

    def __init__(self, app: App, dataset: str, context: dict[str, Any]):
        settings = Settings()
        self.app = app
        self.dataset = dataset
        self.db = get_fragments(dataset, OP_INGEST, database_uri=settings.fragments_uri)
        self.writer = self.db.bulk()
        self.context = context
        self.ns = Namespace(self.context["namespace"])
        self.work_path = ensure_path(mkdtemp(prefix="ingestor-"))
        self.emitted = MemoryStore()
        self.archive = get_archive()

    def make_entity(self, schema, parent=None):
        schema = model.get(schema)
        if schema is None:
            raise ProcessingException("Invalid schema")
        entity = model.make_entity(schema, key_prefix=self.dataset)
        self.make_child(parent, entity)
        return entity

    def make_child(self, parent, child):
        """Derive entity properties by knowing it's parent folder."""
        if parent is not None and child is not None:
            # Folder hierarchy:
            child.add("parent", parent.id)
            child.add("ancestors", parent.get("ancestors"))
            child.add("ancestors", parent.id)
            self.apply_context(child, parent)

    def apply_context(self, entity, source):
        # Aleph-specific context data:
        entity.context = {
            "created_at": source.context.get("created_at"),
            "updated_at": source.context.get("updated_at"),
            "role_id": source.context.get("role_id"),
            "mutable": False,
        }

    def emit_entity(self, entity, fragment=None):
        entity = self.ns.apply(entity)
        self.writer.put(entity.to_dict(), fragment)
        with self.emitted.writer() as bulk:
            bulk.add_entity(make_checksum_entity(entity, quiet=True))

    def emit_text_fragment(self, entity, texts, fragment):
        texts = [t for t in ensure_list(texts) if filter_text(t)]
        if len(texts):
            doc = self.make_entity(entity.schema)
            doc.id = entity.id
            doc.add("indexText", texts)
            self.emit_entity(doc, fragment=safe_fragment(fragment))

    def auction(self, file_path, entity) -> type[Ingestor]:
        if not entity.has("mimeType"):
            if file_path.is_dir():
                entity.add("mimeType", DirectoryIngestor.MIME_TYPE)
                return DirectoryIngestor
            entity.add("mimeType", self.MAGIC.from_file(file_path.as_posix()))

        if "application/encrypted" in entity.get("mimeType"):
            raise ProcessingException(ENCRYPTED_MSG)

        best_score, best_cls = 0, None
        for cls in get_extensions("ingestors"):
            score = cls.match(file_path, entity)
            if score > best_score:
                best_score = score
                best_cls = cls
        if best_cls is None:
            settings = Settings()
            if settings.tika_fallback:
                best_cls = TikaIngestor
            else:
                raise ProcessingException("Format not supported")
        return best_cls

    def queue_entity(self, entity):
        with self.app.open():
            defer.ingest(self.app, self.dataset, [entity], **self.context)

    def store(self, file_path, mime_type=None):
        file_path = ensure_path(file_path)
        mime_type = normalize_mimetype(mime_type)
        if file_path is not None and file_path.is_file():
            return self.archive.archive_file(file_path, mime_type=mime_type)

    def load(self, content_hash, file_name=None):
        # log.info("Local archive name: %s", file_name)
        return self.archive.load_file(
            content_hash, file_name=file_name, temp_path=self.work_path
        )

    def ingest_entity(self, entity):
        for content_hash in entity.get("contentHash", quiet=True):
            file_name = entity_filename(entity)
            file_path = self.load(content_hash, file_name=file_name)
            if file_path is None or not file_path.exists():
                log.error(
                    f"Couldn't find file named {file_name} at path {file_path}."
                    "Skipping ingestion."
                )
                continue
            self.ingest(file_path, entity)
            return
        # don't emit this entity if we didn't find a file to ingest
        self.finalize(entity, emit=False)

    def ingest(self, file_path, entity, **kwargs):
        """Main execution step of an ingestor."""
        file_path = ensure_path(file_path)
        file_size = None

        if file_path.is_file():
            file_size = file_path.stat().st_size  # size in bytes

        if file_size is not None and not entity.has("fileSize"):
            entity.add("fileSize", file_size)

        now = datetime.now()
        now_string = now.strftime("%Y-%m-%dT%H:%M:%S.%f")

        entity.set("processingStatus", self.STATUS_FAILURE)
        entity.set("processingAgent", __version__)
        entity.set("processedAt", now_string)

        ingestor_class = None
        ingestor_name = None

        try:
            ingestor_class = self.auction(file_path, entity)
            ingestor_name = ingestor_class.__name__
            log.info(f"Ingestor [{repr(entity)}]: {ingestor_name}")

            start_time = default_timer()
            self.delegate(ingestor_class, file_path, entity)
            duration = max(0, default_timer() - start_time)

            INGESTIONS_SUCCEEDED.labels(ingestor=ingestor_name).inc()
            INGESTION_DURATION.labels(ingestor=ingestor_name).observe(duration)

            if file_size is not None:
                INGESTED_BYTES.labels(ingestor=ingestor_name).inc(file_size)

            entity.set("processingStatus", self.STATUS_SUCCESS)
        except ProcessingException as pexc:
            log.exception(f"[{repr(entity)}] Failed to process: {pexc}")
            INGESTIONS_FAILED.labels(ingestor=ingestor_name).inc()
            entity.set("processingError", stringify(pexc))
        finally:
            self.finalize(entity)

    def finalize(self, entity, emit: bool | None = True):
        if emit:
            self.emit_entity(entity)
        self.writer.flush()
        remove_directory(self.work_path)

    def delegate(self, ingestor_class, file_path, entity):
        ingestor_class(self).ingest(file_path, entity)

    def close(self):
        self.writer.flush()
        remove_directory(self.work_path)
