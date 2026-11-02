from anystore.types import Uri
from followthemoney import EntityProxy, model

from ingestors.ingestor import Ingestor
from ingestors.support.ooxml import OOXMLSupport
from ingestors.support.table import CalamineSpreadsheetSupport
from ingestors.support.tika import TikaSupport


class ExcelXMLIngestor(Ingestor, CalamineSpreadsheetSupport, OOXMLSupport, TikaSupport):
    MIME_TYPES = [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # noqa: B950
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template",  # noqa: B950
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-excel.template.macroenabled.12",
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    ]
    EXTENSIONS = ["xlsx", "xlsm", "xltx", "xltm"]
    SCORE = 7

    def ingest(self, file_path: Uri, entity: EntityProxy):
        entity.schema = model["Workbook"]
        self.ooxml_extract_metadata(file_path, entity)
        self.calamine_extract_sheets(file_path, entity)
        self.ingest_embedded(file_path, parent=entity)

    @classmethod
    def match(cls, file_path, entity):
        score = super(ExcelXMLIngestor, cls).match(file_path, entity)
        if score > 0 and not cls.inspect_ooxml_manifest(file_path):
            return -1
        return score
