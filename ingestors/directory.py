from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Generator

from followthemoney import model
from followthemoney.proxy import EntityProxy
from ftm_lakehouse.core.conventions import tag

from ingestors.ingestor import Ingestor
from ingestors.settings import OP_INGEST


class DirectoryIngestor(Ingestor):
    """Traverse the entries in a directory."""

    MIME_TYPE = "inode/directory"

    SKIP_ENTRIES = [".git", ".hg", "__MACOSX", ".gitignore"]

    def ingest(self, file_path, entity):
        """Ingestor implementation."""
        if entity.schema == model.get("Document"):
            entity.schema = model.get("Folder")

        if file_path is None or not file_path.is_dir():
            return

        self.crawl(self.manager, file_path, parent=entity)

    @classmethod
    def walk(
        cls,
        manager,
        file_path: Path,
        parent=None,
        origin: str = OP_INGEST,
        skip: set[str] | None = None,
    ) -> Generator[tuple[EntityProxy, Path], None, None]:
        """Emit the folders below `file_path` as they are reached and yield
        the files to store and queue, leaving out those whose local path is in
        `skip`."""
        for path in file_path.iterdir():
            name = path.name
            if name is None or name in cls.SKIP_ENTRIES:
                continue
            sub_path = file_path.joinpath(name)
            child = manager.make_entity("Document", parent=parent)
            child.add("fileName", name)
            if sub_path.is_dir():
                if parent is not None:
                    child.make_id(parent.id, name)
                else:
                    child.make_id(name)
                child.schema = model.get("Folder")
                child.add("mimeType", cls.MIME_TYPE)
                manager.emit_entity(child, origin=origin)
                yield from cls.walk(
                    manager, sub_path, parent=child, origin=origin, skip=skip
                )
            elif skip and sub_path.as_posix() in skip:
                continue
            else:
                yield child, sub_path

    @classmethod
    def queue(
        cls,
        manager,
        child: EntityProxy,
        file_path: Path,
        checksum: str,
        origin: str = OP_INGEST,
    ) -> None:
        child.make_id(file_path.name, checksum)
        child.set("contentHash", checksum)
        if origin == tag.CRAWL_ORIGIN:
            # the crawl is what discovered this file: record it under
            # its own origin
            manager.emit_entity(child, origin=origin)
        manager.queue_entity(child)

    @classmethod
    def crawl(
        cls,
        manager,
        file_path: Path,
        parent=None,
        origin: str = OP_INGEST,
        skip: set[str] | None = None,
        threads: int = 1,
    ) -> None:
        """Emit the folders and store and queue the files below `file_path`,
        leaving out the files whose local path is in `skip`. Use `threads` > 1
        for a remote archive"""
        files = cls.walk(manager, file_path, parent, origin, skip)
        if threads < 2:
            for child, path in files:
                checksum = manager.store(path, origin=origin)
                cls.queue(manager, child, path, checksum, origin)
            return
        pending: deque[tuple[EntityProxy, Path, Future[str]]] = deque()

        def drain(keep: int) -> None:
            while len(pending) > keep:
                child, path, future = pending.popleft()
                cls.queue(manager, child, path, future.result(), origin)

        with ThreadPoolExecutor(threads) as pool:
            for child, path in files:
                pending.append(
                    (child, path, pool.submit(manager.store, path, origin=origin))
                )
                drain(2 * threads)
            drain(0)
