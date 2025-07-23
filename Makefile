INGEST=ghcr.io/openaleph/ingest-file
INGEST=ghcr.io/openaleph/ingest-file
COMPOSE=docker compose
COMPOSE_E2E=docker compose -f docker-compose.e2e.yml
DOCKER=$(COMPOSE) run --rm ingest-file

.PHONY: build

all: build shell

build:
	$(COMPOSE) build --no-rm --parallel

build-base:
	docker build . -f Dockerfile.base -t ghcr.io/openaleph/ingest-file-base:latest

build-cache:
	docker build . --cache-from ghcr.io/openaleph/ingest-file:cache -t ghcr.io/openaleph/ingest-file:cache

build-test:
	docker build . -f Dockerfile.test -t ghcr.io/openaleph/ingest-file:test

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

test: build-test services
	PYTHONDEVMODE=1 PYTHONTRACEMALLOC=1 $(COMPOSE) run -e DEBUG=1 --rm ingest-file pytest --cov=ingestors --cov-report html --cov-report term

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
