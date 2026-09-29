from followthemoney import model
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
    def crawl(
        cls,
        manager,
        file_path,
        parent=None,
        origin: str = OP_INGEST,
        skip: set[str] | None = None,
    ):
        """Emit the folders and store and queue the files below `file_path`,
        leaving out the files whose local path is in `skip`."""
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
                cls.crawl(manager, sub_path, parent=child, origin=origin, skip=skip)
            elif skip and sub_path.as_posix() in skip:
                continue
            else:
                checksum = manager.store(sub_path, origin=origin)
                child.make_id(name, checksum)
                child.set("contentHash", checksum)
                if origin == tag.CRAWL_ORIGIN:
                    # the crawl is what discovered this file: record it under
                    # its own origin
                    manager.emit_entity(child, origin=origin)
                manager.queue_entity(child)
