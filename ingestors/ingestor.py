import logging
import typing

from rigour.mime import normalize_extension, normalize_mimetype

if typing.TYPE_CHECKING:
    from ingestors.manager import Manager

log = logging.getLogger(__name__)


class Ingestor(object):
    """Generic ingestor class."""

    MIME_TYPES = []
    EXTENSIONS = []
    SCORE = 3

    def __init__(self, manager: "Manager"):
        self.manager = manager

    def ingest(self, file_path, entity):
        """The ingestor implementation. Should be overwritten.

        This method does not return anything.
        Use the extracted data on `entity`.
        """
        raise NotImplementedError()

    @classmethod
    def match(cls, file_path, entity):
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
