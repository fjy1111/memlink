from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from agentipc.agents.planner import PlannerAgent
from agentipc.agents.retriever import RetrieverAgent
from agentipc.agents.summarizer import SummarizerAgent
from agentipc.artifacts.store import ArtifactStore
from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import EXPERIMENT_D
from agentipc.evaluation.metrics import MetricsCollector
from agentipc.evaluation.runner import RawRunRecord, run_single
from agentipc.evaluation.trace import TraceLogger
from agentipc.experiments.real_bailian.artifacts import (
    audit_result_secrets,
    create_result_dir,
    utc_now,
    write_json,
    write_jsonl,
)
from agentipc.experiments.real_bailian.config import RealBailianConfig
from agentipc.experiments.real_bailian.environment import capture_environment_manifest
from agentipc.experiments.real_bailian.evaluate import (
    build_memory_validation,
    evaluate_normalized_knowledge_answer,
)
from agentipc.experiments.real_bailian.providers import (
    ProviderUsage,
    RecordingEmbeddingProvider,
    RecordingLLMProvider,
    build_provider_usage,
)
from agentipc.experiments.real_bailian.recording_executor import RecordingExecutorAgent
from agentipc.experiments.real_bailian.report import render_calibration_report
from agentipc.memory.service import MemoryService
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.memory.vector_index import VectorIndex
from agentipc.protocol.registry import CapabilityRegistry
from agentipc.providers.factory import ProviderBundle
from agentipc.providers.openai_compatible import OpenAICompatibleProvider
from agentipc.providers.openai_embedding import OpenAICompatibleEmbeddingProvider
from agentipc.runtime.agent_registry import AgentRegistry
from agentipc.runtime.context import RunContext, RunMode
from agentipc.scenarios.codeact_chain import _build_runtime_task, _validate_fixture_root
from agentipc.scenarios.codeact_eval import evaluate_codeact_execution
from agentipc.scenarios.knowledge_eval import evaluate_knowledge_answer
from agentipc.scenarios.knowledge_loader import load_knowledge_documents
from agentipc.scenarios.models import (
    CodeActTask,
    KnowledgeTask,
    load_codeact_tasks,
    load_knowledge_tasks,
)
from agentipc.state.checksum import array_checksum
from agentipc.state.hub import StateHub
from agentipc.state.plan_vector import PLAN_VECTOR_DIM, encode_plan_vector


_PHASE = "calibration"
REAL_API_TIMEOUT_SEC = 120.0
# OpenAICompatibleProvider fixes max_retries=0 internally.
REAL_API_MAX_RETRIES = 0


def run_calibration(
    *,
    config: RealBailianConfig,
    repo_root: str | Path,
    results_root: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run the paid R001 calibration after the caller has passed the API gate."""
    if not isinstance(config, RealBailianConfig):
        raise TypeError("config must be a RealBailianConfig")
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be an existing directory")

    started_at = utc_now(now)
    output_root = root / "results" if results_root is None else Path(results_root)
    result_dir = create_result_dir(output_root, phase=_PHASE, now=started_at)
    traces_dir = result_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=False)

    environment = capture_environment_manifest(
        config=config,
        repo_root=root,
        started_at=started_at,
        repeat=1,
        task_count=4,
    )
    write_json(result_dir / "environment.json", environment)

    raw_records: list[dict[str, Any]] = []
    llm_recorder: RecordingLLMProvider | None = None
    embedding_recorder: RecordingEmbeddingProvider | None = None

    provider_probe: dict[str, Any] = {"passed": False, "error": "not run"}
    embedding_probe: dict[str, Any] = {"passed": False, "error": "not run"}
    shm_probe: dict[str, Any] = {"passed": False, "error": "not run"}
    knowledge: dict[str, Any] = {"passed": False, "error": "not run", "rounds": []}
    codeact: dict[str, Any] = {"passed": False, "error": "not run", "rounds": []}

    try:
        llm_recorder, embedding_recorder = build_recording_provider_bundle(config)
        provider_probe = run_llm_provider_probe(llm_recorder, config=config)
        embedding_probe = run_embedding_provider_probe(
            embedding_recorder,
            expected_dim=config.embedding_dim,
            config=config,
        )
    except Exception as exc:
        safe = _sanitize_error(exc, config)
        if provider_probe.get("error") == "not run":
            provider_probe = {"passed": False, "error": safe}
        if embedding_probe.get("error") == "not run":
            embedding_probe = {"passed": False, "error": safe}

    try:
        shm_probe = run_shm_probe()
    except Exception as exc:
        shm_probe = {
            "passed": False,
            "error": _sanitize_error(exc, config),
        }

    provider_ready = (
        provider_probe.get("passed") is True
        and embedding_probe.get("passed") is True
        and llm_recorder is not None
        and embedding_recorder is not None
    )
    shm_ready = shm_probe.get("passed") is True

    if provider_ready and shm_ready:
        assert llm_recorder is not None
        assert embedding_recorder is not None
        provider_bundle = ProviderBundle(
            llm=llm_recorder,
            embedding=embedding_recorder,
        )
        runtime_config = AgentIPCConfig(
            llm_provider="openai",
            embedding_provider="openai",
            random_seed=42,
        )

        try:
            knowledge, knowledge_raw = run_knowledge_mini_calibration(
                repo_root=root,
                result_dir=result_dir,
                config=runtime_config,
                provider_bundle=provider_bundle,
                secret_config=config,
            )
            raw_records.extend(knowledge_raw)
        except Exception as exc:
            knowledge = {
                "passed": False,
                "error": _sanitize_error(exc, config),
                "rounds": [],
            }

        try:
            codeact, codeact_raw = run_codeact_mini_calibration(
                repo_root=root,
                result_dir=result_dir,
                config=runtime_config,
                provider_bundle=provider_bundle,
                secret_config=config,
            )
            raw_records.extend(codeact_raw)
        except Exception as exc:
            codeact = {
                "passed": False,
                "error": _sanitize_error(exc, config),
                "rounds": [],
            }
    else:
        reason = "provider/embedding/SHM prerequisite failed; paid mini chains skipped"
        knowledge = {"passed": False, "error": reason, "rounds": []}
        codeact = {"passed": False, "error": reason, "rounds": []}

    usage = (
        build_provider_usage(llm_recorder, embedding_recorder)
        if llm_recorder is not None and embedding_recorder is not None
        else _empty_provider_usage()
    )
    usage_dict = usage.model_dump(mode="json")
    write_json(result_dir / "provider_usage.json", usage_dict)
    write_jsonl(result_dir / "raw.jsonl", raw_records)

    pre_audit_pass = all(
        section.get("passed") is True
        for section in (provider_probe, embedding_probe, shm_probe, knowledge, codeact)
    )
    summary: dict[str, Any] = {
        "phase": _PHASE,
        "real_api": True,
        "provider_probe": provider_probe,
        "embedding_probe": embedding_probe,
        "shm_probe": shm_probe,
        "knowledge": knowledge,
        "codeact": codeact,
        "provider_usage": usage_dict,
        "secret_audit": {"passed": False, "files_scanned": 0},
        "pass": False,
        "passed": False,
    }
    write_json(result_dir / "summary.json", summary)
    (result_dir / "report.md").write_text(
        render_calibration_report(summary),
        encoding="utf-8",
    )

    audit = audit_result_secrets(result_dir, config=config)
    overall = bool(pre_audit_pass and audit["passed"])
    summary["secret_audit"] = audit
    summary["pass"] = overall
    summary["passed"] = overall
    write_json(result_dir / "summary.json", summary)
    (result_dir / "report.md").write_text(
        render_calibration_report(summary),
        encoding="utf-8",
    )

    final_audit = audit_result_secrets(result_dir, config=config)
    if final_audit != audit:
        summary["secret_audit"] = final_audit
        overall = bool(pre_audit_pass and final_audit["passed"])
        summary["pass"] = overall
        summary["passed"] = overall
        write_json(result_dir / "summary.json", summary)
        (result_dir / "report.md").write_text(
            render_calibration_report(summary),
            encoding="utf-8",
        )

    return result_dir, summary


def build_recording_provider_bundle(
    config: RealBailianConfig,
) -> tuple[RecordingLLMProvider, RecordingEmbeddingProvider]:
    llm = OpenAICompatibleProvider(
        model=config.llm_model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout_sec=REAL_API_TIMEOUT_SEC,
    )
    embedding = OpenAICompatibleEmbeddingProvider(
        model=config.embedding_model,
        dim=config.embedding_dim,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout_sec=REAL_API_TIMEOUT_SEC,
    )
    return (
        RecordingLLMProvider(llm, model=config.llm_model),
        RecordingEmbeddingProvider(embedding, model=config.embedding_model),
    )


def run_llm_provider_probe(
    llm: RecordingLLMProvider,
    *,
    config: RealBailianConfig,
) -> dict[str, Any]:
    try:
        response = llm.complete(
            [
                {
                    "role": "system",
                    "content": "Reply with a short non-empty acknowledgement.",
                },
                {
                    "role": "user",
                    "content": "AgentIPC R001 calibration provider probe.",
                },
            ],
            temperature=config.temperature,
        )
        passed = bool(
            response.text.strip()
            and response.prompt_tokens is not None
            and response.prompt_tokens > 0
            and response.completion_tokens is not None
            and response.completion_tokens > 0
            and response.latency_ms > 0.0
        )
        raw = response.raw if isinstance(response.raw, dict) else {}
        return {
            "passed": passed,
            "model": config.llm_model,
            "request_id": _safe_scalar(raw.get("request_id")),
            "finish_reason": _safe_scalar(raw.get("finish_reason")),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": (
                None
                if response.prompt_tokens is None or response.completion_tokens is None
                else response.prompt_tokens + response.completion_tokens
            ),
            "latency_ms": response.latency_ms,
            "answer_non_empty": bool(response.text.strip()),
            "answer_sha256": hashlib.sha256(response.text.encode("utf-8")).hexdigest(),
            "error": None if passed else "provider probe acceptance condition failed",
        }
    except Exception as exc:
        return {"passed": False, "error": _sanitize_error(exc, config)}


def run_embedding_provider_probe(
    embedding: RecordingEmbeddingProvider,
    *,
    expected_dim: int,
    config: RealBailianConfig,
) -> dict[str, Any]:
    try:
        matrix = embedding.embed(["AgentIPC calibration", "shared memory vector"])
        passed = bool(
            isinstance(matrix, np.ndarray)
            and matrix.shape == (2, expected_dim)
            and matrix.dtype == np.dtype(np.float32)
            and np.all(np.isfinite(matrix))
        )
        return {
            "passed": passed,
            "model": config.embedding_model,
            "shape": list(matrix.shape),
            "dtype": str(matrix.dtype),
            "all_finite": bool(np.all(np.isfinite(matrix))),
            "error": None if passed else "embedding probe acceptance condition failed",
        }
    except Exception as exc:
        return {"passed": False, "error": _sanitize_error(exc, config)}


def run_shm_probe() -> dict[str, Any]:
    hub = StateHub(transport="shm")
    ref = None
    try:
        vector = encode_plan_vector(
            {
                "task": "R001 real shared memory calibration",
                "steps": ["retrieve", "execute", "summarize"],
                "requires_execution": False,
            }
        )
        ref = hub.put_array(
            vector,
            kind="calibration_plan_vector",
            summary="R001 real POSIX shared-memory calibration vector",
        )
        resolved = hub.resolve_array(ref)
        checksum_valid = array_checksum(resolved) == ref.checksum
        consumed_norm = float(np.linalg.norm(resolved))
        pre_release_exists = hub.exists(ref)
        passed_before_release = bool(
            ref.transport == "shm"
            and ref.shape == [PLAN_VECTOR_DIM]
            and np.dtype(ref.dtype) == np.dtype(np.float32)
            and ref.nbytes == PLAN_VECTOR_DIM * np.dtype(np.float32).itemsize
            and resolved.shape == (PLAN_VECTOR_DIM,)
            and resolved.dtype == np.dtype(np.float32)
            and checksum_valid
            and consumed_norm > 0.0
            and pre_release_exists
        )
        hub.release(ref)
        released = not hub.exists(ref)
        return {
            "passed": bool(passed_before_release and released),
            "transport": ref.transport,
            "shape": ref.shape,
            "dtype": str(np.dtype(ref.dtype)),
            "nbytes": ref.nbytes,
            "checksum_valid": checksum_valid,
            "consumed_norm": consumed_norm,
            "released": released,
            "error": None if passed_before_release and released else "SHM acceptance condition failed",
        }
    finally:
        if ref is not None:
            hub.release(ref)
        hub.close()


def run_knowledge_mini_calibration(
    *,
    repo_root: Path,
    result_dir: Path,
    config: AgentIPCConfig,
    provider_bundle: ProviderBundle,
    secret_config: RealBailianConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = [
        task
        for task in load_knowledge_tasks(repo_root / "tests/scenarios/knowledge_chain/tasks.json")
        if task.round in (2, 8)
    ]
    _require_rounds(tasks, expected=(2, 8), task_type=KnowledgeTask)
    documents = load_knowledge_documents(repo_root / "tests/scenarios/knowledge_chain/knowledge")
    knowledge_data = [
        {
            "document_id": document.document_id,
            "text": document.body,
            "keywords": list(document.tags),
        }
        for document in documents
    ]

    work_root = result_dir / "knowledge"
    work_root.mkdir(parents=True, exist_ok=False)
    store = SQLiteMemoryStore(work_root / "memory")
    results: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    try:
        memory_service = MemoryService(
            store,
            provider_bundle.embedding,
            VectorIndex(provider_bundle.embedding.dim),
        )
        for task in tasks:
            state_hub = StateHub(transport="shm")
            try:
                metrics = MetricsCollector()
                ctx = RunContext(
                    trace_id=f"real-knowledge-r{task.round}-trace",
                    task_id=f"real-knowledge-r{task.round}",
                    mode=RunMode.STRUCTURED,
                    config=config,
                    registry=CapabilityRegistry(),
                    state_hub=state_hub,
                    artifact_store=ArtifactStore(work_root / "artifacts" / f"round-{task.round:02d}"),
                    memory_service=memory_service,
                    metrics=metrics,
                    trace_logger=TraceLogger(result_dir / "traces" / f"knowledge-round-{task.round:02d}.jsonl"),
                    provider_bundle=provider_bundle,
                    use_state=True,
                    use_memory=True,
                    use_sandbox=False,
                )
                agents = AgentRegistry()
                agents.register(PlannerAgent())
                agents.register(RetrieverAgent(knowledge=knowledge_data))
                agents.register(RecordingExecutorAgent())
                agents.register(SummarizerAgent())

                record = run_single(
                    experiment=EXPERIMENT_D,
                    task=task.query,
                    ctx=ctx,
                    agent_registry=agents,
                )
                round_result = _knowledge_round_result(
                    task,
                    record,
                    secret_config=secret_config,
                )
                results.append(round_result)
                raw.append({"scenario": "knowledge", **round_result})
            finally:
                state_hub.close()
    finally:
        store.close()

    by_round = {item["round"]: item for item in results}
    r2 = by_round[2]
    r8 = by_round[8]
    r8_metrics = r8["metrics"]
    passed = bool(
        r2["evaluation_pass"]
        and r8["evaluation_pass"]
        and r8_metrics.get("memory_retrieved", 0) >= 1
        and r8_metrics.get("memory_used", 0) >= 1
    )
    discrepancy_count = sum(
        1
        for item in results
        if item["memory_validation"]["strict_vs_validated_discrepancy"]
    )
    return (
        {
            "passed": passed,
            "rounds": results,
            "strict_vs_validated_discrepancy_count": discrepancy_count,
            "error": None if passed else "Knowledge mini-chain acceptance condition failed",
        },
        raw,
    )


def run_codeact_mini_calibration(
    *,
    repo_root: Path,
    result_dir: Path,
    config: AgentIPCConfig,
    provider_bundle: ProviderBundle,
    secret_config: RealBailianConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = [
        task
        for task in load_codeact_tasks(repo_root / "tests/scenarios/codeact_chain/tasks.json")
        if task.round in (2, 8)
    ]
    _require_rounds(tasks, expected=(2, 8), task_type=CodeActTask)
    fixture_root = _validate_fixture_root(repo_root / "tests/scenarios/codeact_chain")
    runtime_tasks = {
        task.round: _build_runtime_task(task, fixture_root)
        for task in tasks
    }
    if runtime_tasks[2] != runtime_tasks[8]:
        raise ValueError("CodeAct calibration requires Round 2 and Round 8 runtime code to be identical")

    work_root = result_dir / "codeact"
    work_root.mkdir(parents=True, exist_ok=False)
    store = SQLiteMemoryStore(work_root / "memory")
    results: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    try:
        memory_service = MemoryService(
            store,
            provider_bundle.embedding,
            VectorIndex(provider_bundle.embedding.dim),
        )
        for task in tasks:
            state_hub = StateHub(transport="shm")
            recorder = RecordingExecutorAgent()
            try:
                metrics = MetricsCollector()
                ctx = RunContext(
                    trace_id=f"real-codeact-r{task.round}-trace",
                    task_id=f"real-codeact-r{task.round}",
                    mode=RunMode.STRUCTURED,
                    config=config,
                    registry=CapabilityRegistry(),
                    state_hub=state_hub,
                    artifact_store=ArtifactStore(work_root / "artifacts" / f"round-{task.round:02d}"),
                    memory_service=memory_service,
                    metrics=metrics,
                    trace_logger=TraceLogger(result_dir / "traces" / f"codeact-round-{task.round:02d}.jsonl"),
                    provider_bundle=provider_bundle,
                    use_state=True,
                    use_memory=True,
                    use_sandbox=True,
                )
                agents = AgentRegistry()
                agents.register(PlannerAgent())
                agents.register(RetrieverAgent(knowledge=[]))
                agents.register(recorder)
                agents.register(SummarizerAgent())

                record = run_single(
                    experiment=EXPERIMENT_D,
                    task=runtime_tasks[task.round],
                    ctx=ctx,
                    agent_registry=agents,
                )
                round_result = _codeact_round_result(
                    task,
                    record,
                    recorder=recorder,
                    secret_config=secret_config,
                )
                results.append(round_result)
                raw.append({"scenario": "codeact", **round_result})
            finally:
                state_hub.close()
    finally:
        store.close()

    by_round = {item["round"]: item for item in results}
    r2 = by_round[2]
    r8 = by_round[8]
    r2_metrics = r2["metrics"]
    r8_metrics = r8["metrics"]
    r8_validation = r8["memory_validation"]
    passed = bool(
        r2["evaluation_pass"]
        and r2_metrics.get("tool_call_count") == 1
        and r8["evaluation_pass"]
        and r8_metrics.get("memory_used", 0) >= 1
        and r8_metrics.get("tool_call_count") == 0
        and r8_validation.get("validated_memory_effective", 0) >= 1
    )
    discrepancy_count = sum(
        1
        for item in results
        if item["memory_validation"]["strict_vs_validated_discrepancy"]
    )
    return (
        {
            "passed": passed,
            "rounds": results,
            "strict_vs_validated_discrepancy_count": discrepancy_count,
            "error": None if passed else "CodeAct mini-chain acceptance condition failed",
        },
        raw,
    )


def _knowledge_round_result(
    task: KnowledgeTask,
    record: RawRunRecord,
    *,
    secret_config: RealBailianConfig,
) -> dict[str, Any]:
    answer = record.run_result.answer
    existing = evaluate_knowledge_answer(task, answer)
    normalized = evaluate_normalized_knowledge_answer(task, answer)
    metrics = dict(record.run_result.metrics)
    validation = build_memory_validation(metrics, evaluator_pass=normalized.success)
    return {
        "round": task.round,
        "task_hash": record.task_hash,
        "run_success": record.run_result.success,
        "existing_evaluation_pass": existing.success,
        "normalized_evaluation_pass": normalized.success,
        "evaluation_pass": normalized.success,
        "matched_answer_contains": normalized.matched_answer_contains,
        "missing_answer_contains": normalized.missing_answer_contains,
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        "metrics": metrics,
        "memory_validation": validation.model_dump(mode="json"),
        "error": _sanitize_run_error(record, secret_config),
    }


def _codeact_round_result(
    task: CodeActTask,
    record: RawRunRecord,
    *,
    recorder: RecordingExecutorAgent,
    secret_config: RealBailianConfig,
) -> dict[str, Any]:
    metrics = dict(record.run_result.metrics)
    execution = recorder.executions[-1] if recorder.executions else {}
    evaluation = evaluate_codeact_execution(task, execution) if execution else None
    evaluation_pass = bool(evaluation is not None and evaluation.success)
    validation = build_memory_validation(metrics, evaluator_pass=evaluation_pass)
    return {
        "round": task.round,
        "task_hash": record.task_hash,
        "run_success": record.run_result.success,
        "evaluation_pass": evaluation_pass,
        "evaluation_error": None if evaluation is None else evaluation.error,
        "execution_operation": execution.get("operation") if execution else None,
        "metrics": metrics,
        "memory_validation": validation.model_dump(mode="json"),
        "error": _sanitize_run_error(record, secret_config),
    }


def _require_rounds(
    tasks: list[Any],
    *,
    expected: tuple[int, ...],
    task_type: type,
) -> None:
    if not all(isinstance(task, task_type) for task in tasks):
        raise TypeError("unexpected task type in calibration selection")
    rounds = tuple(task.round for task in tasks)
    if rounds != expected:
        raise ValueError(f"calibration requires rounds {expected}, got {rounds}")


def _sanitize_run_error(
    record: RawRunRecord,
    config: RealBailianConfig,
) -> dict[str, Any] | None:
    error = record.run_result.error
    if not isinstance(error, dict):
        return None
    return {
        "type": _safe_scalar(error.get("type")),
        "message": _redact_text(str(error.get("message", "")), config),
    }


def _sanitize_error(exc: Exception, config: RealBailianConfig) -> str:
    return f"{exc.__class__.__name__}: {_redact_text(str(exc), config)}"


def _redact_text(text: str, config: RealBailianConfig) -> str:
    redacted = text
    for secret in (config.api_key, config.base_url):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _safe_scalar(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _empty_provider_usage() -> ProviderUsage:
    return ProviderUsage(
        llm_calls=[],
        embedding_calls=[],
        llm_call_count=0,
        llm_prompt_tokens=0,
        llm_completion_tokens=0,
        llm_total_tokens=0,
        llm_usage_missing_count=0,
        llm_latency_ms=0.0,
        embedding_call_count=0,
        embedding_input_count=0,
        embedding_input_chars=0,
        embedding_latency_ms=0.0,
    )
