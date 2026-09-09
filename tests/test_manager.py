import os
import shutil
from unittest import mock

from servicelayer.archive.util import ensure_path

from ingestors.directory import DirectoryIngestor
from ingestors.email.olm import MIME as OPF_MESSAGE_MIME
from ingestors.email.olm import OutlookOLMMessageIngestor
from ingestors.manager import Manager
from ingestors.media.tiff import TIFFIngestor
from ingestors.settings import Settings
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
        if Settings().lakehouse:
            # the lakehouse backend takes entities from the job payload instead
            # of re-fetching them, so it forces dehydration off (see
            # `OpenAlephSettings.enforce_lakehouse_payloads`)
            self.skipTest("dehydration is disabled for the lakehouse backend")
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


class AuctionTest(TestCase):
    # Which ingestor wins decides the entity's schema, so it has to be a
    # function of the file alone. When it also depended on the mimeType a
    # producer had declared, the same file got `ImageIngestor` (schema `Image`)
    # or `TIFFIngestor` (schema `Pages`) depending on whether that claim
    # survived into the job payload, and a statement store that keeps both
    # emissions ends up holding an entity with no common schema.

    def disguised(self, fixture, file_name):
        """A fixture copied to a file name that lies about its content."""
        source = ensure_path(__file__).parent.joinpath("fixtures", fixture)
        target = ensure_path(self.tmp_dir).joinpath(file_name)
        shutil.copy(source, target)
        return target

    def auction(self, path, mime_type=None):
        entity = self.manager.make_entity("Document")
        entity.make_id(path.name)
        entity.add("fileName", path.name)
        if mime_type is not None:
            entity.add("mimeType", mime_type)
        return self.manager.auction(path, entity), entity

    def test_declared_mime_type_does_not_decide(self):
        # a TIFF that an e-mail header announced as a PNG
        path = self.disguised("hello_world_tiff.tif", "image003.png")
        for declared in (None, "image/png"):
            ingestor, entity = self.auction(path, declared)
            self.assertEqual(ingestor, TIFFIngestor)
            self.assertEqual(entity.get("mimeType"), ["image/tiff"])

    def test_routing_mime_type_is_kept(self):
        # OLM message parts are plain xml and carry no file name, so the marker
        # `OutlookOLMArchiveIngestor` puts on them is the only thing that can
        # route them to the right ingestor
        path = ensure_path(self.tmp_dir).joinpath("message_0001")
        path.write_bytes(b"<?xml version='1.0'?><emails><email /></emails>")
        entity = self.manager.make_entity("Document")
        entity.make_id(path.name)
        entity.add("mimeType", OPF_MESSAGE_MIME)
        ingestor = self.manager.auction(path, entity)
        self.assertEqual(ingestor, OutlookOLMMessageIngestor)
        self.assertEqual(entity.get("mimeType"), [OPF_MESSAGE_MIME])

    def test_directory_is_matched_before_sniffing(self):
        # `MAGIC.from_file` cannot read a directory, so the check has to come
        # first – including for a folder that already carries a mimeType
        path = ensure_path(__file__).parent.joinpath("fixtures", "testdir")
        entity = self.manager.make_entity("Folder")
        entity.make_id("testdir")
        entity.add("mimeType", DirectoryIngestor.MIME_TYPE)
        self.assertEqual(self.manager.auction(path, entity), DirectoryIngestor)
