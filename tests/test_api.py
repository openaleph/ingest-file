import uuid
from pathlib import Path
from unittest import mock

import pytest
from anystore.logic.uri import uri_to_path
from anystore.store import get_store
from ftm_lakehouse import get_lakehouse
from openaleph_procrastinate.model import BatchStatus

from ingestors.settings import Settings
from ingestors.tasks import app as tasks
from tests.support import TEST_DATASET, TestCase

if not Settings().lakehouse:
    pytest.skip("the api needs OPENALEPH_LAKEHOUSE=1", allow_module_level=True)
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ingestors.api import app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class ApiTest(TestCase):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(app))  # runs the lifespan

    def upload(self, fixture, **params):
        return self.client.post(
            f"/{TEST_DATASET}/files",
            params={"file_name": fixture, **params},
            content=(FIXTURES / fixture).read_bytes(),
        )

    def jobs(self):
        return [job["args"] for job in tasks.connector.jobs.values()]

    def test_upload_defers_into_batch(self):
        res = self.upload("test-documents.zip", batch="b1", analyze="false")
        self.assertEqual(res.status_code, 202, res.text)
        data = res.json()
        self.assertEqual(data["batch"], "b1")
        self.assertEqual(len(data["sha256"]), 64)
        self.assertEqual(self.jobs()[0]["batch"], "b1")
        self.assertFalse(self.jobs()[0]["payload"]["context"]["analyze"])

        # the child jobs of the archive members stay in the batch
        tasks.run_worker(queues=["ingest"], wait=False)
        ingest = [j for j in self.jobs() if j["task"] == "ingestors.tasks.ingest"]
        self.assertGreater(len(ingest), 1)
        self.assertEqual({j["batch"] for j in ingest}, {"b1"})
        self.assertFalse([j for j in self.jobs() if j["queue"] == "analyze"])

    def test_upload_new_batch(self):
        # the name is the entity's fileName as given, only the worker's copy on
        # disk gets a safe name
        name = "../pfad/Bericht über.txt"
        data = self.upload("utf.txt", file_name=name).json()
        self.assertEqual(uuid.UUID(data["batch"]).version, 7)
        self.assertEqual(data["file_name"], name)
        tasks.run_worker(queues=["ingest"], wait=False)
        emitted = {e.first("fileName"): e for e in self.dataset.iterate()}
        self.assertIn(name, emitted)
        self.assertEqual(emitted[name].schema.name, "PlainText")
        res = self.upload("utf.txt", file_name="")
        self.assertEqual(res.status_code, 422)

    def test_invalid_dataset(self):
        res = self.client.post("/Not Valid/files", params={"file_name": "x"})
        self.assertEqual(res.status_code, 400)

    def test_batch_status(self):
        batches = {"x": BatchStatus(name="x", todo=1, succeeded=2)}
        with mock.patch("ingestors.api.get_batch_status") as get_batch_status:
            get_batch_status.side_effect = lambda d, b, **kw: batches.get(
                b, BatchStatus(name=b)
            )
            res = self.client.get(f"/{TEST_DATASET}/batches/x")
            self.assertEqual(res.status_code, 200, res.text)
            get_batch_status.assert_called_with(TEST_DATASET, "x", active_only=False)
            data = res.json()
            self.assertFalse(data["done"])
            self.assertEqual(data["total"], 3)
            self.assertNotIn("queues", data)
            self.assertEqual(
                self.client.get(f"/{TEST_DATASET}/batches/y").status_code, 404
            )

    def test_make_and_delete(self):
        self.upload("utf.txt", batch="b2")
        tasks.run_worker(queues=["ingest"], wait=False)
        res = self.client.post(f"/{TEST_DATASET}/make")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["dataset"], TEST_DATASET)
        root = get_lakehouse().dataset_uri(TEST_DATASET)
        self.assertTrue(get_store(root).exists("entities.ftm.json"))
        self.assertTrue(get_store(root).exists("exports/statistics.json"))
        with mock.patch("ingestors.api.get_db") as get_db:
            res = self.client.delete(f"/{TEST_DATASET}")
            self.assertEqual(res.status_code, 204)
            self.assertEqual(res.content, b"")
            get_db().cancel_jobs.assert_called_with(dataset=TEST_DATASET)
        self.assertFalse(list(get_store(root).iterate_keys()))
        if get_store(root).is_local:
            self.assertFalse(uri_to_path(root).exists())
