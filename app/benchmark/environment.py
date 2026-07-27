"""Safe benchmark environment collection with no credentials."""

import os
import platform
import sys
from datetime import UTC, datetime
from typing import Any


def collect_environment() -> dict[str, Any]:
    """Collect reproducibility metadata without copying environment secrets."""

    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "implementation": platform.python_implementation(),
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }

