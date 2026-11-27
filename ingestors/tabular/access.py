import csv
import io
import logging
import os
import subprocess
from collections import OrderedDict

from followthemoney import model

from ingestors.exc import ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.support.shell import ShellSupport, forward_output, log_output
from ingestors.support.table import TableSupport

log = logging.getLogger(__name__)


class AccessIngestor(Ingestor, TableSupport, ShellSupport):
    MIME_TYPES = [
        "application/msaccess",
        "application/x-msaccess",
        "application/vnd.msaccess",
        "application/vnd.ms-access",
        "application/mdb",
        "application/x-mdb",
    ]
    EXTENSIONS = ["mdb"]
    SCORE = 8

    def get_tables(self, local_path):
        mdb_tables = self.find_command("mdb-tables")
        if mdb_tables is None:
            raise RuntimeError("mdb-tools is not available")
        try:
            result = subprocess.run(
                [mdb_tables, local_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError as cpe:
            log_output(cpe.stderr, "mdb-tables", log)
            log.warning("Failed to open MDB: %s", cpe)
            raise ProcessingException("Failed to extract Access DB.") from cpe
        log_output(result.stderr, "mdb-tables", log)
        return [
            t.strip().decode("utf-8")
            for t in result.stdout.split(b" ")
            if len(t.strip())
        ]

    def generate_rows(self, file_path, table_name):
        mdb_export = self.find_command("mdb-export")
        if mdb_export is None:
            raise RuntimeError("mdb-tools is not available")
        args = [mdb_export, "-b", "strip", file_path, table_name]
        with subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as proc:
            if proc.stdout is None:
                raise ProcessingException("Failed to create subprocess stdout pipe")
            # its rows are read here, so only what it complains about is logged
            forward_output(proc.stderr, "mdb-export", log)
            output = io.TextIOWrapper(proc.stdout, newline=os.linesep)
            headers = None
            for row in csv.reader((line for line in output), delimiter=","):
                if headers is None:
                    headers = row
                    continue
                yield OrderedDict(zip(headers, row))

    def ingest(self, file_path, entity):
        entity.schema = model.get("Workbook")
        for table_name in self.get_tables(file_path):
            table = self.manager.make_entity("Table", parent=entity)
            table.make_id(entity.id, table_name)
            table.set("title", table_name)
            # Emit a partial table fragment with parent reference and name
            # early, so that we don't have orphan fragments in case of an error
            # in the middle of processing.
            # See https://github.com/alephdata/ingest-file/issues/171
            self.manager.emit_entity(table, fragment="initial")
            rows = self.generate_rows(file_path, table_name)
            self.emit_row_dicts(table, rows)
            self.manager.emit_entity(table)
