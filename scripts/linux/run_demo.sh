#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export MEMLINK_LLM_BACKEND="${MEMLINK_LLM_BACKEND:-fake}"
export MEMLINK_EMBEDDING_BACKEND="${MEMLINK_EMBEDDING_BACKEND:-fake}"

"${PYTHON}" -m app.cli run-demo --mode text
"${PYTHON}" -m app.cli run-demo --mode structured

