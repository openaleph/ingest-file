"""Provide servicelayer archive and lakehouse archive as a transparent
repository during transition"""

from functools import cache
from pathlib import Path

from anystore.exceptions import DoesNotExist
from anystore.logic.io import stream
from anystore.store import get_store
from anystore.util import uri_to_path
from followthemoney import EntityProxy
from ftm_lakehouse import get_archive as get_lakehouse_archive
from ftm_lakehouse import get_entities
from ftm_lakehouse.util import make_checksum
from ftmq.query import M, Query
from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.utils import safe_fragment
from ftmq.types import EntityProxies
from normality import safe_filename
from servicelayer import settings as sls
from servicelayer.archive import init_archive

from ingestors.settings import OP_INGEST, Settings

settings = Settings()


class Archive:
    def archive_file(self, file_path: Path, mime_type: str | None = None) -> str: ...

    def load_file(
        self, content_hash: str, temp_path: Path, file_name: str | None
    ) -> Path | None: ...


class ServicelayerArchive(Archive):
    def __init__(self, dataset: str) -> None:
        self._archive = init_archive(
            archive_type=sls.ARCHIVE_TYPE,
            path=sls.ARCHIVE_PATH,
            bucket=sls.ARCHIVE_BUCKET,
            publication_bucket=sls.PUBLICATION_BUCKET,
        )

    def archive_file(self, file_path: Path, mime_type: str | None = None) -> str:
        return self._archive.archive_file(file_path, mime_type=mime_type)

    def load_file(
        self, content_hash: str, temp_path: Path, file_name: str | None
    ) -> Path | None:
        return self._archive.load_file(content_hash, file_name, temp_path)


class LakehouseArchive(Archive):
    def __init__(self, dataset: str) -> None:
        self._archive = get_lakehouse_archive(dataset)

    def archive_file(self, file_path: Path, mime_type: str | None = None) -> str:
        with file_path.open("rb") as fh:
            checksum = make_checksum(fh)
        file = self._archive.store(
            file_path,
            checksum=checksum,
            mimeType=mime_type,
            id=checksum,
            origin="ingest",
        )
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
        except DoesNotExist:
            return


@cache
def get_archive(dataset: str) -> Archive:
    if settings.lakehouse:
        return LakehouseArchive(dataset)
    return ServicelayerArchive(dataset)


class EntityWriter:
    def put(self, entity: EntityProxy, fragment: str | None = None) -> None: ...

    def flush(self) -> None: ...


class LakehouseWriter(EntityWriter):
    def __init__(self, dataset: str) -> None:
        self._entities = get_entities(dataset)

    def put(self, entity: EntityProxy, fragment: str | None = None) -> None:
        fragment = safe_fragment(fragment)
        self._entities.add(entity, origin=OP_INGEST, fragment=fragment)

    def flush(self) -> None:
        self._entities.flush()


class FragmentWriter(EntityWriter):
    def __init__(self, dataset: str) -> None:
        db = get_fragments(dataset, OP_INGEST, database_uri=settings.fragments_uri)
        self._writer = db.bulk()

    def put(self, entity: EntityProxy, fragment: str | None = None) -> None:
        fragment = safe_fragment(fragment)
        self._writer.put(entity.to_dict(), fragment=fragment)

    def flush(self) -> None:
        self._writer.flush()


@cache
def get_writer(dataset: str) -> EntityWriter:
    if settings.lakehouse:
        return LakehouseWriter(dataset)
    return FragmentWriter(dataset)


class Dataset:
    def iterate(self, entity_id: str | None = None) -> EntityProxies: ...

    def get(self, entity_id: str) -> EntityProxy | None: ...

    def delete(self) -> None: ...


class FragmentDataset(Dataset):
    def __init__(self, dataset: str) -> None:
        self._db = get_fragments(dataset, origin=OP_INGEST)

    def iterate(self, entity_id: str | None = None) -> EntityProxies:
        return self._db.iterate(entity_id)

    def get(self, entity_id: str) -> EntityProxy | None:
        return self._db.get(entity_id)

    def delete(self) -> None:
        self._db.delete()


class LakehouseDataset(Dataset):
    def __init__(self, dataset: str) -> None:
        self._entities = get_entities(dataset)

    def iterate(self, entity_id: str | None = None) -> EntityProxies:
        q = Query()
        if entity_id:
            q = q.where(M(entity_id=entity_id))
        return self._entities.query(q, flush_first=True)

    def get(self, entity_id: str) -> EntityProxy | None:
        return self._entities.get(entity_id, flush_first=True)

    def delete(self) -> None:
        self._entities._statements.destroy()


@cache
def get_dataset(dataset: str) -> Dataset:
    if settings.lakehouse:
        return LakehouseDataset(dataset)
    return FragmentDataset(dataset)
