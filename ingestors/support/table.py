import csv
import logging
from collections import OrderedDict

from followthemoney.types import registry
from followthemoney.util import sanitize_text
from rigour.mime.types import CSV

from ingestors.support.encoding import EncodingSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)


class TableSupport(EncodingSupport, TempFileSupport):
    """Handle creating rows from an ingestor."""

    def emit_row_dicts(self, table, rows, headers=None):
        csv_path = self.make_work_file(table.id)
        row_count = 0
        cell_values: set[str] = set()
        with open(csv_path, "w", encoding=self.DEFAULT_ENCODING) as fp:
            csv_writer = csv.writer(fp, dialect="unix")
            for row in rows:
                if headers is None:
                    headers = list(row.keys())
                values = [sanitize_text(row.get(h)) or "" for h in headers]
                length = sum((len(v) for v in values if v))
                if length == 0:
                    continue
                csv_writer.writerow(values)
                cell_values.update(values)
                row_count += 1
                if row_count > 0 and row_count % 10000 == 0:
                    log.info("Table emit [%s]: %s...", table, row_count)
                    self.manager.emit_text_fragment(table, list(cell_values), row_count)
                    cell_values = set()
        if row_count > 0:
            if len(cell_values):
                self.manager.emit_text_fragment(table, list(cell_values), row_count)
            csv_hash = self.manager.store(csv_path, mime_type=CSV)
            table.set("csvHash", csv_hash)
        table.set("rowCount", row_count + 1)
        table.set("columns", registry.json.pack(headers))

    def wrap_row_tuples(self, rows):
        for row in rows:
            headers = ["Column %s" % i for i in range(1, len(row) + 1)]
            yield OrderedDict(zip(headers, row))

    def emit_row_tuples(self, table, rows):
        return self.emit_row_dicts(table, self.wrap_row_tuples(rows))
