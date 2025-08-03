#!/bin/bash

export OPENALEPH_DB_URI=postgresql://ingest:ingest@localhost:54321/ingest

# defer ingest tasks and add files to archive
docker compose -f docker-compose.e2e.yml run --rm ingest-file ingestors ingest -d fixtures /fixtures
# run one-shot ingest worker
docker compose -f docker-compose.e2e.yml run --rm ingest-file
# run one-shot analyze worker
docker compose -f docker-compose.e2e.yml run --rm analyze

# show results
psql -c "SELECT COUNT(*) FROM ftm_fixtures" $OPENALEPH_DB_URI
psql -c "SELECT COUNT(DISTINCT id) FROM ftm_fixtures" $OPENALEPH_DB_URI
psql -c "SELECT queue_name, task_name, status, COUNT(*) FROM procrastinate_jobs GROUP BY queue_name, task_name, status" $OPENALEPH_DB_URI

docker compose -f docker-compise.e2e.yml down --remove-orphans -v
