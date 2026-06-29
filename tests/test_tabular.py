# -*- coding: utf-8 -*-
from ingestors.exc import ENCRYPTED_MSG
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
        self.assertEqual(int(table.first("rowCount")), 3)
        self.assertIn("Mihai Viteazul", "".join(table.get("indexText")))

    def test_xlsx_with_wrong_extension(self):
        # Regression test: openpyxl refuses to open a workbook when handed a
        # path whose extension is not one of .xlsx/.xlsm/.xltx/.xltm. Files can
        # reach the ingestor without a correct extension (e.g. extracted from an
        # archive or named by content hash), so the ingestor passes openpyxl a
        # file handle, which bypasses that check. The fixture is a valid .xlsx
        # workbook deliberately named ".bin".
        fixture_path, entity = self.fixture("disguised_xlsx.bin")
        # Pin the detected type so ingestor selection does not depend on the
        # local libmagic database; the behaviour under test is purely the
        # ".bin" path extension handed to openpyxl.
        entity.set(
            "mimeType",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Workbook")
        tables = self.get_emitted("Table")
        self.assertEqual(len(tables), 2)

    def test_unicode_xls(self):
        fixture_path, entity = self.fixture("rom.xls")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Workbook")
        tables = self.get_emitted("Table")
        tables = [t.first("title") for t in tables]
        self.assertIn("Лист1", tables)

    def test_unicode_ods(self):
        fixture_path, entity = self.fixture("rom.ods")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        tables = self.get_emitted("Table")
        tables = [t.first("title") for t in tables]
        self.assertIn("Лист1", tables)
        self.assertEqual(entity.schema.name, "Workbook")

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
