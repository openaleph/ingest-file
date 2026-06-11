import os
from unittest import mock

from ingestors.manager import Manager
from ingestors.tasks import app
from tests.support import TEST_DATASET, TestCase


class ManagerTest(TestCase):
    # support.TestCase replaces emit_entity on self.manager with a test stub,
    # so these tests build their own Manager to exercise the real method.

    def make_manager(self):
        return Manager(app, TEST_DATASET, {"namespace": "test"})

    def emit(self, manager):
        entity = manager.make_entity("PlainText")
        entity.make_id("manager-dehydrate-test")
        entity.add("contentHash", "deadbeef" * 5)
        entity.add("bodyText", "full payload")
        manager.emit_entity(entity)
        emitted = manager.get_emitted()
        manager.close()
        self.assertEqual(len(emitted), 1)
        return emitted[0]

    def test_emit_entity_dehydrates_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("OPENALEPH_PROCRASTINATE_DEHYDRATE_ENTITIES", None)
            manager = self.make_manager()
            self.assertTrue(manager.settings.procrastinate_dehydrate_entities)
            entity = self.emit(manager)
        self.assertEqual(entity.get("contentHash"), ["deadbeef" * 5])
        self.assertEqual(entity.get("bodyText"), [])

    def test_emit_entity_honors_openaleph_dehydrate_env_var(self):
        # The documented OPENALEPH_PROCRASTINATE_DEHYDRATE_ENTITIES variable
        # must reach the Manager settings even though the Settings subclass
        # remaps unaliased inherited fields to the `ingestors_` env prefix.
        env = {"OPENALEPH_PROCRASTINATE_DEHYDRATE_ENTITIES": "false"}
        with mock.patch.dict(os.environ, env):
            manager = self.make_manager()
            self.assertFalse(manager.settings.procrastinate_dehydrate_entities)
            entity = self.emit(manager)
        self.assertEqual(entity.get("bodyText"), ["full payload"])
        self.assertEqual(entity.get("contentHash"), ["deadbeef" * 5])
