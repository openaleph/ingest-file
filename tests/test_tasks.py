import unittest
from pathlib import Path
from tempfile import mkdtemp

from followthemoney import EntityProxy, StatementEntity, model, registry
from followthemoney.namespace import Namespace
from openaleph_procrastinate import defer
from openaleph_procrastinate.util import make_file_entity

from ingestors.settings import OP_INGEST, Settings
from ingestors.tasks import SKIP_ANALYSIS, app, ingest_path, should_analyze
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


class ShouldAnalyzeTest(unittest.TestCase):
    """`should_analyze` decides whether the `ingest` task defers to
    `ftm-analyze`. It gets whatever `Manager.get_emitted` returns, which with
    the default `procrastinate_dehydrate_entities=True` is a stub, so it has to
    decide on the schema alone."""

    def make_entity(self, schema: str) -> EntityProxy:
        entity = model.make_entity(schema)
        entity.id = f"analyze-{schema.lower()}"
        return entity

    def dehydrate(self, entity: EntityProxy) -> StatementEntity:
        """Reduce to id, schema, contentHash, fileName, parent and ancestors,
        the way `Manager.emit_entity` does. The stub carries no text."""
        stub = make_file_entity(entity, StatementEntity, quiet=True)
        self.assertEqual(list(stub.get_type_values(registry.text)), [])
        return stub

    def test_analyze_dehydrated_document(self):
        entity = self.make_entity("PlainText")
        entity.add("fileName", "memo.txt")
        entity.add("contentHash", "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        entity.add("bodyText", "Kenneth Lay met Jeff Skilling in Houston.")
        self.assertTrue(should_analyze(entity))
        self.assertTrue(should_analyze(self.dehydrate(entity)))

    def test_analyze_email(self):
        entity = self.make_entity("Email")
        entity.add("bodyText", "Kenneth Lay met Jeff Skilling in Houston.")
        # `Email` extends `Folder`, so it must not be matched with `is_a`
        self.assertTrue(entity.schema.is_a("Folder"))
        self.assertTrue(should_analyze(entity))
        self.assertTrue(should_analyze(self.dehydrate(entity)))

    def test_skip_containers(self):
        """Containers carry no text of their own, their children are emitted
        (and analyzed) separately."""
        for schema in SKIP_ANALYSIS:
            with self.subTest(schema=schema):
                entity = self.make_entity(schema)
                self.assertTrue(entity.schema.is_a("Analyzable"))
                self.assertFalse(should_analyze(entity))

    def test_skip_not_analyzable(self):
        self.assertFalse(should_analyze(self.make_entity("Person")))


class AnalyzeDeferTest(TestCase):
    """The checks above pin `should_analyze` itself, this one pins the chain it
    sits in: running the `ingest` task has to leave a job on the analyze queue.
    Both stages defer into the `InMemoryConnector`, where the jobs sit until it
    is reset per test."""

    def deferred_entities(self, queue: str) -> list[dict]:
        return [
            entity
            for job in app.connector.jobs.values()
            if job["queue_name"] == queue
            for entity in job["args"]["payload"]["entities"]
        ]

    def deferred_schemata(self, queue: str) -> set[str]:
        return {e["schema"] for e in self.deferred_entities(queue)}

    def ingest_fixture(self, name: str) -> None:
        path = Path(__file__).parent / "fixtures" / name
        ingest_path(TEST_DATASET, path)
        # the task defers analyze and index jobs, they stay on their queues
        app.run_worker(queues=[OP_INGEST], wait=False)
        self.assertTrue(list(self.dataset.iterate()), "nothing was ingested")

    def test_defer_analyze_document(self):
        self.ingest_fixture("utf.txt")
        analyze = self.deferred_schemata(defer.tasks.analyze.queue)
        self.assertEqual(analyze, {"PlainText"})
        # the two stages are deferred from the same emitted entities, analysis
        # is the subset that `should_analyze` accepts
        self.assertTrue(analyze <= self.deferred_schemata(defer.tasks.index.queue))

    def test_defer_analyze_email(self):
        self.ingest_fixture("testThunderbirdEml.eml")
        self.assertIn("Email", self.deferred_schemata(defer.tasks.analyze.queue))

    def test_defer_analyze_skips_workbook(self):
        self.ingest_fixture("file.xlsx")
        indexed = self.deferred_schemata(defer.tasks.index.queue)
        self.assertIn("Workbook", indexed)
        self.assertNotIn("Workbook", self.deferred_schemata(defer.tasks.analyze.queue))
