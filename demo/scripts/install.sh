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
    if [[ "$candidate" == */* ]]; then
        resolved="$(resolve_repo_path "$candidate")"
        [[ -x "$resolved" ]] || return 1
        printf '%s\n' "$resolved"
    else
        command -v -- "$candidate"
    fi
}

PYTHON_SETTING="${AGENTIPC_PYTHON:-python3}"
if ! PYTHON_BIN="$(resolve_command "$PYTHON_SETTING")"; then
    printf 'AgentIPC install error: Python executable not found: %s\n' "$PYTHON_SETTING" >&2
    exit 1
fi

VENV_SETTING="${AGENTIPC_VENV_DIR:-.venv}"
VENV_DIR="$(resolve_repo_path "$VENV_SETTING")"

if ! "$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    actual = ".".join(map(str, sys.version_info[:3]))
    print(
        f"AgentIPC install error: Python {actual} detected; Python >= 3.10 is required.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
then
    exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    printf 'Creating virtual environment: %s\n' "$VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        printf '%s\n' \
            'AgentIPC install error: failed to create the virtual environment.' \
            'Ensure the Python venv/pip prerequisites for this system are installed, then retry.' >&2
        exit 1
    fi
else
    printf 'Reusing virtual environment: %s\n' "$VENV_DIR"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    printf 'AgentIPC install error: virtual environment Python is not executable: %s\n' \
        "$VENV_DIR/bin/python" >&2
    exit 1
fi

"$VENV_DIR/bin/python" -m pip install -e "${REPO_ROOT}[dev,dashboard]"

if [[ ! -x "$VENV_DIR/bin/agentipc" ]]; then
    printf 'AgentIPC install error: expected CLI was not installed: %s\n' \
        "$VENV_DIR/bin/agentipc" >&2
    exit 1
fi

"$VENV_DIR/bin/agentipc" version

printf '%s\n' 'AgentIPC installation complete'
printf 'Virtual environment: %s\n' "$VENV_DIR"
printf 'Activate with: source %s/bin/activate\n' "$VENV_DIR"
