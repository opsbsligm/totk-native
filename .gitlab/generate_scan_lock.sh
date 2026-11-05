#!/bin/sh
# Maintenance only: generate a real pip-compile input for the dependency scanner.
set -eu
cd "$(dirname "$0")/.."
export PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple PIP_EXTRA_INDEX_URL= PIP_NO_INDEX=0
uv --no-config tool run --isolated --python 3.11 --with pip==26.3 --from pip-tools==7.6.2 \
  pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url \
  --no-emit-trusted-host --output-file .gitlab/pipcompile.lock.txt requirements-build.lock
python3 .gitlab/check_dependency_coverage.py --input-only
