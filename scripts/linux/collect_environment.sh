#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
OUTPUT="${PROJECT_ROOT}/benchmarks/results/environment.json"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

mkdir -p "$(dirname -- "${OUTPUT}")"
"${PYTHON}" -c \
    'from pathlib import Path; from app.benchmark.environment import collect_environment; from app.benchmark.output import write_json; write_json(Path("benchmarks/results/environment.json"), collect_environment())'
echo "Environment written to ${OUTPUT}"

