#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

HOST="${MEMLINK_UI_HOST:-0.0.0.0}"
PORT="${MEMLINK_UI_PORT:-8501}"
exec "${PYTHON}" -m streamlit run app/ui/streamlit_app.py \
    --server.address "${HOST}" \
    --server.port "${PORT}" \
    --server.headless true

