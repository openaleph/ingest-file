from unittest import mock

from ingestors.misc.tika import TikaIngestor
from tests.support import TestCase

# what tika-python returns for an error status with an empty body, e.g. a 503
# while the server restarts its forked JVM
FAILED = {"status": 503, "metadata": None, "content": None}


class TikaIngestorTest(TestCase):
    def test_match(self):
        fixture_path, entity = self.fixture("translate.po")
        assert self.manager.auction(fixture_path, entity) == TikaIngestor

    def test_ingest(self):
        fixture_path, entity = self.fixture("translate.po")
        self.manager.ingest(fixture_path, entity)
        entity = self.get_emitted()[0]
        assert entity.first("bodyText").startswith("# Copyright")

    def test_error_status(self):
        """A failed parse fails the file, and is not cached: the next ingest of
        the same file parses it again."""
        fixture_path, entity = self.fixture("translate.po")
        with mock.patch("ingestors.support.tika.parser.from_file", return_value=FAILED):
            self.manager.ingest(fixture_path, entity)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_FAILURE)
        self.assertIn("503", entity.first("processingError"))

        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        entity = self.get_emitted()[0]
        assert entity.first("bodyText").startswith("# Copyright")

    def test_cached_error_status(self):
        """Failed parses cached by earlier versions are parsed again."""
        fixture_path, entity = self.fixture("translate.po")
        ingestor = TikaIngestor(self.manager)
        ingestor.tags.set(
            ingestor.cache_key("tika", entity.first("contentHash")), FAILED
        )
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        entity = self.get_emitted()[0]
        assert entity.first("bodyText").startswith("# Copyright")
