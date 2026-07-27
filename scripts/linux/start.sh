#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

HOST="${MEMLINK_HOST:-0.0.0.0}"
PORT="${MEMLINK_PORT:-8000}"
exec "${PYTHON}" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"

