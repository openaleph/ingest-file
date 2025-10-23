from __future__ import absolute_import

import os
import shutil
import types
import unittest
from tempfile import mkdtemp

from followthemoney import StatementEntity
from ftmq.store.fragments import get_fragments
from openaleph_procrastinate.util import make_checksum_entity
from procrastinate.testing import InMemoryConnector
from servicelayer import settings as sls
from servicelayer.archive.util import ensure_path
from servicelayer.tags import Tags

from ingestors.manager import OP_INGEST, Manager, get_archive
from ingestors.tasks import app

TEST_DATASET = "test"


def emit_entity(self, entity, fragment=None):
    self.entities.append(entity)
    self.writer.put(entity.to_dict(), fragment=fragment)
    with self.emitted.writer() as bulk:
        bulk.add_entity(make_checksum_entity(entity, StatementEntity, quiet=True))


class TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = mkdtemp()
        # clear cached func calls
        get_archive.cache_clear()
        get_fragments.cache_clear()
        # Force tests to use fake configuration
        self.assertIsInstance(app.connector, InMemoryConnector)
        sls.REDIS_URL = None
        sls.ARCHIVE_TYPE = "file"
        sls.ARCHIVE_PATH = self.tmp_dir
        os.environ["FTM_STORE_URI"] = f"sqlite:///{self.tmp_dir}/ftm.store"
        sls.TAGS_DATABASE_URI = os.environ["FTM_STORE_URI"]
        Tags("ingest_cache").delete()
        self.manager = Manager(app, TEST_DATASET, {"namespace": "test"})
        self.manager.emit_entity = types.MethodType(emit_entity, self.manager)
        self.manager.entities = []
        self.dataset = self.manager.db

    def fixture(self, fixture_path):
        """Returns a fixture path and a dummy entity"""
        # clear out entities
        self.manager.db.delete()
        self.manager.entities = []
        cur_path = ensure_path(__file__).parent
        cur_path = cur_path.joinpath("fixtures")
        path = cur_path.joinpath(fixture_path)
        entity = self.manager.make_entity("Document")
        if not path.exists():
            raise RuntimeError(path)
        if path.is_file():
            checksum = self.manager.store(path)
            entity.make_id(path.name, checksum)
            entity.set("contentHash", checksum)
            entity.set("fileSize", path.stat().st_size)
            entity.set("fileName", path.name)
        else:
            entity.make_id(fixture_path)
        return path, entity

    def get_emitted(self, schema=None):
        entities = list(self.manager.db.iterate())
        if schema is not None:
            entities = [e for e in entities if e.schema.is_a(schema)]
        return entities

    def get_emitted_by_id(self, id):
        return self.manager.db.get(id)

    def assertSuccess(self, entity):
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)

    def tearDown(self) -> None:
        # clean up processing queue
        self.manager.app.run_worker(queues=[OP_INGEST], wait=False)
        # remove tmp dir
        shutil.rmtree(self.tmp_dir)
