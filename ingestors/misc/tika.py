from typing import Any

from followthemoney import EntityProxy, model
from rigour.mime import normalize_mimetype

from ingestors.exc import ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.support.tika import TikaSupport


def extract_mimetype(result: dict[str, Any]) -> str | None:
    mime = result.get("Content-Type")
    if mime and ";" in mime:
        return normalize_mimetype(mime.split(";")[0])
    return normalize_mimetype(mime)


class TikaIngestor(Ingestor, TikaSupport):
    SCORE = 1

    def ingest(self, file_path: str, entity: EntityProxy):
        with open(file_path, "rb") as fh:
            try:
                result = self.extract_tika(fh, cache_key=entity.first("contentHash"))
                if result:
                    patch = model.make_entity(entity.schema)
                    patch.id = entity.id
                    patch.add("mimeType", extract_mimetype(result))
                    patch.add("bodyText", result["content"])
                    self.manager.emit_entity(patch, fragment="tika")
            except Exception as exc:
                raise ProcessingException("Cannot extract tika text: %s" % exc) from exc
