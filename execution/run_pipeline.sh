#!/bin/zsh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(command -v python3)"

exec "$PYTHON_BIN" "$REPO_ROOT/execution/run_pipeline.py" "$@"
