import csv
import logging
from itertools import chain

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

_MISSING = object()


class TableSupport(EncodingSupport, TempFileSupport):
    """Handle creating rows from an ingestor."""

    manager: Manager

    def _emit_value_rows(self, table, value_rows, headers):
        """Write rows of raw cell values (each aligned to ``headers``) to a CSV
        and emit table metadata.

        Shared core for the dict- and tuple-based entry points: it sanitises
        cells, skips fully-empty rows, streams chunked text fragments and sets
        the table properties, so both paths behave identically.
        """
        sanitize = sanitize_text
        csv_path = self.make_work_file(table.id)
        row_count = 0
        cell_values: set[str] = set()
        with open(csv_path, "w", encoding=self.DEFAULT_ENCODING) as fp:
            csv_writer = csv.writer(fp, dialect="unix")
            for raw in value_rows:
                values = [sanitize(v) or "" for v in raw]
                if not any(values):
                    continue
                csv_writer.writerow(values)
                cell_values.update(values)
                row_count += 1
                if row_count % 10000 == 0:
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
                log.info(
                    "Table emit [%s]: %s cell values from %s rows ...",
                    table,
                    len(cell_values),
                    row_count,
                )
            csv_hash = self.manager.store(csv_path, mime_type=CSV)
            table.set("csvHash", csv_hash)
        table.set("rowCount", row_count + 1)
        table.set("columns", registry.json.pack(headers))

    def emit_row_dicts(self, table, rows, headers=None):
        rows = iter(rows)
        if headers is None:
            # Derive headers from the first row's keys (as the previous in-loop
            # logic did), then replay that row through the shared core.
            first = next(rows, _MISSING)
            if first is _MISSING:
                return self._emit_value_rows(table, iter(()), None)
            headers = list(first.keys())
            rows = chain((first,), rows)
        value_rows = ([row.get(h) for h in headers] for row in rows)
        return self._emit_value_rows(table, value_rows, headers)

    def emit_row_tuples(self, table, rows):
        rows = iter(rows)
        first = next(rows, _MISSING)
        if first is _MISSING:
            return self._emit_value_rows(table, iter(()), None)
        width = len(first)
        headers = ["Column %s" % i for i in range(1, width + 1)]
        rows = chain((first,), rows)
        # Align each row to the first row's width: drop extra columns, pad short
        # rows with None — matching the previous OrderedDict/`.get` lookup.
        value_rows = (
            [row[i] if i < len(row) else None for i in range(width)] for row in rows
        )
        return self._emit_value_rows(table, value_rows, headers)


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
