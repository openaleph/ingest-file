"""HTTP api for uploads and status tracking

Upload files into a dataset as a batch, poll the batch status, then build the
lakehouse dataset, so clients read the result from the lakehouse itself:

    POST   /{dataset}/files?file_name=…[&batch=…]  raw body -> batch
    GET    /{dataset}/batches/{batch}              job counts, done
    POST   /{dataset}/make                         lakehouse make
    DELETE /{dataset}                              cancel jobs, delete
"""

import hashlib
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from anystore.logic.uri import uri_to_path
from anystore.store import get_store
from anystore.util import ensure_uuid
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from followthemoney.dataset.util import dataset_name_check
from ftm_lakehouse import get_lakehouse
from ftm_lakehouse.operation.factories import make
from ftm_lakehouse.operation.make import MakeJob
from openaleph_procrastinate.manage.db import get_db
from openaleph_procrastinate.manage.status import get_batch_status
from openaleph_procrastinate.model import StatusCounts
from pydantic import BaseModel, computed_field

from ingestors import __version__
from ingestors.settings import Settings
from ingestors.tasks import ingest_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not Settings().lakehouse:
        raise RuntimeError("The api needs `OPENALEPH_LAKEHOUSE=1`")
    yield


app = FastAPI(
    title="ingest-file",
    version=__version__,
    description=__doc__,
    redoc_url="/",
    lifespan=lifespan,
)


def check_dataset(dataset: str) -> str:
    try:
        return dataset_name_check(dataset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


Dataset = Annotated[str, Depends(check_dataset)]


class Upload(BaseModel):
    dataset: str
    batch: str
    file_name: str
    size: int
    md5: str
    sha1: str
    sha256: str


class Batch(StatusCounts):
    name: str

    @computed_field
    @property
    def done(self) -> bool:
        """No job left to run"""
        return not (self.todo or self.doing or self.aborting)


@app.post("/{dataset}/files", status_code=202)
async def upload(
    dataset: Dataset,
    request: Request,
    file_name: Annotated[str, Query(min_length=1)],
    batch: str | None = None,
    languages: Annotated[list[str] | None, Query()] = None,
    analyze: bool = True,
) -> Upload:
    """Upload one file as the raw request body, `file_name` becomes the
    entity's `fileName` as is. Pass `batch` to add more files to the same
    batch."""
    batch = ensure_uuid(batch)  # uuid7
    hashes = {alg: hashlib.new(alg) for alg in ("md5", "sha1", "sha256")}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload"
        with open(path, "wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
                for h in hashes.values():
                    h.update(chunk)
        size = path.stat().st_size
        await run_in_threadpool(
            ingest_path,
            dataset,
            path,
            languages or [],
            batch=batch,
            analyze=analyze,
            file_name=file_name,
        )
    return Upload(
        dataset=dataset,
        batch=batch,
        file_name=file_name,
        size=size,
        **{alg: h.hexdigest() for alg, h in hashes.items()},
    )


@app.get("/{dataset}/batches/{batch}")
def batch_status(dataset: Dataset, batch: str) -> Batch:
    status = get_batch_status(dataset, batch, active_only=False)
    if not status.total:
        raise HTTPException(404, "batch not found")
    return Batch.model_validate(status, from_attributes=True)


@app.post("/{dataset}/make")
def make_dataset(dataset: Dataset) -> MakeJob:
    return make(dataset)


@app.delete("/{dataset}", status_code=204)
def delete(dataset: Dataset) -> None:
    get_db().cancel_jobs(dataset=dataset)
    store = get_store(get_lakehouse().dataset_uri(dataset))
    if store.is_local:  # removes the directories, too
        shutil.rmtree(uri_to_path(store.uri), ignore_errors=True)
    else:
        for key in list(store.iterate_keys()):
            store.delete(key, ignore_errors=True)
