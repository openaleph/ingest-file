from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob, Defers
from openaleph_procrastinate.tasks import task

app = make_app(__loader__.name)


@task(app=app)
def ingest(job: DatasetJob) -> Defers:
    to_analyze: list[EntityProxy] = []
    to_index: list[EntityProxy] = []

    for entity in job.get_entities():
        # TODO ingest it ;)
        if entity.schema.is_a("Analyzable"):
            to_analyze.append(entity)
        else:
            to_index.append(entity)

    yield defer.analyze(job.dataset, to_analyze, **job.context)
    yield defer.index(job.dataset, to_index, **job.context)
