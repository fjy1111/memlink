#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

resolve_repo_path() {
    local value="$1"
    if [[ "$value" == /* ]]; then
        printf '%s\n' "$value"
    else
        printf '%s\n' "${REPO_ROOT}/${value}"
    fi
}

resolve_command() {
    local candidate="$1"
    local resolved=""
    [[ -n "$candidate" ]] || return 1
    if [[ "$candidate" == */* ]]; then
        resolved="$(resolve_repo_path "$candidate")"
        [[ -x "$resolved" ]] || return 1
        printf '%s\n' "$resolved"
    else
        command -v -- "$candidate"
    fi
}

select_python() {
    local candidate=""

    if [[ -n "${AGENTIPC_PYTHON:-}" ]] && resolve_command "$AGENTIPC_PYTHON"; then
        return 0
    fi

    if [[ -n "${AGENTIPC_VENV_DIR:-}" ]]; then
        candidate="$(resolve_repo_path "$AGENTIPC_VENV_DIR")/bin/python"
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    candidate="${REPO_ROOT}/.venv/bin/python"
    if [[ -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    if resolve_command python3; then
        return 0
    fi

    return 1
}

absolute_from_cwd() {
    local value="$1"
    if [[ "$value" == /* ]]; then
        printf '%s\n' "$value"
    else
        printf '%s/%s\n' "$(pwd -P)" "$value"
    fi
}

reject_repo_path() {
    local candidate="$1"
    if [[ "$candidate" == "$REPO_ROOT" || "$candidate" == "$REPO_ROOT/"* ]]; then
        printf 'AgentIPC package smoke error: work root must be outside repository: %s\n' \
            "$candidate" >&2
        return 1
    fi
}

if ! PYTHON_BIN="$(select_python)"; then
    printf '%s\n' 'AgentIPC package smoke error: no usable Python executable found' >&2
    exit 1
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -n "${AGENTIPC_PACKAGE_SMOKE_ROOT:-}" ]]; then
    WORK_ROOT="$(absolute_from_cwd "$AGENTIPC_PACKAGE_SMOKE_ROOT")"
else
    WORK_ROOT="$(absolute_from_cwd "${TMPDIR:-/tmp}/agentipc-package-smoke-${TIMESTAMP}-$$")"
fi

reject_repo_path "$WORK_ROOT"
mkdir -p "$WORK_ROOT"
WORK_ROOT="$(cd -- "$WORK_ROOT" && pwd -P)"
reject_repo_path "$WORK_ROOT"

SOURCE_COPY="${WORK_ROOT}/source"
DIST_DIR="${WORK_ROOT}/dist"
SMOKE_VENV="${WORK_ROOT}/install-venv"
AWAY_DIR="${WORK_ROOT}/away-from-source"

for reserved in "$SOURCE_COPY" "$DIST_DIR" "$SMOKE_VENV" "$AWAY_DIR"; do
    if [[ -e "$reserved" ]]; then
        printf 'AgentIPC package smoke error: reserved path already exists: %s\n' \
            "$reserved" >&2
        exit 1
    fi
done

mkdir -p "$DIST_DIR" "$AWAY_DIR"

"$PYTHON_BIN" - "$REPO_ROOT" "$SOURCE_COPY" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])

excluded_names = {
    ".git",
    ".venv",
    "venv",
    "results",
    "dist",
    "build",
    ".pytest_cache",
    "__pycache__",
}


def ignore(directory: str, names: list[str]) -> set[str]:
    del directory
    return {
        name
        for name in names
        if name in excluded_names or name.endswith(".egg-info")
    }


shutil.copytree(source, destination, ignore=ignore)
PY

"$PYTHON_BIN" -m pip wheel \
    --no-deps \
    --no-build-isolation \
    --wheel-dir "$DIST_DIR" \
    "$SOURCE_COPY"

shopt -s nullglob
WHEELS=("${DIST_DIR}"/agentipc-*.whl)
shopt -u nullglob

if ((${#WHEELS[@]} != 1)); then
    printf 'AgentIPC package smoke error: expected exactly one AgentIPC wheel, found %d\n' \
        "${#WHEELS[@]}" >&2
    exit 1
fi
WHEEL_PATH="${WHEELS[0]}"

"$PYTHON_BIN" -m venv "$SMOKE_VENV"
"$SMOKE_VENV/bin/python" -m pip install --no-deps "$WHEEL_PATH"

VERSION="$(
    cd -- "$AWAY_DIR"
    PYTHONPATH= "$SMOKE_VENV/bin/agentipc" version
)"
if [[ "$VERSION" != "0.1.0" ]]; then
    printf 'AgentIPC package smoke error: unexpected installed version: %s\n' \
        "$VERSION" >&2
    exit 1
fi

(
    cd -- "$AWAY_DIR"
    PYTHONPATH= "$SMOKE_VENV/bin/python" - <<'PY'
import agentipc

assert agentipc.__version__ == "0.1.0"
print(agentipc.__version__)
PY
)

(
    cd -- "$AWAY_DIR"
    PYTHONPATH= "$SMOKE_VENV/bin/python" - <<'PY'
from importlib.metadata import distribution

installed = distribution("agentipc")
assert installed.metadata["Name"] == "agentipc"
assert installed.version == "0.1.0"
entry_points = [
    entry
    for entry in installed.entry_points
    if entry.group == "console_scripts" and entry.name == "agentipc"
]
assert len(entry_points) == 1
assert entry_points[0].value == "agentipc.cli:main"
print("distribution metadata: PASS")
PY
)

(
    cd -- "$AWAY_DIR"
    PYTHONPATH= "$SMOKE_VENV/bin/python" - <<'PY'
import sys
from pathlib import Path

root = Path(sys.prefix) / "share" / "agentipc" / "dashboard"
for name in ("index.html", "app.js", "styles.css"):
    path = root / name
    assert path.is_file(), path
    assert path.stat().st_size > 0, path
print(root)
PY
)

printf '%s\n' 'AgentIPC package smoke: PASS'
printf 'Wheel: %s\n' "$WHEEL_PATH"
printf 'Fresh venv: %s\n' "$SMOKE_VENV"
printf 'Version: %s\n' "$VERSION"
printf '%s\n' 'Dashboard assets: PASS'
