#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

"${PYTHON}" -m pip check
"${PYTHON}" -m pytest -q

