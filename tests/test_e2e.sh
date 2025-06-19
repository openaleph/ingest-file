#!/bin/bash

ingestors ingest -d fixtures /ingestors/tests/fixtures/
procrastinate worker -q ingest --concurrency 8 --one-shot
