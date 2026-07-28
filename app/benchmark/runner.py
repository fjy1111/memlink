"""Fair, isolated execution of the formal MemLink benchmark matrix."""

import json
import platform
import random
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np

from app.benchmark.environment import collect_environment
from app.benchmark.matrix import select_experiments
from app.benchmark.models import (
    BenchmarkArtifacts,
    BenchmarkConfig,
    BenchmarkRunRecord,
    ExperimentDefinition,
    ExperimentName,
    ExperimentResourceStatus,
    StabilitySummary,
)
from app.benchmark.output import write_all_outputs
from app.benchmark.statistics import percentile, summarize_records
from app.core.config import PROJECT_ROOT, Settings
from app.llm import create_embedding_client, create_llm_client
from app.models import TaskCreate, TaskStatus
from app.runtime.orchestrator import TaskOrchestrator

ProgressCallback = Callable[[str], None]
TASKS_FILE = PROJECT_ROOT / "data" / "examples" / "continuous_tasks.json"


class BenchmarkRunner:
    """Run real tasks with identical inputs and isolated experiment state."""

    def __init__(
        self,
        *,
        settings: Settings,
        progress: ProgressCallback | None = None,
    ) -> None:
        if (
            settings.llm_backend != "fake"
            or settings.embedding_backend != "fake"
        ):
            raise ValueError(
                "Benchmark 仅允许使用离线 Fake LLM 和 Fake Embedding"
            )
        self._settings = settings
        self._progress = progress or (lambda message: None)
        self._tasks = self._load_tasks()

    async def run(self, config: BenchmarkConfig) -> BenchmarkArtifacts:
        """Execute selected experiments and persist every raw observation."""

        experiments = select_experiments(config.experiment)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        temporary_parent = config.temporary_root
        if temporary_parent is not None:
            temporary_parent.mkdir(parents=True, exist_ok=True)

        records: list[BenchmarkRunRecord] = []
        resources: list[ExperimentResourceStatus] = []
        for experiment in experiments:
            random.seed(config.seed)
            np.random.seed(config.seed)
            self._progress(
                f"开始实验 {experiment.name.value}："
                f"{config.rounds} 轮，{len(self._tasks)} 个任务/轮"
            )
            experiment_records, resource = await self._run_experiment(
                experiment=experiment,
                rounds=config.rounds,
                seed=config.seed,
                temporary_parent=temporary_parent,
            )
            records.extend(experiment_records)
            resources.append(resource)

        summaries = summarize_records(records)
        stability = self._build_stability(records, resources)
        output_files = write_all_outputs(
            results_dir=config.results_dir,
            records=records,
            summaries=summaries,
            stability=stability,
            environment={
                **collect_environment(),
                "seed": config.seed,
                "rounds": config.rounds,
                "task_order": [
                    task["source_task_id"] for task in self._tasks
                ],
                "llm_backend": self._settings.llm_backend,
                "llm_model": "fake",
                "embedding_backend": self._settings.embedding_backend,
                "embedding_model": self._settings.embedding_model or "fake",
                "temperature": self._settings.llm_temperature,
                "timeout_seconds": self._settings.llm_timeout_seconds,
                "max_retries": self._settings.llm_max_retries,
            },
        )
        return BenchmarkArtifacts(
            records=records,
            summaries=summaries,
            stability=stability,
            resource_statuses=resources,
            output_files=output_files,
        )

    async def _run_experiment(
        self,
        *,
        experiment: ExperimentDefinition,
        rounds: int,
        seed: int,
        temporary_parent: Path | None,
    ) -> tuple[list[BenchmarkRunRecord], ExperimentResourceStatus]:
        """Use one fresh temporary database and state directory per experiment."""

        del seed
        runtime_path: Path
        records: list[BenchmarkRunRecord] = []
        database_released = False
        with tempfile.TemporaryDirectory(
            prefix=f"memlink-{experiment.name.value}-",
            dir=str(temporary_parent) if temporary_parent else None,
        ) as temporary_name:
            runtime_path = Path(temporary_name)
            database_path = runtime_path / "memory" / "shared.db"
            state_path = runtime_path / "states"
            orchestrator = TaskOrchestrator(
                metrics_dir=runtime_path / "metrics",
                state_dir=state_path,
                memory_db_path=database_path,
                llm=create_llm_client(self._settings),
                embedding=create_embedding_client(self._settings),
                backend_name=self._settings.llm_backend,
                enable_shared_memory=experiment.enable_shared_memory,
                enable_semantic_state=experiment.enable_semantic_state,
                enable_result_reference=experiment.enable_result_reference,
            )
            total = rounds * len(self._tasks)
            progress_index = 0
            for round_index in range(1, rounds + 1):
                for task in self._tasks:
                    progress_index += 1
                    self._progress(
                        f"[{experiment.name.value}] "
                        f"轮次 {round_index}/{rounds}，"
                        f"任务 {progress_index}/{total}：{task['title']}"
                    )
                    record = await self._run_task(
                        orchestrator=orchestrator,
                        experiment=experiment,
                        task=task,
                        round_index=round_index,
                    )
                    records.append(record)
            database_released = self._probe_database_release(database_path)

        cleanup_success = not runtime_path.exists()
        residue_count = (
            sum(1 for path in runtime_path.rglob("*") if path.is_file())
            if runtime_path.exists()
            else 0
        )
        return records, ExperimentResourceStatus(
            experiment_name=experiment.name,
            cleanup_success=cleanup_success,
            database_handle_released=database_released,
            temporary_file_residue_count=residue_count,
            background_process_count=0,
        )

    async def _run_task(
        self,
        *,
        orchestrator: TaskOrchestrator,
        experiment: ExperimentDefinition,
        task: dict[str, str],
        round_index: int,
    ) -> BenchmarkRunRecord:
        """Execute one actual task, recording failure rather than hiding it."""

        run_id = str(uuid4())
        started_at = datetime.now(UTC)
        started = perf_counter()
        memory_before = orchestrator.memory_store.count()
        state_before = orchestrator.state_store.file_count()
        try:
            result = await orchestrator.run(
                TaskCreate(
                    title=task["title"],
                    prompt=task["prompt"],
                    task_topic=task["task_topic"],
                    mode=experiment.communication_mode,
                )
            )
            metrics = result.metrics
            return BenchmarkRunRecord(
                run_id=run_id,
                experiment_name=experiment.name,
                communication_mode=experiment.communication_mode,
                task_group=task["task_group"],
                task_id=result.task_id,
                source_task_id=task["source_task_id"],
                round_index=round_index,
                success=True,
                task_status=metrics.task_status,
                message_count=metrics.message_count,
                protocol_message_count=metrics.protocol_message_count,
                text_character_count=metrics.text_character_count,
                estimated_token_count=metrics.estimated_token_count,
                json_serialized_bytes=metrics.json_serialized_bytes,
                msgpack_serialized_bytes=metrics.msgpack_serialized_bytes,
                semantic_state_transfer_count=(
                    metrics.semantic_state_transfer_count
                ),
                semantic_state_bytes=metrics.semantic_state_bytes,
                memory_query_count=metrics.memory_query_count,
                memory_hit_count=metrics.memory_hit_count,
                memory_hit_rate=metrics.memory_hit_rate,
                reused_memory_ids=metrics.reused_memory_ids,
                repeated_retrieval_count=metrics.repeated_retrieval_count,
                result_reference_count=metrics.result_reference_count,
                full_result_transfer_count=(
                    metrics.full_result_transfer_count
                ),
                retry_count=metrics.retry_count,
                error_count=metrics.error_count,
                total_duration_ms=metrics.total_duration_ms,
                agent_execution_time=metrics.agent_execution_time,
                sqlite_record_count_before=memory_before,
                sqlite_record_count_after=orchestrator.memory_store.count(),
                semantic_state_file_count_before=state_before,
                semantic_state_file_count_after=(
                    orchestrator.state_store.file_count()
                ),
                timestamp=started_at,
                python_version=platform.python_version(),
                operating_system=platform.platform(),
            )
        except Exception as exc:
            elapsed_ms = (perf_counter() - started) * 1000
            self._progress(
                f"[{experiment.name.value}] 任务失败："
                f"{type(exc).__name__}: {exc}"
            )
            return BenchmarkRunRecord(
                run_id=run_id,
                experiment_name=experiment.name,
                communication_mode=experiment.communication_mode,
                task_group=task["task_group"],
                task_id=f"failed:{run_id}",
                source_task_id=task["source_task_id"],
                round_index=round_index,
                success=False,
                task_status=TaskStatus.FAILED,
                message_count=0,
                protocol_message_count=0,
                text_character_count=0,
                estimated_token_count=0,
                json_serialized_bytes=0,
                msgpack_serialized_bytes=0,
                semantic_state_transfer_count=0,
                semantic_state_bytes=0,
                memory_query_count=0,
                memory_hit_count=0,
                memory_hit_rate=0.0,
                repeated_retrieval_count=0,
                result_reference_count=0,
                full_result_transfer_count=0,
                retry_count=0,
                error_count=1,
                total_duration_ms=elapsed_ms,
                sqlite_record_count_before=memory_before,
                sqlite_record_count_after=orchestrator.memory_store.count(),
                semantic_state_file_count_before=state_before,
                semantic_state_file_count_after=(
                    orchestrator.state_store.file_count()
                ),
                timestamp=started_at,
                python_version=platform.python_version(),
                operating_system=platform.platform(),
                error_message=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _probe_database_release(database_path: Path) -> bool:
        """Use a Windows-safe rename probe to detect an open SQLite handle."""

        if not database_path.is_file():
            return False
        probe_path = database_path.with_suffix(".release-probe")
        try:
            database_path.replace(probe_path)
            probe_path.replace(database_path)
            return True
        except OSError:
            return False

    @staticmethod
    def _build_stability(
        records: list[BenchmarkRunRecord],
        resources: list[ExperimentResourceStatus],
    ) -> StabilitySummary | None:
        """Summarize the full structured continuous run."""

        structured = [
            record
            for record in records
            if record.experiment_name is ExperimentName.STRUCTURED
        ]
        if not structured:
            return None
        resource = next(
            item
            for item in resources
            if item.experiment_name is ExperimentName.STRUCTURED
        )
        durations = [record.total_duration_ms for record in structured]
        return StabilitySummary(
            experiment_name=ExperimentName.STRUCTURED,
            total_tasks=len(structured),
            successful_tasks=sum(record.success for record in structured),
            failed_tasks=sum(not record.success for record in structured),
            exception_count=sum(record.error_count for record in structured),
            retry_count=sum(record.retry_count for record in structured),
            total_duration_ms=sum(durations),
            p50_duration_ms=percentile(durations, 50.0),
            p95_duration_ms=percentile(durations, 95.0),
            sqlite_record_growth=(
                structured[-1].sqlite_record_count_after
                - structured[0].sqlite_record_count_before
            ),
            semantic_state_file_growth=(
                structured[-1].semantic_state_file_count_after
                - structured[0].semantic_state_file_count_before
            ),
            cleanup_success=resource.cleanup_success,
            database_handle_released=resource.database_handle_released,
            temporary_file_residue_count=(
                resource.temporary_file_residue_count
            ),
            background_process_count=resource.background_process_count,
        )

    @staticmethod
    def _load_tasks() -> list[dict[str, str]]:
        """Load both checked-in groups in deterministic insertion order."""

        payload = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        tasks: list[dict[str, str]] = []
        for group_key, group in payload["groups"].items():
            for index, task in enumerate(group["tasks"], start=1):
                tasks.append(
                    {
                        **task,
                        "task_group": group_key,
                        "source_task_id": f"{group_key}-{index}",
                    }
                )
        return tasks
