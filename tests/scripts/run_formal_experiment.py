from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from agentipc.experiments.formal import render_report, run_e1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "experiment",
        choices=["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"],
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--provider", choices=["openai", "mock"], default="mock")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--confirm-real-api", action="store_true")
    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.input is not None and args.experiment != "e1":
        parser.error("--input is supported only for e1")

    needs_real_api = (
        args.experiment in {"e2", "e3", "e6", "e8"}
        or (args.experiment == "e1" and args.provider == "openai")
    )
    if args.experiment in {"e2", "e3", "e6", "e8"} and args.provider != "openai":
        parser.error("e2/e3/e6/e8 require --provider openai")
    if needs_real_api and not args.confirm_real_api:
        print("Real API execution requires --confirm-real-api", file=sys.stderr)
        raise SystemExit(2)

    labels = {
        "e1": "e1-abcd",
        "e2": "e2-knowledge",
        "e3": "e3-codeact",
        "e4": "e4-shm",
        "e5": "e5-communication",
        "e6": "e6-memory-fast-path",
        "e7": "e7-state-exchange",
        "e8": "e8-full-system",
    }
    root = Path("results/formal") / (
        labels[args.experiment]
        + "-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    root.mkdir(parents=True, exist_ok=False)

    if args.input is not None:
        from agentipc.experiments.formal.aggregation import aggregate_records

        rows = [
            json.loads(line)
            for line in args.input.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = aggregate_records(rows)
    elif args.experiment == "e4":
        from agentipc.experiments.formal.e4_shm import run_e4

        rows = run_e4(repeat=args.repeat)
        summary = {}
        for transport in ("inproc", "shm"):
            selected = [row for row in rows if row["experiment"] == transport]
            summary[transport] = {
                "mean_latency_ms": sum(row["latency_ms"] for row in selected)
                / len(selected),
                "mean_state_bytes": sum(row["state_bytes"] for row in selected)
                / len(selected),
            }
    elif args.experiment == "e5":
        from agentipc.experiments.formal.e5_communication import run_e5

        rows, summary = run_e5(root=root / "work", repeat=args.repeat)
    elif args.experiment == "e6":
        from agentipc.experiments.formal.e6_memory_fast_path import run_e6

        rows, summary = run_e6(
            root=Path(".").resolve(),
            result_dir=root,
            repeat=args.repeat,
        )
    elif args.experiment == "e7":
        from agentipc.experiments.formal.e7_state_exchange import run_e7

        rows, summary = run_e7(repeat=args.repeat)
    elif args.experiment == "e8":
        from agentipc.experiments.formal.e8_full_system import run_e8

        rows, summary = run_e8(
            root=Path(".").resolve(),
            result_dir=root,
            repeat=args.repeat,
        )
    elif args.experiment == "e1":
        from agentipc.experiments.formal.factory import build_factory

        tasks, factory = build_factory(root=root / "work", provider=args.provider)
        rows, summary = run_e1(
            tasks=tasks,
            repeat=args.repeat,
            run_factory=factory,
        )
    elif args.experiment == "e2":
        from agentipc.experiments.formal.e2_knowledge import run_e2

        rows, summary = run_e2(
            root=Path(".").resolve(),
            result_dir=root,
            repeat=args.repeat,
        )
    else:
        from agentipc.experiments.formal.e3_codeact import run_e3

        rows, summary = run_e3(
            root=Path(".").resolve(),
            result_dir=root,
            repeat=args.repeat,
        )

    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "repeat": args.repeat,
        "provider": args.provider,
        "experiment": args.experiment,
        "real_api": needs_real_api,
    }
    (root / "environment.json").write_text(
        json.dumps(environment, indent=2),
        encoding="utf-8",
    )
    (root / "raw.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    (root / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(root)


if __name__ == "__main__":
    main()
