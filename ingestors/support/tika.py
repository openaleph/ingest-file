import logging
from io import BytesIO
from typing import Any

from normality import collapse_spaces
from tika import parser

from ingestors.support.cache import CacheSupport

log = logging.getLogger(__name__)


class TikaSupport(CacheSupport):
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
