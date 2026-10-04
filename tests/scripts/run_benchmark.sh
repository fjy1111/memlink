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
    if [[ "$candidate" == */* ]]; then
        candidate="$(resolve_repo_path "$candidate")"
        [[ -x "$candidate" ]] || return 1
        printf '%s\n' "$candidate"
    else
        command -v -- "$candidate"
    fi
}

select_agentipc() {
    local candidate=""

    if [[ -n "${AGENTIPC_BIN:-}" ]]; then
        if resolve_command "$AGENTIPC_BIN"; then
            return 0
        fi
        printf 'AgentIPC benchmark error: AGENTIPC_BIN is not executable: %s\n' \
            "$AGENTIPC_BIN" >&2
        return 1
    fi

    if [[ -n "${AGENTIPC_VENV_DIR:-}" ]]; then
        candidate="$(resolve_repo_path "$AGENTIPC_VENV_DIR")/bin/agentipc"
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    candidate="${REPO_ROOT}/.venv/bin/agentipc"
    if [[ -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    if command -v -- agentipc >/dev/null 2>&1; then
        command -v -- agentipc
        return 0
    fi

    printf '%s\n' 'AgentIPC benchmark error: agentipc executable not found' >&2
    return 1
}

PROVIDER="${AGENTIPC_BENCHMARK_PROVIDER-mock}"
SEED="${AGENTIPC_BENCHMARK_SEED-42}"
REPEAT="${AGENTIPC_BENCHMARK_REPEAT-3}"
RESULTS_SETTING="${AGENTIPC_RESULTS_ROOT-results}"

if [[ -z "$PROVIDER" ]]; then
    printf '%s\n' 'AgentIPC benchmark error: AGENTIPC_BENCHMARK_PROVIDER must not be empty' >&2
    exit 1
fi
if [[ ! "$SEED" =~ ^[0-9]+$ ]]; then
    printf 'AgentIPC benchmark error: AGENTIPC_BENCHMARK_SEED must be an integer >= 0: %s\n' \
        "$SEED" >&2
    exit 1
fi
if [[ ! "$REPEAT" =~ ^[0-9]+$ || ! "$REPEAT" =~ [1-9] ]]; then
    printf 'AgentIPC benchmark error: AGENTIPC_BENCHMARK_REPEAT must be an integer >= 1: %s\n' \
        "$REPEAT" >&2
    exit 1
fi
if [[ -z "$RESULTS_SETTING" ]]; then
    printf '%s\n' 'AgentIPC benchmark error: AGENTIPC_RESULTS_ROOT must not be empty' >&2
    exit 1
fi

RESULTS_ROOT="$(resolve_repo_path "$RESULTS_SETTING")"
if ! AGENTIPC_EXEC="$(select_agentipc)"; then
    exit 1
fi

printf '%s\n' 'AgentIPC benchmark'
printf 'Provider: %s\n' "$PROVIDER"
printf 'Seed: %s\n' "$SEED"
printf 'Repeat: %s\n' "$REPEAT"
printf 'Results root: %s\n' "$RESULTS_ROOT"

cd "$REPO_ROOT"
"$AGENTIPC_EXEC" benchmark \
    --suite smoke \
    --repeat "$REPEAT" \
    --seed "$SEED" \
    --provider "$PROVIDER" \
    --results-root "$RESULTS_ROOT"
