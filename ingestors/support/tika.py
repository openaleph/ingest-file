import logging
from io import BytesIO
from pathlib import PosixPath
from typing import Any

from followthemoney import EntityProxy
from normality import collapse_spaces, safe_filename
from tika import parser, unpack

from ingestors.support.cache import CacheSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)


class TikaSupport(CacheSupport, TempFileSupport):
    def extract_tika(
        self, fh: BytesIO, cache_key: str | None = None
    ) -> dict[str, Any] | None:
        _cache_key = None
        if cache_key:
            _cache_key = self.cache_key("tika", cache_key)
            result = self.tags.get(_cache_key)
            if result is not None:
                log.info("Tika: cached result for checksum %s" % cache_key)
                return result

        result = parser.from_file(fh)
        if isinstance(result, dict):
            text = result.get("content")
            if text:
                result["content"] = collapse_spaces(text)
            if _cache_key:
                self.tags.set(_cache_key, result)
            return result

    def ingest_embedded(
        self, parent_file: PosixPath, parent: EntityProxy | None = None
    ):
        parsed = unpack.from_file(parent_file.open("rb"))
        attachments = parsed.get("attachments") or {}
        log.critical(f"Tika extracted {len(attachments.items())} attachments")
        for name, data in attachments.items():
            log.critical(f"Analyzing attachment: {name}")
            if not data:
                log.critical(f"Attachment {name} has no data")
                continue
            file_name = safe_filename(name, default="embedded")
            file_path = self.make_work_file(file_name)
            with open(file_path, "wb") as fh:
                if data is not None:
                    fh.write(data)
            # do not assign mime_type, hope the ingestor deduces it correctly
            checksum = self.manager.store(file_path)
            file_path.unlink()
            child = self.manager.make_entity("Document", parent=parent)
            child.make_id(name, checksum)
            child.add("contentHash", checksum)
            child.add("fileName", name)
            log.critical(
                f"Queuing {name} with content hash {checksum} and parent {parent.id}"
            )
            self.manager.queue_entity(child)
