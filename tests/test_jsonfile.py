from tests.support import TestCase


class JsonFileIngestorTest(TestCase):
    def test_match(self):
        fixture_path, entity = self.fixture("example_2.json")
        self.manager.ingest(fixture_path, entity)
        entity = list(self.get_emitted())[0]
        assert "Golden State Warriros" in entity.get("indexText")
        # 5.3.1 we don't filter out "numeric only" fragments anymore
        assert "10" in entity.get("indexText")
