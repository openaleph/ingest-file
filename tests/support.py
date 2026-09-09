from __future__ import absolute_import

import os
import shutil
import types
import unittest
from tempfile import mkdtemp

from followthemoney import StatementEntity
from ftm_lakehouse.repository.factories import clear_caches as clear_lakehouse_caches
from normality import stringify
from openaleph_procrastinate.repository import get_archive, get_entity_store
from openaleph_procrastinate.util import make_file_entity
from procrastinate.testing import InMemoryConnector
from servicelayer import settings as sls
from servicelayer.archive.util import ensure_path
from servicelayer.tags import Tags

from ingestors.manager import Manager
from ingestors.settings import OP_INGEST, Settings
from ingestors.tasks import app

TEST_DATASET = "test"


def emit_entity(self, entity, fragment=None, origin=OP_INGEST):
    """Stand-in for `Manager.emit_entity` that records what was emitted and,
    unlike the real one, leaves the entity ids un-namespaced so the tests can
    look them up by the id they made. The fragment is coerced the same way the
    manager does it, the backends take it as-is."""
    self.entities.append(entity)
    self.writer.put(entity, stringify(fragment), origin=origin)
    with self.emitted.writer() as bulk:
        bulk.add_entity(make_file_entity(entity, StatementEntity, quiet=True))


class TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = mkdtemp()
        # the lakehouse backend takes its location from `LAKEHOUSE_URI` (the
        # repositories no longer accept an explicit uri), so point it at an
        # isolated directory per test. `TEST_LAKEHOUSE_URI` keeps the escape
        # hatch for running the suite against a shared location.
        os.environ["LAKEHOUSE_URI"] = (
            os.environ.get("TEST_LAKEHOUSE_URI") or self.tmp_dir
        )
        # clear cached func calls, they are keyed on the dataset (resp. the
        # dataset uri) only and would otherwise hand back stores pointing at a
        # previous test's tmp dir. `get_entity_store` is deliberately uncached
        # upstream, so there is nothing to clear for it.
        get_archive.cache_clear()
        clear_lakehouse_caches()
        # Force tests to use fake configuration
        self.assertIsInstance(app.connector, InMemoryConnector)
        # `App.run_worker` registers a notification listener bound to the loop
        # that `asyncio.run` closes on its way out. The connector is module
        # level, so without a reset the next test would dispatch onto that dead
        # loop and fail with "Event loop is closed". Also isolates the job table.
        app.connector.reset()
        sls.REDIS_URL = None
        sls.ARCHIVE_TYPE = "file"
        sls.ARCHIVE_PATH = self.tmp_dir
        os.environ["FTM_STORE_URI"] = f"sqlite:///{self.tmp_dir}/ftm.store"
        sls.TAGS_DATABASE_URI = os.environ["FTM_STORE_URI"]
        # `CacheSupport` resolves the tags db from the ingestors settings, not
        # from `sls`, so clearing the default would leave the real cache (and
        # e.g. the pdf conversion hashes in it) in place between tests
        Tags("ingest_cache", uri=Settings().tags_database_uri).delete()
        self.manager = Manager(app, TEST_DATASET, {"namespace": "test"})
        self.manager.emit_entity = types.MethodType(emit_entity, self.manager)
        self.manager.entities = []
        self.dataset = get_entity_store(self.manager.dataset)
        self.dataset.delete()

    def fixture(self, fixture_path):
        """Returns a fixture path and a dummy entity"""
        # clear out entities
        self.dataset.delete()
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
        entities = list(sorted(self.dataset.iterate(), key=lambda e: e.id))
        # test dehydrated emitted:
        emitted = self.manager.get_emitted()
        try:
            assert {e.id for e in entities} == {e.id for e in emitted}
        except AssertionError:
            # special case of directory test: the child file is emitted in
            # another manager instance, but the Folder entity is there:
            assert len({e.id for e in entities} & {e.id for e in emitted}) == 1
        if schema is not None:
            entities = [e for e in entities if e.schema.is_a(schema)]
        return entities

    def get_emitted_by_id(self, id):
        return self.dataset.get(id)

    def assertSuccess(self, entity):
        self.assertEqual(entity.first("processingStatus"), self.manager.STATUS_SUCCESS)

    def tearDown(self) -> None:
        # clean up processing queue
        self.manager.app.run_worker(queues=[OP_INGEST], wait=False)
        # remove tmp dir
        shutil.rmtree(self.tmp_dir)
