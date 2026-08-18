"""Provide servicelayer archive and lakehouse archive as a transparent
repository during transition"""

from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import DefaultDict, Protocol

from anystore.exceptions import DoesNotExist
from anystore.logging import get_logger
from anystore.logic.io import stream
from anystore.store import get_store
from anystore.util import join_uri, make_checksum, uri_to_path
from followthemoney import EntityProxy
from ftm_lakehouse import get_archive as get_lakehouse_archive
from ftm_lakehouse import get_entities
from ftm_lakehouse.core.conventions import tag
from ftm_lakehouse.core.settings import CHECKSUM_ALGORITHM
from ftmq.query import M, Query
from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.utils import safe_fragment
from ftmq.types import EntityProxies
from normality import safe_filename
from servicelayer import settings as sls
from servicelayer.archive import init_archive

from ingestors.settings import OP_INGEST, Settings

settings = Settings()
log = get_logger(__name__)


def lakehouse_uri(dataset: str) -> str | None:
    """Dataset location for the lakehouse backend.

    `None` keeps the default `{LAKEHOUSE_URI}/{dataset}`. An override (the tests
    use one to get an isolated location per case) is joined with the dataset
    name, because the lakehouse factories take an explicit uri as-is.
    """
    if settings._lakehouse_uri:
        return join_uri(settings._lakehouse_uri, dataset)
    return None


class Archive(Protocol):
    """Blob storage for the files being ingested."""

    def archive_file(
        self, file_path: Path, mime_type: str | None = None, origin: str = OP_INGEST
    ) -> str: ...

    def load_file(
        self, content_hash: str, temp_path: Path, file_name: str | None
    ) -> Path | None: ...


class EntityStore(Protocol):
    """Read and write access to the entities of one dataset."""

    def put(self, entity: EntityProxy, fragment: str | None = None) -> None: ...

    def flush(self) -> None: ...

    def iterate(self, entity_id: str | None = None) -> EntityProxies: ...

    def get(self, entity_id: str) -> EntityProxy | None: ...

    def delete(self) -> None: ...


class ServicelayerArchive:
    def __init__(self) -> None:
        # the servicelayer archive is global, it has no notion of a dataset
        self._archive = init_archive(
            archive_type=sls.ARCHIVE_TYPE,
            path=sls.ARCHIVE_PATH,
            bucket=sls.ARCHIVE_BUCKET,
            publication_bucket=sls.PUBLICATION_BUCKET,
        )

    def archive_file(
        self, file_path: Path, mime_type: str | None = None, origin: str = OP_INGEST
    ) -> str:
        return self._archive.archive_file(file_path, mime_type=mime_type)

    def load_file(
        self, content_hash: str, temp_path: Path, file_name: str | None
    ) -> Path | None:
        return self._archive.load_file(content_hash, file_name, temp_path)


class LakehouseArchive:
    def __init__(self, dataset: str) -> None:
        self._archive = get_lakehouse_archive(dataset, lakehouse_uri(dataset))
        self._entities = get_entities(dataset, lakehouse_uri(dataset))

    def archive_file(
        self, file_path: Path, mime_type: str | None = None, origin: str = OP_INGEST
    ) -> str:
        with file_path.open("rb") as fh:
            checksum = make_checksum(fh, algorithm=CHECKSUM_ALGORITHM)
        file = self._archive.store(
            file_path,
            checksum=checksum,
            mimeType=mime_type,
            id=checksum,
            origin=origin,
        )
        if origin == tag.CRAWL_ORIGIN:
            self._entities.add(file.to_entity(), origin=tag.CRAWL_ORIGIN)
        return file.checksum

    def load_file(
        self, content_hash: str, temp_path: Path, file_name: str | None
    ) -> Path | None:
        local_key = f"{content_hash}.sl/{safe_filename(file_name, default="data")}"
        tmp_store = get_store(temp_path)
        try:
            with self._archive.open(content_hash) as i:
                with tmp_store.open(local_key, "wb") as o:
                    stream(i, o)
            return uri_to_path(tmp_store.to_uri(local_key))
        except (DoesNotExist, FileNotFoundError):
            # callers treat `None` as a miss, a blob that isn't there is not an
            # error. fsspec raises FileNotFoundError instead of DoesNotExist.
            return


class FragmentStore:
    def __init__(self, dataset: str) -> None:
        self._db = get_fragments(
            dataset, OP_INGEST, database_uri=settings.fragments_uri
        )
        self._writer = self._db.bulk()

    def put(self, entity: EntityProxy, fragment: str | None = None) -> None:
        self._writer.put(entity.to_dict(), fragment=safe_fragment(fragment))

    def flush(self) -> None:
        self._writer.flush()

    def iterate(self, entity_id: str | None = None) -> EntityProxies:
        return self._db.iterate(entity_id)

    def get(self, entity_id: str) -> EntityProxy | None:
        return self._db.get(entity_id)

    def delete(self) -> None:
        self._db.delete()


class LakehouseStore:
    def __init__(self, dataset: str) -> None:
        self._entities = get_entities(dataset, lakehouse_uri(dataset))
        self._buffer: DefaultDict[str | None, list[EntityProxy]] = defaultdict(list)

    def put(self, entity: EntityProxy, fragment: str | None = None) -> None:
        self._buffer[fragment].append(entity)

    def flush(self) -> None:
        """Flush from buffer to journal. Flushes journal to parquet if it's
        full, but final flush to parquet needs to be invoked manually by
        callers"""
        with self._entities.writer(OP_INGEST) as bulk:
            for fragment, entities in self._buffer.items():
                for entity in entities:
                    bulk.add_entity(entity, fragment=fragment)
        self._buffer.clear()

    def iterate(self, entity_id: str | None = None) -> EntityProxies:
        q = Query()
        if entity_id:
            q = q.where(M(entity_id=entity_id))
        return self._entities.query(q, flush_first=True)

    def get(self, entity_id: str) -> EntityProxy | None:
        return self._entities.get(entity_id, flush_first=True)

    def delete(self) -> None:
        self._entities.flush()
        self._entities._statements.destroy()


@cache
def get_archive(dataset: str) -> Archive:
    if settings.lakehouse:
        return LakehouseArchive(dataset)
    return ServicelayerArchive()


@cache
def get_entity_store(dataset: str) -> EntityStore:
    if settings.lakehouse:
        return LakehouseStore(dataset)
    return FragmentStore(dataset)
