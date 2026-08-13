from pathlib import Path
from tempfile import mkdtemp

from followthemoney.namespace import Namespace

from ingestors.settings import Settings
from ingestors.tasks import ingest_path
from tests.support import TEST_DATASET, TestCase

FOREIGN_ID = "my_foreign_id"
# `dataset_name_check` requires slugified, underscore separated names
INVALID_FOREIGN_IDS = ["my-foreign-id", "My_Foreign_Id", "my foreign id", "my.foreign"]


class IngestPathTest(TestCase):
    """`ingest_path` is only reached through the cli, so it needs its own
    coverage: a wrong signature or a missing `namespace` context key raises
    before any ingestor runs."""

    def make_tree(self) -> Path:
        """A nested directory: `crawl` emits the sub folder right away and
        queues the file inside it for a worker."""
        self.dataset.delete()
        root = Path(mkdtemp(dir=self.tmp_dir))
        sub = root.joinpath("sub")
        sub.mkdir()
        sub.joinpath("hello.txt").write_text("hello")
        return root

    def assertNamespace(self, entities, name: str) -> None:
        # the lakehouse backend strips namespace signatures on write
        if Settings().lakehouse:
            return
        self.assertTrue(all(Namespace(name).verify(e.id) for e in entities))
        if name != TEST_DATASET:
            self.assertFalse(
                any(Namespace(TEST_DATASET).verify(e.id) for e in entities)
            )

    def test_ingest_path(self):
        ingest_path(TEST_DATASET, self.make_tree())

        entities = list(self.dataset.iterate())
        self.assertTrue(entities)
        # without a foreign id the namespace falls back to the dataset
        self.assertNamespace(entities, TEST_DATASET)

    def test_ingest_path_foreign_id(self):
        # the cli passes all four arguments positionally
        ingest_path(TEST_DATASET, self.make_tree(), [], FOREIGN_ID)

        entities = list(self.dataset.iterate())
        self.assertTrue(entities)
        self.assertNamespace(entities, FOREIGN_ID)

    def test_ingest_path_invalid_foreign_id(self):
        """An invalid foreign id must be rejected rather than silently becoming
        a namespace nothing else can reproduce."""
        tree = self.make_tree()
        for foreign_id in INVALID_FOREIGN_IDS:
            with self.subTest(foreign_id=foreign_id):
                with self.assertRaises(ValueError):
                    ingest_path(TEST_DATASET, tree, [], foreign_id)

        # validation happens before anything is stored
        self.assertEqual(list(self.dataset.iterate()), [])
