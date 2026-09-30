#!/bin/bash

# a failing step fails the test, instead of the run carrying on to a green exit
set -e
trap 'docker compose -f docker-compose.e2e.yml down --remove-orphans -v' EXIT

export OPENALEPH_DB_URI=postgresql://ingest:ingest@localhost:54321/ingest

#1 LAKEHOUSE=0

# initialize db
docker compose -f docker-compose.e2e.yml run --rm ingest-file openaleph-procrastinate init-db
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

docker compose -f docker-compose.e2e.yml down --remove-orphans -v


#2 LAKEHOUSE=1

# initialize db
docker compose -f docker-compose.e2e.yml run --rm ingest-file openaleph-procrastinate init-db
# defer ingest tasks and add files to archive
docker compose -f docker-compose.e2e.yml run -e OPENALEPH_LAKEHOUSE=1 --rm ingest-file ingestors ingest -d fixtures /fixtures
# run one-shot ingest worker
docker compose -f docker-compose.e2e.yml run -e OPENALEPH_LAKEHOUSE=1 --rm ingest-file
# run one-shot analyze worker
docker compose -f docker-compose.e2e.yml run --rm analyze

# show results
psql -c "SELECT COUNT(*) FROM ftm_fixtures" $OPENALEPH_DB_URI
psql -c "SELECT COUNT(DISTINCT id) FROM ftm_fixtures" $OPENALEPH_DB_URI
psql -c "SELECT queue_name, task_name, status, COUNT(*) FROM procrastinate_jobs GROUP BY queue_name, task_name, status" $OPENALEPH_DB_URI

docker compose -f docker-compose.e2e.yml down --remove-orphans -v


#3 unoserver: convert through the listener image instead of the workers' own
# listeners. Fails unless every document went through it and none fell back
# to spawning. One fixture per ingestor that converts to PDF.

UNOSERVER_FIXTURES=("doc.doc" "hello world word.docx" "Plan.odt" "slides.ppt")

docker compose -f docker-compose.e2e.yml up -d --wait unoserver
docker compose -f docker-compose.e2e.yml run --rm ingest-file openaleph-procrastinate init-db
docker compose -f docker-compose.e2e.yml run --rm ingest-file sh -c 'for f; do ingestors ingest -d unoserver "/fixtures/$f"; done' sh "${UNOSERVER_FIXTURES[@]}"
UNOSERVER_LOG=$(mktemp)
docker compose -f docker-compose.e2e.yml run -T -e INGESTORS_UNOSERVER_URI=http://unoserver:2003 --rm ingest-file 2>&1 | tee "$UNOSERVER_LOG"

# grep -c exits 1 when it counts nothing
converted=$(grep -c "Successfully converted .* via unoserver" "$UNOSERVER_LOG" || true)
spawned=$(grep -c "Starting LibreOffice" "$UNOSERVER_LOG" || true)
rm "$UNOSERVER_LOG"
if [ "$converted" -ne ${#UNOSERVER_FIXTURES[@]} ] || [ "$spawned" -ne 0 ]; then
    docker compose -f docker-compose.e2e.yml logs unoserver
    echo "unoserver: expected ${#UNOSERVER_FIXTURES[@]} conversions through the listener and none spawned, got $converted and $spawned"
    exit 1
fi
