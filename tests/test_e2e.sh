#!/bin/bash

ingestors ingest -d fixtures /ingestors/tests/fixtures/
procrastinate worker -q ingest --one-shot
