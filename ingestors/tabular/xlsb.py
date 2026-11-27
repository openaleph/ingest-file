from anystore.types import Uri
from followthemoney import EntityProxy, model

from ingestors.ingestor import Ingestor
from ingestors.support.ooxml import OOXMLSupport
from ingestors.support.table import CalamineSpreadsheetSupport
from ingestors.support.tika import TikaSupport


class ExcelBinaryIngestor(
    Ingestor, CalamineSpreadsheetSupport, OOXMLSupport, TikaSupport
):
    MIME_TYPES = [
        "application/vnd.ms-excel.sheet.binary.macroenabled.12",
    ]
    EXTENSIONS = ["xlsb"]
    SCORE = 10

    def ingest(self, file_path: Uri, entity: EntityProxy):
        entity.schema = model["Workbook"]
        self.ooxml_extract_metadata(file_path, entity)
        self.calamine_extract_sheets(file_path, entity)
        self.ingest_embedded(file_path, parent=entity)
