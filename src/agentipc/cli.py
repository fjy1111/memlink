import argparse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from agentipc import __version__


_SMOKE_TASK = "Summarize the AgentIPC smoke benchmark evidence."
_SMOKE_ANSWER = "AgentIPC smoke benchmark evidence summarized deterministically."
_SMOKE_KNOWLEDGE = [
    {
        "document_id": "benchmark-smoke-evidence",
        "text": (
            "AgentIPC smoke benchmark exercises deterministic multi-agent "
            "communication, state exchange, and shared memory infrastructure."
        ),
        "keywords": ["AgentIPC", "smoke", "benchmark", "evidence"],
    }
]
_SCENARIO_METRIC_NAMES = (
    "memory_retrieved",
    "memory_used",
    "memory_effective",
    "memory_harmful",
    "tool_call_count",
)


def _int_at_least_one(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _tcp_port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def _non_empty_string(value: str) -> str:
    if value == "":
        raise argparse.ArgumentTypeError("must not be empty")
    return value


@contextmanager
def _offline_text_counting() -> Iterator[None]:
    """Force optional tiktoken counting onto the offline-safe fallback path.

    tiktoken may be installed while its encoding assets are not cached locally.
    In that state, get_encoding() can try to download assets. Core mock CLI
    commands must remain fully offline, so temporarily make the optional loader
    behave as if tiktoken were unavailable. TextCounter already defines that
    condition as the supported ``token_method=unavailable`` fallback.
    """
    from agentipc.evaluation import text_counter as text_counter_module

    original_loader = text_counter_module._load_tiktoken

    def unavailable_tiktoken() -> object:
        raise ImportError("tiktoken disabled for offline AgentIPC CLI command")

    text_counter_module._load_tiktoken = unavailable_tiktoken
    try:
        yield
    finally:
        text_counter_module._load_tiktoken = original_loader


def build_parser() -> argparse.ArgumentParser:
    """Build the AgentIPC command-line parser."""
    parser = argparse.ArgumentParser(prog="agentipc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Show the AgentIPC version")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run offline environment checks",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit one machine-readable JSON document",
    )

    demo_parser = subparsers.add_parser(
        "demo",
        help="Run the offline A/B/D AgentIPC demo",
    )
    demo_parser.add_argument(
        "--provider",
        choices=("mock",),
        required=True,
        help="Provider to use for the demo",
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Run the offline A/B/C/D benchmark suite",
    )
    benchmark_parser.add_argument(
        "--suite",
        choices=("smoke",),
        default="smoke",
        help="Benchmark suite to run (default: smoke)",
    )
    benchmark_parser.add_argument(
        "--repeat",
        type=_int_at_least_one,
        default=1,
        help="Number of deterministic repetitions (default: 1)",
    )
    benchmark_parser.add_argument(
        "--seed",
        type=_non_negative_int,
        default=42,
        help="Initial random seed (default: 42)",
    )
    benchmark_parser.add_argument(
        "--provider",
        choices=("mock",),
        default="mock",
        help="Provider to use (default: mock)",
    )
    benchmark_parser.add_argument(
        "--results-root",
        default="results",
        help="Root directory for benchmark results (default: results)",
    )

    scenario_parser = subparsers.add_parser(
        "run-scenario",
        help="Run a continuous Experiment D scenario",
    )
    scenario_parser.add_argument(
        "scenario",
        choices=("knowledge", "codeact"),
        help="Scenario to run",
    )
    scenario_parser.add_argument(
        "--provider",
        choices=("mock",),
        default="mock",
        help="Provider to use (default: mock)",
    )
    scenario_parser.add_argument(
        "--seed",
        type=_non_negative_int,
        default=42,
        help="Random seed (default: 42)",
    )
    scenario_parser.add_argument(
        "--results-root",
        default="results",
        help="Root directory for scenario results (default: results)",
    )
    scenario_parser.add_argument(
        "--scenario-root",
        default="tests/scenarios",
        help="Root containing scenario fixtures (default: tests/scenarios)",
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Run the local AgentIPC Dashboard",
    )
    dashboard_parser.add_argument(
        "--host",
        type=_non_empty_string,
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
    dashboard_parser.add_argument(
        "--port",
        type=_tcp_port,
        default=8000,
        help="TCP port to bind (default: 8000)",
    )
    dashboard_parser.add_argument(
        "--results-dir",
        type=_non_empty_string,
        default="results",
        help="Benchmark results directory (default: results)",
    )
    return parser


def _write_json_file(path: object, payload: object) -> None:
    import json
    from pathlib import Path

    resolved_path = Path(path)  # type: ignore[arg-type]
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    with resolved_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json_text)
        stream.write("\n")


def _run_benchmark_command(
    *,
    suite: str,
    repeat: int,
    seed: int,
    provider: str,
    results_root: str,
) -> int:
    from agentipc.agents.executor import ExecutorAgent
    from agentipc.agents.planner import PlannerAgent
    from agentipc.agents.retriever import RetrieverAgent
    from agentipc.agents.summarizer import SummarizerAgent
    from agentipc.artifacts.store import ArtifactStore
    from agentipc.config import AgentIPCConfig
    from agentipc.evaluation.env import capture_environment_snapshot
    from agentipc.evaluation.experiment import ExperimentConfig
    from agentipc.evaluation.io import (
        append_raw_record,
        create_result_dir,
        summarize_raw_records,
        write_summary,
    )
    from agentipc.evaluation.metrics import MetricsCollector
    from agentipc.evaluation.report import write_markdown_report
    from agentipc.evaluation.runner import run_abcd_suite
    from agentipc.evaluation.trace import TraceLogger
    from agentipc.memory.service import MemoryService
    from agentipc.memory.sqlite_store import SQLiteMemoryStore
    from agentipc.memory.vector_index import VectorIndex
    from agentipc.protocol.registry import CapabilityRegistry
    from agentipc.providers.factory import ProviderBundle
    from agentipc.providers.hash_embedding import HashEmbeddingProvider
    from agentipc.providers.mock_llm import MockLLMProvider
    from agentipc.runtime.agent_registry import AgentRegistry
    from agentipc.runtime.context import RunContext
    from agentipc.state.hub import StateHub

    if suite != "smoke":
        raise ValueError("benchmark currently supports only suite='smoke'")
    if provider != "mock":
        raise ValueError("benchmark currently supports only provider='mock'")

    result_dir = create_result_dir(results_root, "benchmark-smoke")
    environment_config = AgentIPCConfig(
        llm_provider="mock",
        embedding_provider="hash",
        random_seed=seed,
    )
    environment = capture_environment_snapshot(environment_config)
    _write_json_file(
        result_dir / "environment.json",
        environment.model_dump(mode="json"),
    )

    resources: list[tuple[StateHub, SQLiteMemoryStore]] = []

    def run_factory(
        experiment: ExperimentConfig,
        task_index: int,
        run_index: int,
        current_seed: int,
        task: str,
    ) -> tuple[RunContext, AgentRegistry]:
        del task
        experiment_name = experiment.name.value
        run_root = (
            result_dir
            / "runtime"
            / (
                f"{experiment_name}-task{task_index:02d}-"
                f"run{run_index:02d}-seed{current_seed}"
            )
        )
        config = AgentIPCConfig(
            llm_provider="mock",
            embedding_provider="hash",
            random_seed=current_seed,
        )
        provider_bundle = ProviderBundle(
            llm=MockLLMProvider(default_text=_SMOKE_ANSWER),
            embedding=HashEmbeddingProvider(dim=64),
        )
        memory_store = SQLiteMemoryStore(run_root / "memory")
        state_hub = StateHub(transport="inproc")
        resources.append((state_hub, memory_store))
        memory_service = MemoryService(
            memory_store,
            provider_bundle.embedding,
            VectorIndex(provider_bundle.embedding.dim),
        )

        agents = AgentRegistry()
        agents.register(PlannerAgent())
        agents.register(RetrieverAgent(knowledge=_SMOKE_KNOWLEDGE))
        agents.register(ExecutorAgent())
        agents.register(SummarizerAgent())

        ctx = RunContext(
            trace_id=(
                f"benchmark-{experiment_name}-task{task_index}-"
                f"run{run_index}-seed{current_seed}-trace"
            ),
            task_id=(
                f"benchmark-{experiment_name}-task{task_index}-"
                f"run{run_index}-seed{current_seed}"
            ),
            mode=experiment.mode,
            config=config,
            registry=CapabilityRegistry(),
            state_hub=state_hub,
            artifact_store=ArtifactStore(run_root / "artifacts"),
            memory_service=memory_service,
            metrics=MetricsCollector(),
            trace_logger=TraceLogger(run_root / "trace.jsonl"),
            provider_bundle=provider_bundle,
            use_state=experiment.use_state,
            use_memory=experiment.use_memory,
            use_sandbox=False,
        )
        return ctx, agents

    seeds = [seed + offset for offset in range(repeat)]
    try:
        records = run_abcd_suite(
            tasks=[_SMOKE_TASK],
            seeds=seeds,
            run_factory=run_factory,
        )
    finally:
        cleanup_error: Exception | None = None
        for state_hub, memory_store in reversed(resources):
            try:
                state_hub.close()
            except Exception as exc:  # pragma: no cover - defensive cleanup
                cleanup_error = cleanup_error or exc
            try:
                memory_store.close()
            except Exception as exc:  # pragma: no cover - defensive cleanup
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            raise RuntimeError("failed to clean up benchmark resources") from cleanup_error

    raw_path = result_dir / "raw.jsonl"
    for record in records:
        append_raw_record(raw_path, record)

    summary = summarize_raw_records(records)
    write_summary(result_dir / "summary.json", summary)
    write_markdown_report(result_dir / "report.md", summary)

    print(f"result directory: {result_dir}")
    print(f"record count: {len(records)}")
    return 0 if all(record.run_result.success for record in records) else 1


def _knowledge_provider_bundle(tasks: list[object]) -> object:
    from agentipc.providers.factory import ProviderBundle
    from agentipc.providers.hash_embedding import HashEmbeddingProvider
    from agentipc.providers.mock_llm import MockLLMProvider

    keyword_responses: dict[str, str] = {}
    for task in tasks:
        query = task.query  # type: ignore[attr-defined]
        answer = "；".join(task.expected.answer_contains)  # type: ignore[attr-defined]
        previous = keyword_responses.get(query)
        if previous is not None and previous != answer:
            raise ValueError("duplicate knowledge query has inconsistent expected answer")
        keyword_responses[query] = answer

    return ProviderBundle(
        llm=MockLLMProvider(keyword_responses=keyword_responses),
        embedding=HashEmbeddingProvider(dim=64),
    )


def _scenario_payload(
    *,
    scenario: str,
    provider: str,
    seed: int,
    results: list[object],
) -> dict[str, object]:
    metrics_totals = {name: 0 for name in _SCENARIO_METRIC_NAMES}
    rounds: list[dict[str, object]] = []
    runtime_success_count = 0
    evaluation_success_count = 0

    for result in results:
        run_record = result.run_record  # type: ignore[attr-defined]
        evaluation = result.evaluation  # type: ignore[attr-defined]
        runtime_success = run_record.run_result.success
        if runtime_success:
            runtime_success_count += 1
        if evaluation.success:
            evaluation_success_count += 1

        metrics = run_record.run_result.metrics
        for name in _SCENARIO_METRIC_NAMES:
            metrics_totals[name] += metrics[name]

        round_payload: dict[str, object] = {
            "round": result.task.round,  # type: ignore[attr-defined]
            "task_hash": run_record.task_hash,
            "runtime_success": runtime_success,
            "evaluation": evaluation.model_dump(mode="json"),
        }
        if scenario == "codeact":
            round_payload["execution_operation"] = (
                result.execution["operation"]  # type: ignore[attr-defined]
            )
        rounds.append(round_payload)

    return {
        "kind": "scenario",
        "scenario": scenario,
        "experiment": "D",
        "provider": provider,
        "seed": seed,
        "round_count": len(results),
        "runtime_success_count": runtime_success_count,
        "evaluation_success_count": evaluation_success_count,
        "metrics_totals": metrics_totals,
        "rounds": rounds,
    }


def _run_scenario_command(
    *,
    scenario: str,
    provider: str,
    seed: int,
    results_root: str,
    scenario_root: str,
) -> int:
    from pathlib import Path

    from agentipc.config import AgentIPCConfig
    from agentipc.evaluation.env import capture_environment_snapshot
    from agentipc.evaluation.io import append_raw_record, create_result_dir
    from agentipc.providers.factory import ProviderBundle
    from agentipc.providers.hash_embedding import HashEmbeddingProvider
    from agentipc.providers.mock_llm import MockLLMProvider
    from agentipc.scenarios.codeact_chain import run_codeact_chain
    from agentipc.scenarios.knowledge_chain import run_knowledge_chain
    from agentipc.scenarios.knowledge_loader import load_knowledge_documents
    from agentipc.scenarios.models import load_codeact_tasks, load_knowledge_tasks

    if provider != "mock":
        raise ValueError("run-scenario currently supports only provider='mock'")

    root = Path(scenario_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"scenario root does not exist or is not a directory: {root}")

    config = AgentIPCConfig(
        llm_provider="mock",
        embedding_provider="hash",
        random_seed=seed,
    )

    if scenario == "knowledge":
        fixture_root = root / "knowledge_chain"
        tasks_path = fixture_root / "tasks.json"
        knowledge_root = fixture_root / "knowledge"
        tasks = load_knowledge_tasks(tasks_path)
        documents = load_knowledge_documents(knowledge_root)
        if len(tasks) != 10:
            raise ValueError("knowledge scenario requires exactly 10 rounds")
        provider_bundle = _knowledge_provider_bundle(tasks)
        result_dir = create_result_dir(results_root, "scenario-knowledge")
        _write_json_file(
            result_dir / "environment.json",
            capture_environment_snapshot(config).model_dump(mode="json"),
        )
        results = run_knowledge_chain(
            tasks=tasks,
            documents=documents,
            work_root=result_dir / "work",
            config=config,
            provider_bundle=provider_bundle,  # type: ignore[arg-type]
        )
    elif scenario == "codeact":
        fixture_root = root / "codeact_chain"
        tasks_path = fixture_root / "tasks.json"
        tasks = load_codeact_tasks(tasks_path)
        if len(tasks) != 10:
            raise ValueError("codeact scenario requires exactly 10 rounds")
        provider_bundle = ProviderBundle(
            llm=MockLLMProvider(default_text="deterministic codeact answer"),
            embedding=HashEmbeddingProvider(dim=64),
        )
        result_dir = create_result_dir(results_root, "scenario-codeact")
        _write_json_file(
            result_dir / "environment.json",
            capture_environment_snapshot(config).model_dump(mode="json"),
        )
        results = run_codeact_chain(
            tasks=tasks,
            fixture_root=fixture_root,
            work_root=result_dir / "work",
            config=config,
            provider_bundle=provider_bundle,
        )
    else:
        raise ValueError(f"unknown scenario: {scenario}")

    raw_path = result_dir / "raw.jsonl"
    for result in results:
        append_raw_record(raw_path, result.run_record)

    payload = _scenario_payload(
        scenario=scenario,
        provider=provider,
        seed=seed,
        results=results,
    )
    _write_json_file(result_dir / "scenario.json", payload)

    round_count = len(results)
    success_count = sum(
        1
        for result in results
        if result.run_record.run_result.success and result.evaluation.success
    )
    print(f"scenario: {scenario}")
    print(f"result directory: {result_dir}")
    print(f"round count: {round_count}")
    print(f"success count: {success_count}")
    return 0 if success_count == round_count else 1


def _load_dashboard_runtime() -> tuple[Callable[..., object], Callable[..., object]]:
    try:
        import uvicorn
        from agentipc.dashboard.app import create_app
    except ImportError as exc:
        raise RuntimeError(
            "dashboard dependencies are not installed; install agentipc[dashboard]"
        ) from exc

    return uvicorn.run, create_app


def _run_dashboard_command(
    *,
    host: str,
    port: int,
    results_dir: str,
) -> int:
    run_server, create_app = _load_dashboard_runtime()
    app = create_app(results_dir=results_dir)

    print("AgentIPC Dashboard")
    print(f"URL: http://{host}:{port}/dashboard/")
    print(f"Results: {results_dir}")

    run_server(
        app,
        host=host,
        port=port,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the AgentIPC command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "doctor":
        from agentipc.doctor import render_doctor_human, render_doctor_json, run_doctor

        report = run_doctor()
        if args.json_output:
            print(render_doctor_json(report))
        else:
            print(render_doctor_human(report))
        return 0 if report.ok else 1

    if args.command == "demo":
        from agentipc.demo import render_demo, run_demo

        with _offline_text_counting():
            report = run_demo(provider=args.provider)
        print(render_demo(report))
        return 0

    try:
        if args.command == "benchmark":
            with _offline_text_counting():
                return _run_benchmark_command(
                    suite=args.suite,
                    repeat=args.repeat,
                    seed=args.seed,
                    provider=args.provider,
                    results_root=args.results_root,
                )

        if args.command == "run-scenario":
            with _offline_text_counting():
                return _run_scenario_command(
                    scenario=args.scenario,
                    provider=args.provider,
                    seed=args.seed,
                    results_root=args.results_root,
                    scenario_root=args.scenario_root,
                )

        if args.command == "dashboard":
            return _run_dashboard_command(
                host=args.host,
                port=args.port,
                results_dir=args.results_dir,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        import sys

        print(f"agentipc: error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
