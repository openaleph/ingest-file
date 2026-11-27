from anystore.types import Uri
from followthemoney import EntityProxy, model

from ingestors.ingestor import Ingestor
from ingestors.support.ole import OLESupport
from ingestors.support.table import CalamineSpreadsheetSupport
from ingestors.support.tika import TikaSupport


class ExcelIngestor(Ingestor, CalamineSpreadsheetSupport, OLESupport, TikaSupport):
    MIME_TYPES = [
        "application/excel",
        "application/x-excel",
        "application/vnd.ms-excel",
        "application/x-msexcel",
    ]
    EXTENSIONS = ["xls", "xlt", "xla"]
    SCORE = 7

    def ingest(self, file_path: Uri, entity: EntityProxy):
        entity.schema = model["Workbook"]
        self.extract_ole_metadata(file_path, entity)
        self.calamine_extract_sheets(file_path, entity)
        self.ingest_embedded(file_path, parent=entity)
