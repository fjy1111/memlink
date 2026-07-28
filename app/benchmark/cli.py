"""Command-line interface for formal and partial benchmark runs."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from app.benchmark.models import BenchmarkConfig, BenchmarkRunRecord
from app.benchmark.output import write_all_outputs
from app.benchmark.runner import BenchmarkRunner
from app.benchmark.statistics import summarize_records
from app.core.config import PROJECT_ROOT, Settings

DEFAULT_RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"


def build_parser() -> argparse.ArgumentParser:
    """Build benchmark run and summarize subcommands."""

    parser = argparse.ArgumentParser(prog="python -m app.benchmark.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run real offline benchmark tasks.")
    run.add_argument("--rounds", type=int, default=10)
    run.add_argument("--seed", type=int, default=2026)
    run.add_argument(
        "--experiment",
        default="all",
        choices=[
            "all",
            "ablation",
            "text",
            "structured",
            "structured_no_memory",
            "structured_no_semantic_state",
            "structured_no_result_ref",
        ],
    )
    run.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
    )
    run.add_argument("--temporary-root", type=Path)
    run.add_argument(
        "--backend",
        choices=["fake"],
        default="fake",
        help="Formal benchmarks are intentionally offline and Fake-only.",
    )
    summarize = commands.add_parser(
        "summarize",
        help="Recalculate summaries from an existing raw_runs.jsonl.",
    )
    summarize.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
    )
    return parser


async def run_command(arguments: argparse.Namespace) -> int:
    """Run a selected matrix with deterministic offline adapters."""

    settings = Settings(
        _env_file=None,
        llm_backend=arguments.backend,
        deepseek_api_key="",
        deepseek_base_url="",
        deepseek_model="",
        embedding_backend="fake",
        embedding_api_key="",
        embedding_base_url="",
        embedding_model="",
    )
    runner = BenchmarkRunner(settings=settings, progress=print)
    artifacts = await runner.run(
        BenchmarkConfig(
            rounds=arguments.rounds,
            seed=arguments.seed,
            results_dir=arguments.results_dir.resolve(),
            temporary_root=(
                arguments.temporary_root.resolve()
                if arguments.temporary_root
                else None
            ),
            experiment=arguments.experiment,
        )
    )
    print(f"完成真实任务运行：{len(artifacts.records)} 条")
    for name, path in artifacts.output_files.items():
        print(f"{name}: {path}")
    return 0 if all(record.success for record in artifacts.records) else 1


def summarize_command(results_dir: Path) -> int:
    """Rebuild aggregate files from preserved raw JSONL records."""

    raw_path = results_dir / "raw_runs.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw benchmark file not found: {raw_path}")
    records = [
        BenchmarkRunRecord.model_validate_json(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stability_path = results_dir / "stability_summary.json"
    stability_payload = (
        json.loads(stability_path.read_text(encoding="utf-8"))
        if stability_path.is_file()
        else {}
    )
    from app.benchmark.models import StabilitySummary

    stability = (
        StabilitySummary.model_validate(stability_payload)
        if stability_payload
        else None
    )
    output_files = write_all_outputs(
        results_dir=results_dir,
        records=records,
        summaries=summarize_records(records),
        stability=stability,
        environment=json.loads(
            (results_dir / "environment.json").read_text(encoding="utf-8")
        ),
    )
    print(f"已从 {len(records)} 条原始记录重新汇总：")
    for name, path in output_files.items():
        print(f"{name}: {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments with UTF-8 console output on Windows and Linux."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    arguments = build_parser().parse_args(argv)
    if arguments.command == "run":
        return asyncio.run(run_command(arguments))
    if arguments.command == "summarize":
        return summarize_command(arguments.results_dir.resolve())
    raise ValueError(f"Unsupported command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
