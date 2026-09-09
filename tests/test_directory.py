from ingestors.settings import OP_INGEST
from tests.support import TestCase


class DirectoryTest(TestCase):
    def test_normal_directory(self):
        fixture_path, entity = self.fixture("testdir")
        self.manager.ingest(fixture_path, entity)
        self.manager.app.run_worker(queues=[OP_INGEST], wait=False)
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)
        self.assertEqual(len(self.get_emitted()), 2)
        self.assertEqual(entity.schema.name, "Folder")
