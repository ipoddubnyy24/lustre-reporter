#!/usr/bin/env bash
# Run the unit tests with coverage (enforced 100% gate).
# Bootstraps an isolated .venv with pytest + pytest-cov on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/pytest ]; then
  echo "Creating test venv (.venv)…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q pytest pytest-cov
fi

exec .venv/bin/python -m pytest --cov=lustre_reporter --cov-report=term-missing "$@"
