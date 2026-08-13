COMPOSE=docker compose
IMAGE ?= ghcr.io/openaleph/ingest-file:main
BASE_IMAGE ?= ghcr.io/openaleph/ingest-file-base:main

.PHONY: all build build-base build-test services shell lint format format-check \
	test test-store test-lakehouse test-e2e restart tail stop clean dev documentation

all: build shell

build:
	$(COMPOSE) build

build-base:
	docker build . -f Dockerfile.base -t $(BASE_IMAGE)

build-test:
	$(COMPOSE) build test-ingest-file

services:
	$(COMPOSE) up -d --remove-orphans postgres redis

shell: services
	$(COMPOSE) run --rm ingest-file /bin/bash

lint:
	ruff check .

format:
	black .

format-check:
	black --check .

# The suite runs twice, once per storage backend. The calamine extraction
# backend is covered within each run: the tabular suite re-runs itself with the
# flag toggled (see CalamineTabularIngestorTest).
test: build-test test-store test-lakehouse

# no build prerequisite: CI runs these against an image loaded by buildx
test-store:
	$(COMPOSE) run --rm -e INGESTORS_LAKEHOUSE=0 test-ingest-file

test-lakehouse:
	$(COMPOSE) run --rm -e INGESTORS_LAKEHOUSE=1 test-ingest-file

test-e2e:
	cd e2e && ./test_e2e.sh

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
