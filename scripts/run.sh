#!/usr/bin/env bash
# Launch Lustre Reporter. Any args are passed through (e.g. --port, --open).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m lustre_reporter "$@"
