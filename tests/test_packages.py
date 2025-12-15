# -*- coding: utf-8 -*-
from pprint import pprint  # noqa

from tests.support import TestCase


class PackagesTest(TestCase):
    def test_zip(self):
        fixture_path, entity = self.fixture("test-documents.zip")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Package")

    def test_rar(self):
        fixture_path, entity = self.fixture("test-documents.rar")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Package")

    def test_tar(self):
        fixture_path, entity = self.fixture("test-documents.tar")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(entity.schema.name, "Package")

    def test_password_protected_7z(self):
        fixture_path, entity = self.fixture("500_pages_password.7z")
        self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_FAILURE)
        self.assertEqual(
            entity.get("processingError")[0],
            "Could not unpack the contents of this file. The document might be protected with a password. Try removing the password protection and re-uploading the documents.",
        )
