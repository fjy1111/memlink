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
    [[ -n "$candidate" ]] || return 1
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
        printf 'AgentIPC verify error: AGENTIPC_BIN is not executable: %s\n' \
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

    printf '%s\n' \
        'AgentIPC verify error: installed AgentIPC CLI not found; run demo/scripts/install.sh first' >&2
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
        printf 'AgentIPC verify error: verification root must be outside repository: %s\n' \
            "$candidate" >&2
        return 1
    fi
}

if ! AGENTIPC_EXEC="$(select_agentipc)"; then
    exit 1
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -n "${AGENTIPC_VERIFY_ROOT:-}" ]]; then
    VERIFY_ROOT="$(absolute_from_cwd "$AGENTIPC_VERIFY_ROOT")"
else
    VERIFY_ROOT="$(absolute_from_cwd "${TMPDIR:-/tmp}/agentipc-verify-${TIMESTAMP}-$$")"
fi

reject_repo_path "$VERIFY_ROOT"
mkdir -p "$VERIFY_ROOT"
VERIFY_ROOT="$(cd -- "$VERIFY_ROOT" && pwd -P)"
reject_repo_path "$VERIFY_ROOT"

VERIFY_LOG="${VERIFY_ROOT}/verify.log"
if [[ -n "${AGENTIPC_TEST_LOG_DIR:-}" ]]; then
    if [[ "$AGENTIPC_TEST_LOG_DIR" == /* ]]; then
        TEST_LOG_CANDIDATE="$AGENTIPC_TEST_LOG_DIR"
    else
        TEST_LOG_CANDIDATE="${REPO_ROOT}/${AGENTIPC_TEST_LOG_DIR}"
    fi
    reject_repo_path "$TEST_LOG_CANDIDATE"
    TEST_LOG_DIR="$AGENTIPC_TEST_LOG_DIR"
else
    TEST_LOG_DIR="${VERIFY_ROOT}/test-logs"
fi
RESULTS_ROOT="${VERIFY_ROOT}/results"
VERIFY_SEED="${AGENTIPC_VERIFY_SEED:-42}"

mkdir -p "$RESULTS_ROOT"
: > "$VERIFY_LOG"

log_line() {
    printf '%s\n' "$1" | tee -a "$VERIFY_LOG"
}

run_stage() {
    local stage="$1"
    shift
    local -a pipeline_status=()
    local stage_rc=0
    local tee_rc=0

    log_line "=== STAGE ${stage} START ==="

    set +e
    "$@" 2>&1 | tee -a "$VERIFY_LOG"
    pipeline_status=("${PIPESTATUS[@]}")
    set -e

    stage_rc="${pipeline_status[0]:-1}"
    tee_rc="${pipeline_status[1]:-1}"
    if ((stage_rc == 0 && tee_rc != 0)); then
        stage_rc="$tee_rc"
    fi

    if ((stage_rc == 0)); then
        log_line "=== STAGE ${stage} PASS ==="
        return 0
    fi

    log_line "=== STAGE ${stage} FAIL (exit=${stage_rc}) ==="
    log_line 'AgentIPC openEuler verification: FAIL'
    log_line "Failed stage: ${stage}"
    log_line "Log: ${VERIFY_LOG}"
    return "$stage_rc"
}

verify_benchmark_outputs() {
    local -a runs=()
    local run=""
    local complete=0

    AGENTIPC_BENCHMARK_PROVIDER=mock \
    AGENTIPC_BENCHMARK_REPEAT=1 \
    AGENTIPC_BENCHMARK_SEED="$VERIFY_SEED" \
    AGENTIPC_RESULTS_ROOT="$RESULTS_ROOT" \
        "${REPO_ROOT}/tests/scripts/run_benchmark.sh" || return $?

    shopt -s nullglob
    runs=("${RESULTS_ROOT}"/*-benchmark-smoke)
    shopt -u nullglob

    if ((${#runs[@]} == 0)); then
        printf '%s\n' 'AgentIPC verify error: benchmark result directory not found' >&2
        return 1
    fi

    for run in "${runs[@]}"; do
        if [[ -d "$run" \
            && -f "$run/raw.jsonl" \
            && -f "$run/summary.json" \
            && -f "$run/environment.json" \
            && -f "$run/report.md" ]]; then
            complete=1
            break
        fi
    done

    if ((complete == 0)); then
        printf '%s\n' \
            'AgentIPC verify error: benchmark result is missing required output files' >&2
        return 1
    fi
}

run_stage openEuler-check "${SCRIPT_DIR}/check_openeuler.sh"
run_stage doctor "$AGENTIPC_EXEC" doctor
run_stage tests env AGENTIPC_TEST_LOG_DIR="$TEST_LOG_DIR" "${REPO_ROOT}/tests/scripts/run_tests.sh"
run_stage demo "$AGENTIPC_EXEC" demo --provider mock
run_stage benchmark verify_benchmark_outputs

log_line 'AgentIPC openEuler verification: PASS'
log_line "Log: ${VERIFY_LOG}"
log_line "Results: ${RESULTS_ROOT}"
