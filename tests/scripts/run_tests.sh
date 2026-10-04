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

if ! PYTHON_BIN="$(select_python)"; then
    printf '%s\n' 'AgentIPC test error: no usable Python executable found' >&2
    exit 1
fi

LOG_SETTING="${AGENTIPC_TEST_LOG_DIR:-${TMPDIR:-/tmp}/agentipc-logs}"
if [[ "$LOG_SETTING" == /* ]]; then
    LOG_DIR="$LOG_SETTING"
else
    LOG_DIR="$(resolve_repo_path "$LOG_SETTING")"
fi
mkdir -p "$LOG_DIR"
LOG_PATH="${LOG_DIR}/tests-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"

printf '%s\n' 'AgentIPC test suite'
printf 'Repository: %s\n' "$REPO_ROOT"
printf 'Log: %s\n' "$LOG_PATH"

cd "$REPO_ROOT"
if (($#)); then
    "$PYTHON_BIN" -m pytest "$@" 2>&1 | tee "$LOG_PATH"
else
    "$PYTHON_BIN" -m pytest -q 2>&1 | tee "$LOG_PATH"
fi
