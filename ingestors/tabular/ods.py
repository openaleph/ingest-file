from followthemoney import model

from ingestors.ingestor import Ingestor
from ingestors.support.opendoc import OpenDocumentSupport
from ingestors.support.table import CalamineSpreadsheetSupport
from ingestors.support.tika import TikaSupport


class OpenOfficeSpreadsheetIngestor(
    Ingestor, CalamineSpreadsheetSupport, OpenDocumentSupport, TikaSupport
):
    MIME_TYPES = [
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.spreadsheet-template",
    ]
    EXTENSIONS = ["ods", "ots"]
    SCORE = 7

    def ingest(self, file_path, entity):
        entity.schema = model.get("Workbook")
        self.parse_opendocument_metadata(file_path, entity)
        self.calamine_extract_sheets(file_path, entity)
        self.ingest_embedded(file_path, parent=entity)
