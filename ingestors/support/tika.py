import logging
from io import BytesIO
from pathlib import PosixPath
from typing import Any

import olefile
from followthemoney import EntityProxy
from normality import collapse_spaces, safe_filename
from oletools.oleobj import OleNativeStream
from tika import parser, unpack

from ingestors.exc import ProcessingException
from ingestors.support.cache import CacheSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)

OLE_MAGIC = b"\xd0\xcf\x11\xe0"
# https://www.loc.gov/preservation/digital/formats/fdd/fdd000392.shtml


def _unwrap_ole_package(data: bytes) -> tuple[str, bytes] | None:
    """Extract (filename, bytes) from an OLE Package (Ole10Native stream).
    Returns None if data is not an OLE container or has no Package stream.
    Spec: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-oleds/cc825ec3-f0ed-4023-97f6-13c323ac1172
    """  # noqa: B950
    if data[:4] != OLE_MAGIC:
        return None
    try:
        with olefile.OleFileIO(BytesIO(data)) as ole:
            ole10_streams = [
                e for e in ole.listdir() if e and e[-1] == "\x01Ole10Native"
            ]
            entry = ole10_streams[0] if ole10_streams else None
            if entry is None:
                return None
            raw = ole.openstream(entry).read()
        obj = OleNativeStream(raw)
        if not obj.filename or not obj.data:
            return None
        return obj.filename, obj.data
    except Exception as exc:
        log.warning("Failed to unpack OLE: %s", exc)
        return None


class TikaSupport(CacheSupport, TempFileSupport):
    def extract_tika(
        self, fh: BytesIO, cache_key: str | None = None
    ) -> dict[str, Any] | None:
        _cache_key = None
        if cache_key:
            _cache_key = self.cache_key("tika", cache_key)
            result = self.tags.get(_cache_key)
            if result is not None and result.get("status") == 200:
                log.info("Tika: cached result for checksum %s" % cache_key)
                return result

        result = parser.from_file(fh)
        if isinstance(result, dict):
            # tika-python doesn't raise on an error status, and with an empty
            # body (e.g. a 503 while the server restarts) the result looks like
            # a document without text – which must neither pass nor be cached
            status = result.get("status")
            if status != 200:
                raise ProcessingException(f"Tika server returned status {status}")
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
        log.info(f"Tika extracted {len(attachments.items())} attachments.")
        for name, data in attachments.items():
            log.debug(f"Analyzing attachment: {name}")
            if not data:
                log.error(f"Attachment {name} has no data")
                continue
            unwrapped = _unwrap_ole_package(data)
            if unwrapped is not None:
                name, data = unwrapped
                log.debug("Unwrapped OLE Package: %s", name)
            file_name = safe_filename(name, default="embedded")
            file_path = self.make_work_file(file_name)
            with open(file_path, "wb") as fh:
                fh.write(data)
            # do not assign mime_type, hope the ingestor deduces it correctly
            checksum = self.manager.store(file_path)
            file_path.unlink()
            child = self.manager.make_entity("Document", parent=parent)
            child.make_id(name, checksum)
            child.add("contentHash", checksum)
            child.add("fileName", name)
            log.info(
                f"Queuing {name} with content hash {checksum} and parent {parent.id}"
            )
            self.manager.queue_entity(child)
