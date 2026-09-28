import logging

from anystore.types import Uri
from followthemoney import EntityProxy, model

from ingestors.exc import ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.support.table import CalamineSpreadsheetSupport

log = logging.getLogger(__name__)


class ExcelBinaryIngestor(Ingestor, CalamineSpreadsheetSupport):
    MIME_TYPES = [
        "application/vnd.ms-excel.sheet.binary.macroenabled.12",
    ]
    EXTENSIONS = ["xlsb"]
    SCORE = 10

    def ingest(self, file_path: Uri, entity: EntityProxy):
        entity.schema = model["Workbook"]

        if not self.settings.calamine:
            raise ProcessingException("Calamine support required for xlsb files.")

        # TODO: Metadata extraction, needs specific parser

        return self.calamine_extract_sheets(file_path, entity)
