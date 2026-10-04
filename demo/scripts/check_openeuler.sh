#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
FAILED=0

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

if [[ -r /etc/os-release ]]; then
    OS_ID="$(. /etc/os-release; printf '%s' "${ID:-}")"
    OS_NAME="$(. /etc/os-release; printf '%s' "${NAME:-}")"
    OS_PRETTY="$(. /etc/os-release; printf '%s' "${PRETTY_NAME:-}")"
    OS_VERSION="$(. /etc/os-release; printf '%s' "${VERSION_ID:-}")"
    OS_LABEL="${OS_PRETTY:-${OS_NAME:-${OS_ID:-unknown}}}"

    if [[ "${OS_ID,,}" == "openeuler" || "${OS_NAME,,}" == *"openeuler"* ]]; then
        if [[ -n "$OS_VERSION" && "$OS_LABEL" != *"$OS_VERSION"* ]]; then
            OS_LABEL="$OS_LABEL $OS_VERSION"
        fi
        printf 'PASS os: %s\n' "$OS_LABEL"
    else
        printf 'FAIL os: expected openEuler, detected %s\n' "$OS_LABEL" >&2
        FAILED=1
    fi
else
    printf '%s\n' 'FAIL os: /etc/os-release not found' >&2
    FAILED=1
fi

PYTHON_BIN=""
if PYTHON_BIN="$(select_python)"; then
    if PYTHON_VERSION="$("$PYTHON_BIN" - <<'PY'
import sys

print(".".join(map(str, sys.version_info[:3])))
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
)"; then
        printf 'PASS python: %s\n' "$PYTHON_VERSION"
    else
        printf 'FAIL python: AgentIPC requires Python >= 3.10 (detected %s)\n' \
            "${PYTHON_VERSION:-unknown}" >&2
        FAILED=1
    fi
else
    printf '%s\n' 'FAIL python: no usable Python executable found' >&2
    FAILED=1
fi

if [[ -n "$PYTHON_BIN" ]]; then
    if SHM_ERROR="$("$PYTHON_BIN" - <<'PY'
from multiprocessing.shared_memory import SharedMemory
import sys

owner = None
attached = None
payload = b"agentipc-openeuler-shm"
try:
    owner = SharedMemory(create=True, size=len(payload))
    owner.buf[: len(payload)] = payload
    attached = SharedMemory(name=owner.name)
    observed = bytes(attached.buf[: len(payload)])
    if observed != payload:
        raise RuntimeError("shared memory round-trip mismatch")
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}")
    raise SystemExit(1)
finally:
    if attached is not None:
        try:
            attached.close()
        except Exception:
            pass
    if owner is not None:
        try:
            owner.close()
        except Exception:
            pass
        try:
            owner.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
PY
)"; then
        printf '%s\n' 'PASS shared_memory'
    else
        printf 'FAIL shared_memory: %s\n' "${SHM_ERROR:-probe failed}" >&2
        FAILED=1
    fi

    if SQLITE_ERROR="$("$PYTHON_BIN" - <<'PY'
import sqlite3
import sys
import tempfile
from pathlib import Path

connection = None
try:
    with tempfile.TemporaryDirectory(prefix="agentipc-openeuler-sqlite-") as temp_dir:
        db_path = Path(temp_dir) / "probe.sqlite3"
        connection = sqlite3.connect(db_path)
        with connection:
            connection.execute("CREATE TABLE probe (value TEXT NOT NULL)")
            connection.execute("INSERT INTO probe(value) VALUES (?)", ("ok",))
        row = connection.execute("SELECT value FROM probe").fetchone()
        if row != ("ok",):
            raise RuntimeError("SQLite round-trip mismatch")
        connection.close()
        connection = None
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}")
    raise SystemExit(1)
finally:
    if connection is not None:
        connection.close()
PY
)"; then
        printf '%s\n' 'PASS sqlite'
    else
        printf 'FAIL sqlite: %s\n' "${SQLITE_ERROR:-probe failed}" >&2
        FAILED=1
    fi
else
    printf '%s\n' 'FAIL shared_memory: Python unavailable' >&2
    printf '%s\n' 'FAIL sqlite: Python unavailable' >&2
    FAILED=1
fi

if ((FAILED == 0)); then
    printf '%s\n' 'AgentIPC openEuler environment check: PASS'
    exit 0
fi

printf '%s\n' 'AgentIPC openEuler environment check: FAIL' >&2
exit 1
