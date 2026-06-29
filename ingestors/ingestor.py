import logging
import os
import tempfile
import typing

from anystore.types import Uri
from banal import ensure_list
from followthemoney import EntityProxy
from kreuzberg import (
    ExtractionConfig,
    ExtractionResult,
    extract_file_sync,
    get_extensions_for_mime,
)
from kreuzberg.exceptions import ParsingError
from rigour.mime import normalize_extension, normalize_mimetype

from ingestors.exc import ENCRYPTED_MSG, ProcessingException
from ingestors.settings import Settings
from ingestors.support.kreuzberg import map_iso_languages

if typing.TYPE_CHECKING:
    from ingestors.manager import Manager

log = logging.getLogger(__name__)


class Ingestor(object):
    """Generic ingestor class."""

    MIME_TYPES = []
    EXTENSIONS = []
    SCORE = 3
    settings = Settings()

    def __init__(self, manager: "Manager"):
        self.manager = manager

    def ingest(self, file_path: Uri, entity: EntityProxy):
        """The ingestor implementation. Should be overwritten.

        This method does not return anything.
        Use the extracted data on `entity`.
        """
        raise NotImplementedError()

    @classmethod
    def match(cls, file_path: Uri, entity: EntityProxy):
        mime_types = [normalize_mimetype(m, default=None) for m in cls.MIME_TYPES]
        mime_types = [m for m in mime_types if m is not None]
        for mime_type in entity.get("mimeType"):
            if mime_type in mime_types:
                return cls.SCORE

        extensions = [normalize_extension(e) for e in cls.EXTENSIONS]
        for file_name in entity.get("fileName"):
            extension = normalize_extension(file_name)
            if extension is not None and extension in extensions:
                return cls.SCORE

        return -1


class KreuzbergIngestor(Ingestor):
    """Kreuzberg (https://docs.kreuzberg.dev) implementation base class"""

    settings = Settings()
    extraction_config = ExtractionConfig()

    def kreuzberg_extract(
        self, file_path: Uri, entity: EntityProxy
    ) -> ExtractionResult:
        """Extract file via kreuzberg implementation"""
        log.info(f"Kreuzberg extract: [{repr(entity)}]: {self.__class__.__name__}")

        mtype = entity.first("mimeType")
        if mtype:
            mtype = normalize_mimetype(mtype)
        path = str(file_path)
        link = None
        # kreuzberg resolves the format from the path EXTENSION; mime_type is
        # only a hint. Files might reach us named by content hash (no
        # extension), which makes kreuzberg skip the documents metadata
        # (title/keywords/dates/...). Hand it a correctly-suffixed symlink so
        # extension and mime agree.
        exts = []
        if mtype:
            try:
                exts = get_extensions_for_mime(mtype)
            except RuntimeError:
                # kreuzberg has no extension mapping for this mime; nothing to
                # rename to, so fall through to the original path unchanged.
                pass
        if exts and normalize_extension(path) not in exts:
            link = os.path.join(tempfile.mkdtemp(), f"{entity.id}.{exts[0]}")
            os.symlink(os.path.abspath(path), link)
            path = link
        try:
            result = extract_file_sync(
                file_path=path, mime_type=mtype, config=self.extraction_config
            )
        except ParsingError as err:
            # kreuzberg raises a generic ParsingError for password-protected /
            # encrypted files (e.g. "Workbook is password protected", "PDF is
            # password-protected"); surface these as the shared encrypted error.
            message = str(err).lower()
            if "password" in message or "encrypted" in message:
                raise ProcessingException(ENCRYPTED_MSG) from err
            raise
        finally:
            if link:
                os.unlink(link)
                os.rmdir(os.path.dirname(link))
        self._patch_metadata(result, entity)
        return result

    def _patch_metadata(self, result: ExtractionResult, entity: EntityProxy):
        """Patch entity metadata from kreuzberg result"""
        entity.add("title", ensure_list(result.metadata.get("title")))
        # generator: the software that produced the file, named differently per
        # format (PDF: producer, OOXML: application, ODF: generator).
        entity.add("generator", ensure_list(result.metadata.get("producer")))
        entity.add("generator", ensure_list(result.metadata.get("generator")))
        application = result.metadata.get("application")
        version = result.metadata.get("application_version")
        if application and version:
            application = f"{application} {version}"
        entity.add("generator", ensure_list(application))
        entity.add("description", ensure_list(result.metadata.get("description")))
        entity.add("summary", ensure_list(result.metadata.get("summary")))
        entity.add("summary", ensure_list(result.metadata.get("subject")))
        entity.add("keywords", ensure_list(result.metadata.get("keywords")))
        entity.add("author", ensure_list(result.metadata.get("author")))
        entity.add("author", ensure_list(result.metadata.get("authors")))
        entity.add("author", ensure_list(result.metadata.get("created_by")))
        entity.add("author", ensure_list(result.metadata.get("modified_by")))
        entity.add("authoredAt", ensure_list(result.metadata.get("created_at")))
        entity.add("modifiedAt", ensure_list(result.metadata.get("modified_at")))
        entity.add("language", map_iso_languages(result.metadata.get("language")))
