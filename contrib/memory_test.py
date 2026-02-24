"""
Entrypoint for memray. make sure postgres & redis are running

export REDIS_URL=redis://localhost
export OPENALEPH_DB_URI=postgresql:///openaleph
export FTM_FRAGMENTS_URI=postgresql:///openaleph

then:
openaleph-procrastinate init-db
memray run contrib/memory_test.py
"""

from pathlib import Path

from openaleph_procrastinate.settings import DeferSettings

from ingestors.tasks import app, ingest_path

path = Path(__file__).parent.parent.resolve() / "tests/fixtures"
defer_settings = DeferSettings()

ingest_path("memory_test", path=path, languages=[])

app.run_worker(queues=[defer_settings.ingest.queue], wait=False)
