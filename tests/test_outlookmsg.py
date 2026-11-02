# -*- coding: utf-8 -*-
from pprint import pprint  # noqa

from tests.support import TestCase


class OutlookMsgTest(TestCase):
    def test_match(self):
        fixture_path, entity = self.fixture("piste.msg")
        self.manager.ingest(fixture_path, entity)

        self.assertEqual(entity.first("subject"), "Ab auf die Piste!")
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)

    def test_broken_property_stream(self):
        # One property stream msglite cannot parse (an unknown property type
        # makes create_prop return None) used to raise out of the ingestor and
        # fail the job. The rest of the message is still readable.
        fixture_path, entity = self.fixture("broken_props.msg")
        self.manager.ingest(fixture_path, entity)

        self.assertEqual(entity.first("subject"), "Ab auf die Piste!")
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
