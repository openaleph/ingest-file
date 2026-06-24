import csv
import logging
from collections import OrderedDict

from followthemoney import EntityProxy
from followthemoney.types import registry
from followthemoney.util import sanitize_text
from kreuzberg import ExtractionResult
from rigour.mime.types import CSV

from ingestors.exc import ProcessingException
from ingestors.manager import Manager
from ingestors.support.encoding import EncodingSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)


class TableSupport(EncodingSupport, TempFileSupport):
    """Handle creating rows from an ingestor."""

    manager: Manager

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
                    log.info(
                        "Table emit [%s]: %s cell values from %s rows ...",
                        table,
                        len(cell_values),
                        row_count,
                    )
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


class KreuzbergSpreadsheetSupport(TableSupport):
    """Kreuzberg implementation for xls[x] spreadsheets"""

    def kreuzberg_extract_sheets(
        self, result: ExtractionResult, entity: EntityProxy
    ) -> None:
        sheet_names = result.metadata.get("sheet_names")
        if not sheet_names:
            log.warning(
                f"No sheets in Workbook `{entity.id}` ({entity.first('contentHash')})"
            )
            return
        # kreuzberg emits one table per non-empty sheet (empty sheets are
        # skipped), so the number of tables can be smaller than sheet_count.
        # Each table's `page_number` is the 1-based index of its source sheet,
        # which recovers the correct name regardless of any empty sheets.
        if not result.tables:
            log.warning(
                f"No tables extracted from Workbook `{entity.id}` "
                f"({entity.first('contentHash')})"
            )
        try:
            for position, sheet_table in enumerate(result.tables):
                index = sheet_table.page_number or position + 1
                name = (
                    sheet_names[index - 1]
                    if index <= len(sheet_names)
                    else f"Sheet {index}"
                )
                table = self.manager.make_entity("Table", parent=entity)
                table.make_id(entity.id, name)
                table.set("title", name)
                # Emit a partial table fragment with parent reference and
                # name early, so that we don't have orphan fragments in case
                # of an error in the middle of processing.
                # See https://github.com/alephdata/ingest-file/issues/171
                self.manager.emit_entity(table, fragment="initial")
                log.debug("Sheet: %s", name)
                self.emit_row_tuples(table, sheet_table.cells)
                if table.has("csvHash"):
                    self.manager.emit_entity(table)
        except Exception as err:
            raise ProcessingException("Cannot read Excel file: %s" % err) from err
