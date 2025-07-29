from ingestors.misc.tika import TikaIngestor
from tests.support import TestCase


class TikaIngestorTest(TestCase):
    def test_match(self):
        fixture_path, entity = self.fixture("translate.po")
        assert self.manager.auction(fixture_path, entity) == TikaIngestor

    def test_ingest(self):
        fixture_path, entity = self.fixture("translate.po")
        self.manager.ingest(fixture_path, entity)
        entity = self.get_emitted()[0]
        assert entity.first("bodyText").startswith("# Copyright")
