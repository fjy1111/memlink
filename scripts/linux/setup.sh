#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    echo "Operating system: ${PRETTY_NAME:-unknown}"
    if [[ "${ID:-}" != "openEuler" && "${ID:-}" != "openeuler" ]]; then
        echo "Warning: target validation is intended for openEuler 24.03-LTS-SP3." >&2
    fi
else
    echo "Unable to read /etc/os-release." >&2
    exit 1
fi

python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version; print(sys.version)'
python3 -m venv .venv

PYTHON="${PROJECT_ROOT}/.venv/bin/python"
"${PYTHON}" -m pip install --upgrade pip
"${PYTHON}" -m pip install -r requirements-dev.txt

mkdir -p data/metrics data/states data/memory benchmarks/results
chmod u+rwX data/metrics data/states data/memory benchmarks/results
chmod u+x scripts/linux/*.sh
"${PYTHON}" -m pip check

echo "MemLink environment created at ${PROJECT_ROOT}/.venv"

