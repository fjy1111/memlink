"""Command-line demonstration for text and structured communication modes."""

import argparse
import asyncio
import json
import sys
from typing import Sequence

from app.agents.base import AgentExecutionError
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.llm import LLMClientError
from app.models.domain import CommunicationMode, LLMBackend, TaskCreate
from app.runtime.orchestrator import OrchestrationError, TaskOrchestrator

EXAMPLES_FILE = PROJECT_ROOT / "data" / "examples" / "continuous_tasks.json"


def build_parser() -> argparse.ArgumentParser:
    """Build the small stage-two CLI without external UI dependencies."""

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_demo = subparsers.add_parser(
        "run-demo",
        help="Run one deterministic enterprise incident example.",
    )
    run_demo.add_argument(
        "--mode",
        choices=[mode.value for mode in CommunicationMode],
        default=CommunicationMode.TEXT.value,
    )
    run_demo.add_argument(
        "--backend",
        choices=[backend.value for backend in LLMBackend],
        default=LLMBackend.FAKE.value,
        help="Use Fake offline or DeepSeek from the root .env file.",
    )
    run_demo.add_argument(
        "--group",
        choices=["rag", "api"],
        default="rag",
    )
    run_demo.add_argument(
        "--task-index",
        type=int,
        choices=[1, 2, 3],
        default=1,
    )
    return parser


def load_example(group: str, task_index: int) -> dict[str, str]:
    """Load a checked-in example with no current-working-directory dependency."""

    payload = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    tasks = payload["groups"][group]["tasks"]
    return tasks[task_index - 1]


async def run_demo(
    mode: CommunicationMode,
    backend: LLMBackend,
    group: str,
    task_index: int,
) -> int:
    """Execute one example and print raw run metrics."""

    base_settings = (
        Settings(
            _env_file=None,
            llm_backend="fake",
            deepseek_api_key="",
            deepseek_base_url="",
            deepseek_model="",
            embedding_backend="fake",
            embedding_api_key="",
            embedding_base_url="",
            embedding_model="",
        )
        if backend is LLMBackend.FAKE
        else get_settings()
    )
    settings = base_settings.model_copy(
        update={
            "llm_backend": backend.value,
            "embedding_backend": "fake",
        }
    )
    orchestrator = TaskOrchestrator.from_settings(settings)
    example = load_example(group, task_index)
    result = await orchestrator.run(
        TaskCreate(
            title=example["title"],
            prompt=example["prompt"],
            task_topic=example["task_topic"],
            mode=mode,
            llm_backend=backend,
        )
    )
    metrics = result.metrics
    print(f"任务 ID：{result.task_id}")
    print(f"通信模式：{result.communication_mode.value}")
    print(f"模型后端：{backend.value}")
    if backend is LLMBackend.DEEPSEEK:
        print(f"模型名称：{settings.deepseek_model}")
        print(f"Base URL：{settings.deepseek_base_url}")
        print(
            "API Key 状态："
            + ("已配置" if settings.deepseek_api_key else "未配置")
        )
    print("最终答案：")
    print(result.final_answer)
    print("Agent 执行轨迹：" + " -> ".join(result.agent_trace))
    print(f"消息数量：{metrics.message_count}")
    print(f"估算 Token：{metrics.estimated_token_count}")
    print(f"JSON 序列化字节数：{metrics.json_serialized_bytes}")
    print(f"MessagePack 序列化字节数：{metrics.msgpack_serialized_bytes}")
    print(
        "SemanticState："
        f"{metrics.semantic_state_transfer_count} 次 / "
        f"{metrics.semantic_state_bytes} 字节"
    )
    print(f"共享记忆命中数：{metrics.memory_hit_count}")
    print(
        "复用记忆 ID："
        + (", ".join(metrics.reused_memory_ids) or "无")
    )
    print(f"总耗时：{metrics.total_duration_ms:.3f} ms")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the selected asynchronous demo."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    arguments = build_parser().parse_args(argv)
    if arguments.command == "run-demo":
        try:
            return asyncio.run(
                run_demo(
                    CommunicationMode(arguments.mode),
                    LLMBackend(arguments.backend),
                    arguments.group,
                    arguments.task_index,
                )
            )
        except (
            AgentExecutionError,
            LLMClientError,
            OrchestrationError,
            ValueError,
        ) as exc:
            print(f"运行失败：{exc}", file=sys.stderr)
            return 1
    raise ValueError(f"Unsupported command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
