import logging
import zipfile

from odf.opendocument import load

from ingestors.exc import ProcessingException
from ingestors.support.timestamp import TimestampSupport
from ingestors.support.xml import XMLSupport

log = logging.getLogger(__name__)


class OpenDocumentSupport(TimestampSupport, XMLSupport):
    """Provides helpers for Libre/Open Office tools."""

    META_FILE = "meta.xml"
    DC_NS = "{http://purl.org/dc/elements/1.1/}"
    META_NS = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"

    def parse_opendocument_metadata(self, file_path, entity):
        """Extract document metadata by reading only meta.xml, skipping the
        (potentially huge) document content that parse_opendocument loads."""
        try:
            with zipfile.ZipFile(file_path) as zf:
                with zf.open(self.META_FILE, "r") as xml:
                    doc = self.parse_xml_path(xml)
        except (KeyError, zipfile.BadZipFile, OSError, ProcessingException):
            log.warning("Cannot read OpenDocument metadata: %s", file_path)
            return

        def get(ns, name):
            return doc.findtext(".//%s%s" % (ns, name))

        entity.add("title", get(self.DC_NS, "title"))
        entity.add("summary", get(self.DC_NS, "description"))
        entity.add("author", get(self.DC_NS, "creator"))
        entity.add("date", self.parse_timestamp(get(self.DC_NS, "date")))
        creation_date = get(self.META_NS, "creation-date")
        entity.add("authoredAt", self.parse_timestamp(creation_date))
        entity.add("generator", get(self.META_NS, "generator"))

    def parse_opendocument(self, file_path, entity):
        try:
            doc = load(file_path)
        except Exception as exc:
            raise ProcessingException("Cannot open document.") from exc

        for child in doc.meta.childNodes:
            value = str(child)
            if child.tagName == "dc:title":
                entity.add("title", value)
            if child.tagName == "dc:description":
                entity.add("summary", value)
            if child.tagName == "dc:creator":
                entity.add("author", value)
            if child.tagName == "dc:date":
                entity.add("date", self.parse_timestamp(value))
            if child.tagName == "meta:creation-date":
                entity.add("authoredAt", self.parse_timestamp(value))
            if child.tagName == "meta:generator":
                entity.add("generator", value)

        return doc
