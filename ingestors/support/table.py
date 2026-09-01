import csv
import logging
from itertools import chain

from anystore.types import Uri
from followthemoney import EntityProxy
from followthemoney.types import registry
from followthemoney.util import sanitize_text
from python_calamine import CalamineError, CalamineWorkbook, PasswordError
from rigour.mime.types import CSV

from ingestors.exc import EMPTY_SHEET_MSG, ENCRYPTED_MSG, ProcessingException
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
        table.set("rowCount", row_count)
        table.set("columns", registry.json.pack(headers))
        return row_count

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


class CalamineSpreadsheetSupport(TableSupport):
    """Spreadsheet extraction via python-calamine, a binding to the Rust
    `calamine` crate. Reads xls, xlsx and ods with content-based format
    detection, orders of magnitude faster than the pure-Python parsers.
    It reads cell data only; document metadata (author, dates, generator)
    must be extracted natively by the calling ingestor."""

    def calamine_generate_rows(self, sheet):
        # start is None for empty sheets, where iter_rows() panics
        # (python-calamine 0.7.0)
        if sheet.start is None:
            return
        # iter_rows() is lazy but trims leading empty columns; left-pad to
        # keep absolute column positions, matching the native
        # openpyxl/xlrd/odfpy behaviour.
        padding = [None] * sheet.start[1]
        for row in sheet.iter_rows():
            yield padding + list(row) if padding else row

    def calamine_extract_sheets(self, file_path: Uri, entity: EntityProxy) -> None:
        log.info(f"Calamine extract: [{repr(entity)}]: {self.__class__.__name__}")
        try:
            workbook = CalamineWorkbook.from_path(str(file_path))
        except PasswordError as err:
            raise ProcessingException(ENCRYPTED_MSG) from err
        except CalamineError as err:
            raise ProcessingException("Invalid workbook: %s" % err) from err
        try:
            for name in workbook.sheet_names:
                sheet = workbook.get_sheet_by_name(name)
                table = self.manager.make_entity("Table", parent=entity)
                table.make_id(entity.id, name)
                table.set("title", name)
                # Emit a partial table fragment with parent reference and
                # name early, so that we don't have orphan fragments in case
                # of an error in the middle of processing.
                # See https://github.com/alephdata/ingest-file/issues/171
                self.manager.emit_entity(table, fragment="initial")
                log.debug("Sheet: %s", name)
                row_count = self.emit_row_tuples(
                    table, self.calamine_generate_rows(sheet)
                )
                if row_count == 0:
                    table.set("processingError", EMPTY_SHEET_MSG)
                    table.set("processingStatus", self.manager.STATUS_FAILURE)
                self.manager.emit_entity(table)
        except CalamineError as err:
            raise ProcessingException("Cannot read workbook: %s" % err) from err
