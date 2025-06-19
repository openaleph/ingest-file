#!/bin/bash

set -e

# initialize db
opal-procrastinate init-db

exec "$@"
