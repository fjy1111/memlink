from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentipc.agents.executor import ExecutorAgent
from agentipc.agents.planner import PlannerAgent
from agentipc.agents.retriever import RetrieverAgent
from agentipc.agents.summarizer import SummarizerAgent
from agentipc.artifacts.store import ArtifactStore
from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import (
    EXPERIMENT_A,
    EXPERIMENT_D,
    ExperimentConfig,
)
from agentipc.evaluation.metrics import MetricsCollector
from agentipc.evaluation.runner import run_single
from agentipc.evaluation.text_counter import TextCounter
from agentipc.evaluation.trace import TraceLogger
from agentipc.experiments.real_bailian.config import load_real_bailian_config
from agentipc.experiments.real_bailian.evaluate import (
    evaluate_normalized_knowledge_answer,
)
from agentipc.experiments.real_bailian.recording_executor import (
    RecordingExecutorAgent,
)
from agentipc.experiments.real_bailian.runner import (
    REAL_API_MAX_RETRIES,
    REAL_API_TIMEOUT_SEC,
    build_recording_provider_bundle,
)
from agentipc.memory.service import MemoryService
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.memory.vector_index import VectorIndex
from agentipc.protocol.registry import CapabilityRegistry
from agentipc.providers.factory import ProviderBundle
from agentipc.runtime.agent_registry import AgentRegistry
from agentipc.runtime.context import RunContext
from agentipc.scenarios.codeact_chain import (
    _build_runtime_task,
    _validate_fixture_root,
)
from agentipc.scenarios.codeact_eval import evaluate_codeact_execution
from agentipc.scenarios.knowledge_loader import load_knowledge_documents
from agentipc.scenarios.models import load_codeact_tasks, load_knowledge_tasks
from agentipc.state.hub import StateHub


_CONFIGS: tuple[tuple[str, ExperimentConfig, bool], ...] = (
    ("A-Text", EXPERIMENT_A, False),
    ("D-Full", EXPERIMENT_D, True),
)

_INFRASTRUCTURE_ERROR_TYPES = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
    }
)


def run_e8(
    *,
    root: Path,
    result_dir: Path,
    repeat: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be >= 1")
    _require_wire_tokenizer()

    secret = load_real_bailian_config()
    llm_recorder, embedding_recorder = build_recording_provider_bundle(secret)
    provider_bundle = ProviderBundle(
        llm=llm_recorder,
        embedding=embedding_recorder,
    )
    provider_metadata = {
        **secret.public_fields(),
        "timeout_sec": REAL_API_TIMEOUT_SEC,
        "max_retries": REAL_API_MAX_RETRIES,
    }
    git_sha = _read_git_sha(root)

    knowledge_tasks = load_knowledge_tasks(
        root / "tests/scenarios/knowledge_chain/tasks.json"
    )
    knowledge_base = [task for task in knowledge_tasks if 1 <= task.round <= 5]
    if [task.round for task in knowledge_base] != [1, 2, 3, 4, 5]:
        raise ValueError("E8 Knowledge workload requires rounds 1..5")

    documents = load_knowledge_documents(
        root / "tests/scenarios/knowledge_chain/knowledge"
    )
    knowledge_data = [
        {
            "document_id": document.document_id,
            "text": document.body,
            "keywords": list(document.tags),
        }
        for document in documents
    ]

    codeact_tasks = load_codeact_tasks(
        root / "tests/scenarios/codeact_chain/tasks.json"
    )
    codeact_base = [task for task in codeact_tasks if 1 <= task.round <= 5]
    if [task.round for task in codeact_base] != [1, 2, 3, 4, 5]:
        raise ValueError("E8 CodeAct workload requires rounds 1..5")

    fixture_root = _validate_fixture_root(root / "tests/scenarios/codeact_chain")
    codeact_runtime = {
        task.round: _build_runtime_task(task, fixture_root)
        for task in codeact_base
    }

    rows: list[dict[str, Any]] = []
    for repeat_index in range(repeat):
        repeat_number = repeat_index + 1
        runtime_config = AgentIPCConfig(
            llm_provider="openai",
            embedding_provider="openai",
            random_seed=42 + repeat_index,
        )
        repeat_root = result_dir / f"repeat-{repeat_number:03d}" / "e8"

        # Alternate config order across repeats to reduce systematic
        # provider-load / temporal-order bias.
        config_order = (
            _CONFIGS if repeat_index % 2 == 0 else tuple(reversed(_CONFIGS))
        )

        for config_name, experiment, fast_path in config_order:
            slug = config_name.lower().replace("-", "_")
            rows.extend(
                _run_knowledge_config(
                    config_name=config_name,
                    experiment=experiment,
                    fast_path=fast_path,
                    tasks=knowledge_base,
                    knowledge=knowledge_data,
                    runtime_config=runtime_config,
                    provider_bundle=provider_bundle,
                    repeat_number=repeat_number,
                    work_root=repeat_root / "knowledge" / slug,
                )
            )
            rows.extend(
                _run_codeact_config(
                    config_name=config_name,
                    experiment=experiment,
                    fast_path=fast_path,
                    tasks=codeact_base,
                    runtime_tasks=codeact_runtime,
                    runtime_config=runtime_config,
                    provider_bundle=provider_bundle,
                    repeat_number=repeat_number,
                    work_root=repeat_root / "codeact" / slug,
                )
            )

    _verify_task_integrity(rows)
    expected_rows = repeat * 2 * 2 * 10
    if len(rows) != expected_rows:
        raise RuntimeError(f"E8 expected {expected_rows} rows, got {len(rows)}")

    return rows, _aggregate_e8(
        rows,
        repeat=repeat,
        provider=provider_metadata,
        git_sha=git_sha,
    )


def _run_knowledge_config(
    *,
    config_name: str,
    experiment: ExperimentConfig,
    fast_path: bool,
    tasks,
    knowledge: list[dict[str, object]],
    runtime_config: AgentIPCConfig,
    provider_bundle: ProviderBundle,
    repeat_number: int,
    work_root: Path,
) -> list[dict[str, Any]]:
    work_root.mkdir(parents=True, exist_ok=False)
    (work_root / "traces").mkdir()
    store = SQLiteMemoryStore(work_root / "memory")
    rows: list[dict[str, Any]] = []
    try:
        memory_service = MemoryService(
            store,
            provider_bundle.embedding,
            VectorIndex(provider_bundle.embedding.dim),
        )
        schedule = [(task, False) for task in tasks] + [
            (task, True) for task in tasks
        ]
        for sequence, (task, is_repeat) in enumerate(schedule, start=1):
            state_hub = StateHub(transport="shm")
            try:
                metrics = MetricsCollector()
                task_id = (
                    f"e8-knowledge-r{repeat_number}-"
                    f"{config_name}-{sequence:02d}"
                )
                ctx = RunContext(
                    trace_id=f"{task_id}-trace",
                    task_id=task_id,
                    mode=experiment.mode,
                    config=runtime_config,
                    registry=CapabilityRegistry(),
                    state_hub=state_hub,
                    artifact_store=ArtifactStore(
                        work_root / "artifacts" / f"task-{sequence:02d}"
                    ),
                    memory_service=memory_service,
                    metrics=metrics,
                    trace_logger=TraceLogger(
                        work_root / "traces" / f"task-{sequence:02d}.jsonl"
                    ),
                    provider_bundle=provider_bundle,
                    use_state=experiment.use_state,
                    use_memory=experiment.use_memory,
                    use_sandbox=False,
                )
                agents = AgentRegistry()
                agents.register(PlannerAgent())
                agents.register(RetrieverAgent(knowledge=knowledge))
                agents.register(ExecutorAgent())
                agents.register(SummarizerAgent())

                record = run_single(
                    experiment=experiment,
                    task=task.query,
                    ctx=ctx,
                    agent_registry=agents,
                    memory_fast_path=fast_path,
                )
                evaluation = evaluate_normalized_knowledge_answer(
                    task,
                    record.run_result.answer,
                )
                _persist_validation_if_written(
                    memory_service,
                    task_id=task_id,
                    passed=evaluation.success,
                    enabled=experiment.use_memory,
                )
                rows.append(
                    _row(
                        group="knowledge",
                        config_name=config_name,
                        repeat_number=repeat_number,
                        sequence=sequence,
                        source_round=task.round,
                        is_repeat=is_repeat,
                        task_hash=record.task_hash,
                        runtime_success=record.run_result.success,
                        evaluation_pass=evaluation.success,
                        error=record.run_result.error,
                        metrics=dict(record.run_result.metrics),
                    )
                )
            finally:
                state_hub.close()
    finally:
        store.close()
    return rows


def _run_codeact_config(
    *,
    config_name: str,
    experiment: ExperimentConfig,
    fast_path: bool,
    tasks,
    runtime_tasks: dict[int, str],
    runtime_config: AgentIPCConfig,
    provider_bundle: ProviderBundle,
    repeat_number: int,
    work_root: Path,
) -> list[dict[str, Any]]:
    work_root.mkdir(parents=True, exist_ok=False)
    (work_root / "traces").mkdir()
    store = SQLiteMemoryStore(work_root / "memory")
    rows: list[dict[str, Any]] = []
    try:
        memory_service = MemoryService(
            store,
            provider_bundle.embedding,
            VectorIndex(provider_bundle.embedding.dim),
        )
        schedule = [(task, False) for task in tasks] + [
            (task, True) for task in tasks
        ]
        for sequence, (task, is_repeat) in enumerate(schedule, start=1):
            runtime_task = runtime_tasks[task.round]
            state_hub = StateHub(transport="shm")
            recorder = RecordingExecutorAgent()
            try:
                metrics = MetricsCollector()
                task_id = (
                    f"e8-codeact-r{repeat_number}-"
                    f"{config_name}-{sequence:02d}"
                )
                ctx = RunContext(
                    trace_id=f"{task_id}-trace",
                    task_id=task_id,
                    mode=experiment.mode,
                    config=runtime_config,
                    registry=CapabilityRegistry(),
                    state_hub=state_hub,
                    artifact_store=ArtifactStore(
                        work_root / "artifacts" / f"task-{sequence:02d}"
                    ),
                    memory_service=memory_service,
                    metrics=metrics,
                    trace_logger=TraceLogger(
                        work_root / "traces" / f"task-{sequence:02d}.jsonl"
                    ),
                    provider_bundle=provider_bundle,
                    use_state=experiment.use_state,
                    use_memory=experiment.use_memory,
                    use_sandbox=True,
                )
                agents = AgentRegistry()
                agents.register(PlannerAgent())
                agents.register(RetrieverAgent(knowledge=[]))
                agents.register(recorder)
                agents.register(SummarizerAgent())

                record = run_single(
                    experiment=experiment,
                    task=runtime_task,
                    ctx=ctx,
                    agent_registry=agents,
                    memory_fast_path=fast_path,
                )

                execution = (
                    recorder.executions[-1]
                    if recorder.executions
                    else None
                )
                if (
                    execution is None
                    and record.run_result.metrics.get("fast_path_hit_count", 0)
                ):
                    cached = memory_service.get_exact_validated_result(runtime_task)
                    if cached is not None:
                        maybe_execution = cached.payload.get("execution")
                        if type(maybe_execution) is dict:
                            execution = maybe_execution

                evaluation_pass = bool(
                    type(execution) is dict
                    and evaluate_codeact_execution(task, execution).success
                )
                _persist_validation_if_written(
                    memory_service,
                    task_id=task_id,
                    passed=evaluation_pass,
                    enabled=experiment.use_memory,
                )
                rows.append(
                    _row(
                        group="codeact",
                        config_name=config_name,
                        repeat_number=repeat_number,
                        sequence=sequence,
                        source_round=task.round,
                        is_repeat=is_repeat,
                        task_hash=record.task_hash,
                        runtime_success=record.run_result.success,
                        evaluation_pass=evaluation_pass,
                        error=record.run_result.error,
                        metrics=dict(record.run_result.metrics),
                    )
                )
            finally:
                state_hub.close()
    finally:
        store.close()
    return rows


def _persist_validation_if_written(
    memory_service: MemoryService,
    *,
    task_id: str,
    passed: bool,
    enabled: bool,
) -> None:
    if not enabled:
        return
    memory_id = f"mem_{task_id}"
    if memory_service.get(memory_id) is not None:
        memory_service.mark_validated_result(memory_id, passed=passed)


def _row(
    *,
    group: str,
    config_name: str,
    repeat_number: int,
    sequence: int,
    source_round: int,
    is_repeat: bool,
    task_hash: str,
    runtime_success: bool,
    evaluation_pass: bool,
    error: dict[str, Any] | None,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    fast_hit = int(metrics.get("fast_path_hit_count", 0))
    return {
        "experiment": "E8",
        "group": group,
        "config": config_name,
        "repeat": repeat_number,
        "sequence": sequence,
        "phase": "repeat" if is_repeat else "new",
        "source_round": source_round,
        "task_hash": task_hash,
        "runtime_success": runtime_success,
        "evaluation_pass": evaluation_pass,
        "error": error,
        "validated_fast_path_effective": int(
            bool(fast_hit and evaluation_pass)
        ),
        "validated_fast_path_harmful": int(
            bool(fast_hit and not evaluation_pass)
        ),
        "metrics": metrics,
    }


def _verify_task_integrity(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            int(row["repeat"]),
            str(row["group"]),
            int(row["sequence"]),
        )
        grouped.setdefault(key, []).append(row)

    for key, selected in grouped.items():
        configs = {str(row["config"]) for row in selected}
        if configs != {"A-Text", "D-Full"}:
            raise RuntimeError(
                f"E8 benchmark integrity violation at {key}: "
                f"configs={sorted(configs)!r}"
            )
        if len(selected) != 2:
            raise RuntimeError(
                f"E8 benchmark integrity violation at {key}: "
                f"expected 2 rows, got {len(selected)}"
            )

        task_hashes = {str(row["task_hash"]) for row in selected}
        source_rounds = {int(row["source_round"]) for row in selected}
        phases = {str(row["phase"]) for row in selected}
        if (
            len(task_hashes) != 1
            or len(source_rounds) != 1
            or len(phases) != 1
        ):
            raise RuntimeError(
                f"E8 benchmark integrity violation at {key}: "
                "A-Text and D-Full did not receive identical tasks"
            )


def _aggregate_e8(
    rows: list[dict[str, Any]],
    *,
    repeat: int,
    provider: dict[str, Any] | None = None,
    git_sha: str | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot aggregate an empty E8 row set")

    groups: dict[str, Any] = {}
    for group in ("knowledge", "codeact"):
        selected = [row for row in rows if row["group"] == group]
        groups[group] = _aggregate_scope(selected)

    overall = _aggregate_scope(rows)
    overall_configs = overall["configs"]
    infrastructure_failure_count = sum(
        item["infrastructure_failure_count"]
        for item in overall_configs.values()
    )
    infrastructure_failure_types = sorted(
        {
            error_type
            for item in overall_configs.values()
            for error_type in item["infrastructure_failure_types"]
        }
    )

    infrastructure_valid = infrastructure_failure_count == 0
    comparison_valid = overall["comparison_valid"]
    quality_gate_pass = all(
        item["evaluation_pass_rate"] == 1.0
        for item in overall_configs.values()
    )

    full_new = overall["phases"]["new"]["configs"]["D-Full"]
    full_repeat = overall["phases"]["repeat"]["configs"]["D-Full"]
    fast_path_safety_pass = bool(
        full_new["total_fast_path_hits"] == 0
        and full_repeat["total_fast_path_hits"] == full_repeat["task_count"]
        and full_repeat["validated_fast_path_harmful_count"] == 0
        and full_repeat["evaluation_pass_rate"] == 1.0
    )

    expected_rows = repeat * 2 * 2 * 10
    integrity_pass = len(rows) == expected_rows
    passed = bool(
        integrity_pass
        and comparison_valid
        and quality_gate_pass
        and fast_path_safety_pass
    )

    return {
        "experiment": "E8",
        "repeat": repeat,
        "row_count": len(rows),
        "expected_row_count": expected_rows,
        "passed": passed,
        "integrity_pass": integrity_pass,
        "infrastructure_valid": infrastructure_valid,
        "infrastructure_failure_count": infrastructure_failure_count,
        "infrastructure_failure_types": infrastructure_failure_types,
        "comparison_valid": comparison_valid,
        "quality_gate_pass": quality_gate_pass,
        "fast_path_safety_pass": fast_path_safety_pass,
        "workload": "per group: 5 new tasks + the exact same 5 tasks repeated",
        "repeat_ratio": 0.5,
        "baseline": (
            "A-Text: TEXT mode, no non-text state, no shared memory reuse"
        ),
        "full_system": (
            "D-Full: structured protocol + ArtifactRef + "
            "SharedMemory/StateRef + shared memory + "
            "evaluator-validated exact-result Memory Fast Path"
        ),
        "fairness": (
            "same tasks, source rounds, provider, model, seed per repeat, "
            "evaluators, artifact store, and success criteria; only "
            "infrastructure feature flags differ"
        ),
        "measurement_note": (
            "TextTransport materializes references into rendered text before "
            "wire accounting. Structured D-Full counts compact encoded "
            "AgentEnvelope bytes. state_bytes and artifact_payload_bytes are "
            "disclosed separately and are not added to Agent-to-Agent wire bytes."
        ),
        "provider": {} if provider is None else provider,
        "git_sha": git_sha,
        "groups": groups,
        "overall": overall,
    }


def _aggregate_scope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot aggregate an empty E8 scope")

    configs = {
        name: _aggregate_rows([row for row in rows if row["config"] == name])
        for name, _, _ in _CONFIGS
    }

    phases: dict[str, Any] = {}
    for phase in ("new", "repeat"):
        phase_rows = [row for row in rows if row["phase"] == phase]
        phase_configs = {
            name: _aggregate_rows(
                [row for row in phase_rows if row["config"] == name]
            )
            for name, _, _ in _CONFIGS
        }
        phases[phase] = {
            "configs": phase_configs,
            "comparison_valid": _comparison_valid(phase_configs),
            "a_vs_full": _delta(
                phase_configs["A-Text"],
                phase_configs["D-Full"],
            ),
        }

    return {
        "configs": configs,
        "comparison_valid": _comparison_valid(configs),
        "a_vs_full": _delta(configs["A-Text"], configs["D-Full"]),
        "phases": phases,
    }


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot aggregate an empty E8 row set")
    n = len(rows)

    def total(metric: str) -> float:
        return sum(float(row["metrics"].get(metric, 0)) for row in rows)

    infrastructure_rows = [
        row for row in rows if _is_infrastructure_failure(row)
    ]
    non_infrastructure_rows = [
        row for row in rows if not _is_infrastructure_failure(row)
    ]
    infrastructure_failure_types = sorted(
        {
            str(row["error"]["type"])
            for row in infrastructure_rows
            if type(row.get("error")) is dict and row["error"].get("type")
        }
    )

    fast_hits = int(total("fast_path_hit_count"))
    validated_effective = sum(
        int(row["validated_fast_path_effective"]) for row in rows
    )
    validated_harmful = sum(
        int(row["validated_fast_path_harmful"]) for row in rows
    )
    non_infra_eval_rate = (
        sum(bool(row["evaluation_pass"]) for row in non_infrastructure_rows)
        / len(non_infrastructure_rows)
        if non_infrastructure_rows
        else 0.0
    )

    return {
        "task_count": n,
        "runtime_success_rate": sum(bool(row["runtime_success"]) for row in rows) / n,
        "evaluation_pass_rate": sum(bool(row["evaluation_pass"]) for row in rows) / n,
        "evaluation_pass_rate_excluding_infrastructure": non_infra_eval_rate,
        "infrastructure_failure_count": len(infrastructure_rows),
        "infrastructure_failure_rate": len(infrastructure_rows) / n,
        "infrastructure_failure_types": infrastructure_failure_types,
        "total_message_count": int(total("message_count")),
        "total_text_chars": int(total("text_chars")),
        "total_text_tokens": int(total("text_tokens")),
        "total_wire_chars": int(total("wire_chars")),
        "total_wire_tokens": int(total("wire_tokens")),
        "total_wire_bytes": int(total("wire_bytes")),
        "total_protocol_bytes": int(total("protocol_bytes")),
        "total_state_transfer_count": int(total("state_transfer_count")),
        "total_state_bytes": int(total("state_bytes")),
        "total_artifact_ref_count": int(total("artifact_ref_count")),
        "total_artifact_payload_bytes": int(total("artifact_payload_bytes")),
        "total_memory_retrieved": int(total("memory_retrieved")),
        "total_memory_used": int(total("memory_used")),
        "total_fast_path_hits": fast_hits,
        "fast_path_hit_rate": fast_hits / n,
        "validated_fast_path_effective_count": validated_effective,
        "validated_fast_path_harmful_count": validated_harmful,
        "total_tool_calls": int(total("tool_call_count")),
        "total_llm_prompt_tokens": int(total("llm_prompt_tokens")),
        "total_llm_completion_tokens": int(total("llm_completion_tokens")),
        "total_llm_tokens": int(total("llm_total_tokens")),
        "total_llm_calls": int(total("llm_call_count")),
        "total_latency_ms": total("latency_ms"),
        "mean_latency_ms": total("latency_ms") / n,
    }


def _delta(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, float]:
    return {
        "provider_prompt_token_saving_pct": _reduction_pct(
            baseline["total_llm_prompt_tokens"],
            current["total_llm_prompt_tokens"],
        ),
        "provider_total_token_saving_pct": _reduction_pct(
            baseline["total_llm_tokens"],
            current["total_llm_tokens"],
        ),
        "llm_call_reduction_pct": _reduction_pct(
            baseline["total_llm_calls"],
            current["total_llm_calls"],
        ),
        "message_reduction_pct": _reduction_pct(
            baseline["total_message_count"],
            current["total_message_count"],
        ),
        "wire_token_saving_pct": _reduction_pct(
            baseline["total_wire_tokens"],
            current["total_wire_tokens"],
        ),
        "wire_byte_saving_pct": _reduction_pct(
            baseline["total_wire_bytes"],
            current["total_wire_bytes"],
        ),
        "tool_call_reduction_pct": _reduction_pct(
            baseline["total_tool_calls"],
            current["total_tool_calls"],
        ),
        "latency_reduction_pct": _reduction_pct(
            baseline["total_latency_ms"],
            current["total_latency_ms"],
        ),
    }


def _comparison_valid(configs: dict[str, dict[str, Any]]) -> bool:
    return bool(
        all(
            item["infrastructure_failure_count"] == 0
            for item in configs.values()
        )
        and all(
            item["runtime_success_rate"] == 1.0
            for item in configs.values()
        )
    )


def _is_infrastructure_failure(row: dict[str, Any]) -> bool:
    if bool(row.get("runtime_success")):
        return False
    error = row.get("error")
    return (
        type(error) is dict
        and error.get("type") in _INFRASTRUCTURE_ERROR_TYPES
    )


def _reduction_pct(baseline: float, current: float) -> float:
    if baseline <= 0.0:
        return 0.0
    return (baseline - current) / baseline * 100.0


def _read_git_sha(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    sha = completed.stdout.strip()
    if len(sha) != 40 or any(
        char not in "0123456789abcdef" for char in sha
    ):
        return None
    return sha


def _require_wire_tokenizer() -> None:
    probe = TextCounter().count("AgentIPC E8 tokenizer probe.")
    if probe.token_method == "unavailable":
        raise RuntimeError(
            "E8 requires tiktoken for wire-token accounting; "
            "install with: pip install -e '.[tiktoken]'"
        )
