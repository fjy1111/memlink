"""UI-facing service functions that reuse the existing application layer."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from app.core.config import PROJECT_ROOT, Settings
from app.models import CommunicationMode, TaskCreate, TaskResult
from app.runtime.orchestrator import TaskOrchestrator

ResultT = TypeVar("ResultT")
EXAMPLES_FILE = PROJECT_ROOT / "data" / "examples" / "continuous_tasks.json"
BENCHMARK_RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"


def load_examples(path: Path = EXAMPLES_FILE) -> list[dict[str, str]]:
    """Load checked-in demo tasks in a stable order."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    examples: list[dict[str, str]] = []
    for group_key, group in payload["groups"].items():
        for index, task in enumerate(group["tasks"], start=1):
            examples.append(
                {
                    **task,
                    "group": group_key,
                    "label": f"{group['name']} / {index}. {task['title']}",
                }
            )
    return examples


def deepseek_backend_is_configured(settings: Settings) -> bool:
    """Return whether the DeepSeek chat configuration is complete."""

    return settings.deepseek_is_configured()


def build_orchestrator(
    settings: Settings,
    *,
    backend: str,
    enable_shared_memory: bool,
    enable_semantic_state: bool,
    enable_result_reference: bool,
) -> TaskOrchestrator:
    """Create the configured service without accepting credentials from UI."""

    if backend == "deepseek" and not deepseek_backend_is_configured(settings):
        raise ValueError(
            "DeepSeek 配置不完整：请在项目根目录 .env 中配置 "
            "API Key、Base URL 和模型名称。"
        )
    active = settings.model_copy(
        update={
            "llm_backend": backend,
            "embedding_backend": "fake",
            "enable_shared_memory": enable_shared_memory,
            "enable_semantic_state": enable_semantic_state,
            "enable_result_reference": enable_result_reference,
        }
    )
    return TaskOrchestrator.from_settings(active)


async def run_task(
    orchestrator: TaskOrchestrator,
    *,
    title: str,
    prompt: str,
    task_topic: str,
    mode: CommunicationMode,
) -> TaskResult:
    """Run one real orchestrated task for the page."""

    return await orchestrator.run(
        TaskCreate(
            title=title,
            prompt=prompt,
            task_topic=task_topic,
            mode=mode,
        )
    )


def run_coroutine(coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Run async services safely from Streamlit's synchronous script thread."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def load_benchmark_results(
    results_dir: Path = BENCHMARK_RESULTS_DIR,
) -> dict[str, Any] | None:
    """Load only real stage-three artifacts, returning None when absent."""

    summary_path = results_dir / "benchmark_summary.json"
    stability_path = results_dir / "stability_summary.json"
    if not summary_path.is_file() or not stability_path.is_file():
        return None
    return {
        "summary": json.loads(summary_path.read_text(encoding="utf-8")),
        "stability": json.loads(stability_path.read_text(encoding="utf-8")),
        "results_dir": str(results_dir),
    }
