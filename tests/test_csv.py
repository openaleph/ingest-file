# -*- coding: utf-8 -*-
from tests.support import TestCase


class CSVIngestorTest(TestCase):
    def test_simple_csv(self):
        fixture_path, entity = self.fixture("countries.csv")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertTrue(entity.has("csvHash"))
        self.assertEqual(int(entity.first("rowCount")), 256)

    def test_inconsistent_columns_csv(self):
        fixture_path, entity = self.fixture("inconsistent_columns.csv")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertTrue(entity.has("csvHash"))
        self.assertEqual(entity.first("columns"), '["Column 1"]')

    def test_nonutf_csv(self):
        fixture_path, entity = self.fixture("countries_nonutf.csv")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertTrue(entity.has("csvHash"))
        self.assertEqual(int(entity.first("rowCount")), 21)
