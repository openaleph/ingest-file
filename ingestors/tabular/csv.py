import csv
import io
import logging

from followthemoney import model

from ingestors.exc import ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.support.table import TableSupport

log = logging.getLogger(__name__)

# Increase CSV field size limit to handle large fields
csv.field_size_limit(10 * 1024 * 1024)  # 10MB limit


class CSVIngestor(Ingestor, TableSupport):
    """Decode and ingest a CSV file.

    This expects a properly formatted CSV file with a header in the first row.
    """

    MIME_TYPES = ["text/csv", "text/tsv", "text/tab-separated-values"]
    EXTENSIONS = ["csv", "tsv"]
    SCORE = 7

    def ingest(self, file_path, entity):
        entity.schema = model.get("Table")
        with io.open(file_path, "rb") as fh:
            encoding = self.detect_stream_encoding(fh)
            log.debug("Detected encoding [%r]: %s", entity, encoding)

        try:
            with io.open(file_path, "r", encoding=encoding, errors="replace") as fh:
                sample = fh.read(4096 * 10)
                fh.seek(0)
                dialect = csv.Sniffer().sniff(sample)
                log.debug("Detected CSV delimiter [%r]: %r", entity, dialect.delimiter)
                reader = csv.reader(fh, dialect=dialect)
                num_cols = len(next(reader, []))
                single_column = any(len(row) > num_cols for row in reader)
        except (Exception, csv.Error) as err:
            log.warning("CSV error: %s", err)
            raise ProcessingException("Invalid CSV: %s" % err) from err
        with io.open(file_path, "r", encoding=encoding, errors="replace") as fh:
            if single_column:
                log.warning("Ambiguous CSV delimiter: [%r]", entity)
                self.emit_row_tuples(entity, ([line.rstrip("\r\n")] for line in fh))
            else:
                self.emit_row_tuples(entity, csv.reader(fh, dialect=dialect))
