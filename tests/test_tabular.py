# -*- coding: utf-8 -*-
from unittest.mock import patch

from ingestors.exc import ENCRYPTED_MSG
from ingestors.ingestor import Ingestor
from tests.support import TestCase


class TabularIngestorTest(TestCase):
    def test_simple_xlsx(self):
        fixture_path, entity = self.fixture("file.xlsx")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Workbook")
        tables = self.get_emitted("Table")
        self.assertEqual(len(tables), 2)
        titles = [t.first("title") for t in tables]
        self.assertIn("Sheet1", titles)
        table = [t for t in tables if "1" in t.first("title")][0]
        self.assertTrue(table.has("csvHash"))
        self.assertEqual(int(table.first("rowCount")), 2)
        self.assertIn("Mihai Viteazul", "".join(table.get("indexText")))

    def test_xlsx_with_wrong_extension(self):
        # Regression test: openpyxl refuses to open a workbook when handed a
        # path whose extension is not one of .xlsx/.xlsm/.xltx/.xltm. Files can
        # reach the ingestor without a correct extension (e.g. extracted from an
        # archive or named by content hash), so the ingestor passes openpyxl a
        # file handle, which bypasses that check. The fixture is a valid .xlsx
        # workbook deliberately named ".bin".
        fixture_path, entity = self.fixture("disguised_xlsx.bin")
        # The auction sniffs the file itself and ignores any declared type, so
        # selection here comes from libmagic recognising the workbook despite
        # the ".bin" name. The behaviour under test is the ".bin" path
        # extension handed to openpyxl.
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Workbook")
        tables = self.get_emitted("Table")
        self.assertEqual(len(tables), 2)

    def test_xlsx_metadata(self):
        fixture_path, entity = self.fixture("metadata.xlsx")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.first("title"), "Spreadsheet with Metadata")
        self.assertTrue(entity.first("authoredAt").startswith("2026-06-23"))
        self.assertTrue(entity.first("modifiedAt").startswith("2026-06-23"))

    def test_unicode_xls(self):
        fixture_path, entity = self.fixture("rom.xls")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Workbook")
        tables = self.get_emitted("Table")
        tables = [t.first("title") for t in tables]
        self.assertIn("Лист1", tables)
        # OLE document metadata must survive regardless of extraction backend
        self.assertIn("Microsoft Office User", entity.get("author"))
        self.assertIn("Microsoft Macintosh Excel", entity.get("generator"))
        self.assertTrue(
            any(v.startswith("2011-06-09") for v in entity.get("authoredAt"))
        )
        self.assertTrue(
            any(v.startswith("2017-06-08") for v in entity.get("modifiedAt"))
        )

    def test_unicode_ods(self):
        fixture_path, entity = self.fixture("rom.ods")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        tables = self.get_emitted("Table")
        titles = [t.first("title") for t in tables]
        self.assertIn("Лист1", titles)
        self.assertEqual(entity.schema.name, "Workbook")
        # ODF document metadata must survive regardless of extraction backend
        self.assertIn("Microsoft Office User", entity.get("author"))
        self.assertTrue(entity.first("generator").startswith("LibreOffice"))
        self.assertTrue(
            any(v.startswith("2011-06-09") for v in entity.get("authoredAt"))
        )
        table = [t for t in tables if t.first("title") == "Лист1"][0]
        self.assertTrue(table.has("csvHash"))
        self.assertEqual(int(table.first("rowCount")), 338)
        self.assertIn("Tip procedură", "".join(table.get("indexText")))

    def test_password_protected_xlsx(self):
        fixture_path, entity = self.fixture("password_protected.xlsx")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(len(self.get_emitted()), 1)
        err = self.manager.entities[0].first("processingError")
        self.assertIn(ENCRYPTED_MSG, err)
        status = self.manager.entities[0].first("processingStatus")
        self.assertEqual("failure", status)

    def test_password_protected_xls(self):
        fixture_path, entity = self.fixture("password_protected.xls")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(len(self.get_emitted()), 1)
        err = self.manager.entities[0].first("processingError")
        self.assertIn(ENCRYPTED_MSG, err)
        status = self.manager.entities[0].first("processingStatus")
        self.assertEqual("failure", status)


class CalamineTabularIngestorTest(TabularIngestorTest):
    """Re-run the full tabular suite with the calamine extraction backend
    enabled, so both code paths are covered in a single pytest run and any
    divergence between them (rows, metadata, error handling) fails loudly."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(Ingestor.settings, "calamine", True)
        patcher.start()
        self.addCleanup(patcher.stop)
