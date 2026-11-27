import typing

from anystore.types import Uri
from followthemoney import EntityProxy
from rigour.mime import normalize_extension, normalize_mimetype

from ingestors.settings import Settings

if typing.TYPE_CHECKING:
    from ingestors.manager import Manager


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
