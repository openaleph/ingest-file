INGEST=ghcr.io/openaleph/ingest-file
INGEST=ghcr.io/openaleph/ingest-file
COMPOSE=docker compose
COMPOSE_E2E=docker compose -f docker-compose.e2e.yml
DOCKER=$(COMPOSE) run --rm ingest-file
IMAGE ?= ghcr.io/openaleph/ingest-file:latest

.PHONY: build

all: build shell

build:
	$(COMPOSE) build --no-rm --parallel

build-base:
	docker build . -f Dockerfile.base -t ghcr.io/openaleph/ingest-file-base:latest

build-cache:
	docker build . --cache-from ghcr.io/openaleph/ingest-file:cache -t ghcr.io/openaleph/ingest-file:cache

build-test:
	$(COMPOSE) build test-ingest-file

build-macos:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 $(COMPOSE) build --no-rm --parallel

services:
	$(COMPOSE) up -d --remove-orphans postgres redis

shell: services
	$(DOCKER) /bin/bash

lint:
	ruff check .

format:
	black .

format-check:
	black --check .

test: build-test services test-kreuzberg
	PYTHONDEVMODE=1 PYTHONTRACEMALLOC=1 $(COMPOSE) run --rm test-ingest-file pytest

# Re-run the tabular suite with the kreuzberg extraction backend enabled
# (INGESTORS_KREUZBERG defaults to off) so both code paths get covered.
test-kreuzberg: build-test services
	PYTHONDEVMODE=1 PYTHONTRACEMALLOC=1 $(COMPOSE) run --rm -e INGESTORS_KREUZBERG=1 test-ingest-file pytest tests/test_tabular.py

test-arm: services
	DEBUG=1 PYTHONDEVMODE=1 PYTHONTRACEMALLOC=1 PROCRASTINATE_APP=ingestors.tasks.app docker run --rm -v ./tests:/ingestors/tests $(IMAGE) sh -c "cd /ingestors && pip3 install --no-deps -r /ingestors/requirements-dev.txt && pip3 install --no-cache-dir procrastinate==3.2.2 && chown -R app:app /ingestors && pytest"

test-e2e: build services
	$(COMPOSE_E2E) run --rm ingest-file

restart: build
	$(COMPOSE) up --force-recreate --no-deps --detach ingest-file

tail:
	$(COMPOSE) logs -f

stop:
	$(COMPOSE) down --remove-orphans

clean:
	rm -rf dist build
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -type d -name __pycache__ -exec rm -r {} \+

dev:
	python3 -m pip install --upgrade pip
	python3 -m pip install -q -r requirements-dev.txt

documentation:
	mkdocs build
	aws --profile nbg1 --endpoint-url https://s3.investigativedata.org s3 sync ./site s3://openaleph.org/docs/lib/ingest-file
