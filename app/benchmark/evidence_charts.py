"""Dependency-light 1600×900 PNG charts for evidence experiment results."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.benchmark.evidence_common import DEFAULT_EVIDENCE_RESULTS_DIR
from app.benchmark.evidence_models import (
    ContextScalingRecord,
    MemoryReuseRecord,
)

WIDTH = 1600
HEIGHT = 900
PLOT_LEFT = 170
PLOT_TOP = 130
PLOT_RIGHT = 1510
PLOT_BOTTOM = 735
COLORS = ("#2563EB", "#0F9D76", "#E87817", "#C23B73")
CONTEXT_ORDER = ("1x", "2x", "4x", "8x")
CONDITION_ORDER = (
    "no_memory",
    "cold_memory",
    "warm_memory",
    "irrelevant_memory",
)
CONTEXT_EXPERIMENT_ORDER = (
    "text",
    "structured",
    "structured_no_result_ref",
)
EXPERIMENT_LABELS = {
    "text": "text",
    "structured": "structured",
    "structured_no_result_ref": "structured（关闭 result_ref）",
}
CONDITION_LABELS = {
    "no_memory": "禁用记忆",
    "cold_memory": "冷启动记忆",
    "warm_memory": "热记忆复用",
    "irrelevant_memory": "无关记忆对照",
}
FIGURE_NAMES = (
    "E01_上下文规模与通信载荷.png",
    "E02_上下文规模与重复传输.png",
    "E03_result_ref节省比例.png",
    "E04_共享记忆条件对比.png",
    "E05_共享记忆复用正确性.png",
    "E06_重复步骤与重复载荷.png",
)
REQUIRED_RESULT_FILES = (
    "context_scaling_raw.csv",
    "context_scaling_summary.csv",
    "context_scaling_summary.json",
    "context_scaling_report.md",
    "memory_reuse_raw.csv",
    "memory_reuse_summary.csv",
    "memory_reuse_summary.json",
    "memory_reuse_report.md",
)
MEMORY_LIST_FIELDS = (
    "retrieved_memory_ids",
    "reused_memory_ids",
    "expected_memory_ids",
    "irrelevant_memory_ids",
    "reviewer_rejected_memory",
)


def generate_context_figures(
    records: Sequence[ContextScalingRecord],
    output_dir: Path,
) -> list[Path]:
    """Generate the three context-scaling figures required for delivery."""

    _validate_context_records(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_series = _context_series(
        records,
        CONTEXT_EXPERIMENT_ORDER,
        lambda row: float(row.utf8_payload_bytes),
    )
    repeated_series = _context_series(
        records,
        CONTEXT_EXPERIMENT_ORDER,
        lambda row: float(row.repeated_payload_bytes),
    )
    payload_series = _display_experiment_names(payload_series)
    repeated_series = _display_experiment_names(repeated_series)
    saving_series: dict[str, list[float]] = {"result_ref 节省比例": []}
    for scale in CONTEXT_ORDER:
        structured = _mean_context(
            records,
            "structured",
            scale,
            lambda row: float(row.json_bytes),
        )
        no_ref = _mean_context(
            records,
            "structured_no_result_ref",
            scale,
            lambda row: float(row.json_bytes),
        )
        saving_series["result_ref 节省比例"].append(
            result_ref_saving_percent(structured, no_ref)
        )

    files = [
        output_dir / FIGURE_NAMES[0],
        output_dir / FIGURE_NAMES[1],
        output_dir / FIGURE_NAMES[2],
    ]
    _draw_line_chart(
        files[0],
        title="上下文规模与通信载荷",
        x_labels=CONTEXT_ORDER,
        series=payload_series,
        y_title="累计通信载荷（Bytes）",
        note=(
            "采用三组同口径 utf8_payload_bytes 均值；"
            "structured 存在固定协议开销，不预设其必然优于 text"
        ),
    )
    _draw_line_chart(
        files[1],
        title="上下文规模与重复传输",
        x_labels=CONTEXT_ORDER,
        series=repeated_series,
        y_title="重复传输字节（Bytes）",
        note=(
            "repeated_payload_bytes 为确定性证据片段首次出现后的"
            "精确重复 UTF-8 字节"
        ),
    )
    _draw_line_chart(
        files[2],
        title="result_ref 节省比例",
        x_labels=CONTEXT_ORDER,
        series=saving_series,
        y_title="节省比例（%）",
        percent_axis=True,
        note=(
            "公式：(structured_no_result_ref JSON - structured JSON)"
            " / structured_no_result_ref JSON × 100%"
        ),
    )
    return files


def generate_memory_figures(
    records: Sequence[MemoryReuseRecord],
    output_dir: Path,
) -> list[Path]:
    """Generate the three shared-memory figures required for delivery."""

    _validate_memory_records(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_conditions = CONDITION_ORDER[:3]
    condition_labels = [CONDITION_LABELS[item] for item in CONDITION_ORDER]
    comparison_labels = [
        CONDITION_LABELS[item] for item in comparison_conditions
    ]
    all_step_series = {
        "重复步骤": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.repeated_steps),
            )
            for condition in CONDITION_ORDER
        ]
    }
    all_payload_series = {
        "重复载荷字节": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.repeated_payload_bytes),
            )
            for condition in CONDITION_ORDER
        ]
    }
    correctness_conditions = ("warm_memory", "irrelevant_memory")
    correctness_series: dict[str, list[float]] = {
        "正确复用率": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.relevant_memory_reused) * 100.0,
            )
            for condition in correctness_conditions
        ],
        "复用精确率": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.memory_reuse_precision) * 100.0,
            )
            for condition in correctness_conditions
        ],
        "无关记忆误用率": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.irrelevant_memory_reused) * 100.0,
            )
            for condition in correctness_conditions
        ],
    }
    step_series = {
        "重复步骤": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.repeated_steps),
            )
            for condition in comparison_conditions
        ],
        "避免步骤": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.avoided_steps),
            )
            for condition in comparison_conditions
        ],
    }
    payload_series = {
        "重复载荷字节": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.repeated_payload_bytes),
            )
            for condition in comparison_conditions
        ]
    }

    files = [
        output_dir / FIGURE_NAMES[3],
        output_dir / FIGURE_NAMES[4],
        output_dir / FIGURE_NAMES[5],
    ]
    _draw_two_panel_bars(
        files[0],
        title="共享记忆条件对比",
        x_labels=condition_labels,
        top_series=all_step_series,
        bottom_series=all_payload_series,
        top_title="平均重复步骤（Steps）",
        bottom_title="平均重复载荷（Bytes）",
        note="步骤数与字节数分面展示，避免混用量纲；四种条件均来自真实目标任务",
    )
    _draw_bar_chart(
        files[1],
        title="共享记忆复用正确性",
        x_labels=[
            CONDITION_LABELS[item] for item in correctness_conditions
        ],
        series=correctness_series,
        y_title="比例（%）",
        percent_axis=True,
        note=(
            "retrieved_memory_ids 是检索候选；图中复用指标依据"
            " reused_memory_ids 与相关性真值计算"
        ),
    )
    _draw_two_panel_bars(
        files[2],
        title="共享记忆复用前后的重复步骤与载荷",
        x_labels=comparison_labels,
        top_series=step_series,
        bottom_series=payload_series,
        top_title="平均重复步骤 / 避免步骤（Steps）",
        bottom_title="平均重复载荷（Bytes）",
        note="重点比较禁用、冷启动与热记忆；0 值按真实结果保留",
    )
    return files


def generate_evidence_figures_from_results(
    results_dir: Path = DEFAULT_EVIDENCE_RESULTS_DIR,
) -> list[Path]:
    """Validate existing evidence results and generate the six delivery PNGs."""

    destination = results_dir.resolve()
    _validate_required_result_files(destination)
    context_rows = _read_csv_rows(destination / "context_scaling_raw.csv")
    memory_rows = _read_csv_rows(destination / "memory_reuse_raw.csv")
    context_summary = _read_csv_rows(
        destination / "context_scaling_summary.csv"
    )
    memory_summary = _read_csv_rows(
        destination / "memory_reuse_summary.csv"
    )
    context_records = _parse_context_records(context_rows)
    memory_records = _parse_memory_records(memory_rows)
    _validate_context_records(context_records)
    _validate_memory_records(memory_records)
    _validate_context_summary(context_records, context_summary)
    _validate_memory_summary(memory_records, memory_summary)
    _validate_json_summary(
        destination / "context_scaling_summary.json",
        expected_rows=len(context_summary),
    )
    _validate_json_summary(
        destination / "memory_reuse_summary.json",
        expected_rows=len(memory_summary),
    )
    figures_dir = destination / "figures"
    return [
        *generate_context_figures(context_records, figures_dir),
        *generate_memory_figures(memory_records, figures_dir),
    ]


def result_ref_saving_percent(
    structured_json_bytes: float,
    no_result_ref_json_bytes: float,
) -> float:
    """Return the real JSON-byte saving without clipping negative results."""

    if not math.isfinite(structured_json_bytes) or not math.isfinite(
        no_result_ref_json_bytes
    ):
        raise ValueError("result_ref saving inputs must be finite")
    if no_result_ref_json_bytes <= 0:
        raise ValueError(
            "structured_no_result_ref JSON bytes must be greater than zero"
        )
    return (
        (no_result_ref_json_bytes - structured_json_bytes)
        / no_result_ref_json_bytes
        * 100.0
    )


def _display_experiment_names(
    series: dict[str, list[float]],
) -> dict[str, list[float]]:
    return {
        EXPERIMENT_LABELS[experiment]: values
        for experiment, values in series.items()
    }


def _validate_required_result_files(results_dir: Path) -> None:
    if not results_dir.is_dir():
        raise FileNotFoundError(
            f"Evidence results directory not found: {results_dir}"
        )
    missing = [
        name
        for name in REQUIRED_RESULT_FILES
        if not (results_dir / name).is_file()
        or (results_dir / name).stat().st_size == 0
    ]
    if missing:
        raise FileNotFoundError(
            "Missing or empty evidence result files: " + ", ".join(missing)
        )
    for report_name in (
        "context_scaling_report.md",
        "memory_reuse_report.md",
    ):
        if not (results_dir / report_name).read_text(
            encoding="utf-8"
        ).strip():
            raise ValueError(f"Evidence report is empty: {report_name}")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"Evidence CSV has no data rows: {path.name}")
    return rows


def _parse_context_records(
    rows: Sequence[dict[str, str]],
) -> list[ContextScalingRecord]:
    _require_fields(
        rows,
        set(ContextScalingRecord.model_fields),
        "context_scaling_raw.csv",
    )
    return [ContextScalingRecord.model_validate(row) for row in rows]


def _parse_memory_records(
    rows: Sequence[dict[str, str]],
) -> list[MemoryReuseRecord]:
    _require_fields(
        rows,
        set(MemoryReuseRecord.model_fields),
        "memory_reuse_raw.csv",
    )
    parsed: list[MemoryReuseRecord] = []
    for row in rows:
        payload: dict[str, Any] = dict(row)
        for field in MEMORY_LIST_FIELDS:
            try:
                payload[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(
                    f"Invalid JSON list in memory_reuse_raw.csv:{field}"
                ) from exc
        parsed.append(MemoryReuseRecord.model_validate(payload))
    return parsed


def _require_fields(
    rows: Sequence[dict[str, str]],
    required: set[str],
    filename: str,
) -> None:
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(
            f"{filename} is missing required fields: {sorted(missing)}"
        )


def _validate_context_records(
    records: Sequence[ContextScalingRecord],
) -> None:
    if not records:
        raise ValueError("No context-scaling records were provided")
    experiment_order = list(
        dict.fromkeys(record.experiment for record in records)
    )
    scale_order = list(
        dict.fromkeys(record.context_scale for record in records)
    )
    if experiment_order != list(CONTEXT_EXPERIMENT_ORDER):
        raise ValueError(
            f"Unexpected context experiment order: {experiment_order}"
        )
    if scale_order != list(CONTEXT_ORDER):
        raise ValueError(f"Unexpected context scale order: {scale_order}")
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        _validate_finite_model(record)
        counts[(record.experiment, record.context_scale)] += 1
    expected = {
        (experiment, scale)
        for experiment in CONTEXT_EXPERIMENT_ORDER
        for scale in CONTEXT_ORDER
    }
    if set(counts) != expected or len(set(counts.values())) != 1:
        raise ValueError(
            "Context-scaling records do not form a complete balanced matrix"
        )


def _validate_memory_records(
    records: Sequence[MemoryReuseRecord],
) -> None:
    if not records:
        raise ValueError("No memory-reuse records were provided")
    condition_order = list(
        dict.fromkeys(record.condition for record in records)
    )
    if condition_order != list(CONDITION_ORDER):
        raise ValueError(
            f"Unexpected memory condition order: {condition_order}"
        )
    scenarios = list(dict.fromkeys(record.scenario for record in records))
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        _validate_finite_model(record)
        counts[(record.scenario, record.condition)] += 1
    expected = {
        (scenario, condition)
        for scenario in scenarios
        for condition in CONDITION_ORDER
    }
    if (
        len(scenarios) != 2
        or set(counts) != expected
        or len(set(counts.values())) != 1
    ):
        raise ValueError(
            "Memory-reuse records do not form a complete balanced matrix"
        )


def _validate_finite_model(
    record: ContextScalingRecord | MemoryReuseRecord,
) -> None:
    for field, value in record.model_dump().items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                f"Non-finite evidence value: {field}={value!r}"
            )


def _validate_context_summary(
    records: Sequence[ContextScalingRecord],
    rows: Sequence[dict[str, str]],
) -> None:
    required = {
        "experiment",
        "context_scale",
        "run_count",
        "utf8_payload_bytes_mean",
        "json_bytes_mean",
        "repeated_payload_bytes_mean",
    }
    _require_fields(rows, required, "context_scaling_summary.csv")
    summary = {
        (row["experiment"], row["context_scale"]): row for row in rows
    }
    expected = {
        (experiment, scale)
        for experiment in CONTEXT_EXPERIMENT_ORDER
        for scale in CONTEXT_ORDER
    }
    if set(summary) != expected:
        raise ValueError("Context summary matrix does not match raw data")
    metric_fields = (
        "utf8_payload_bytes",
        "json_bytes",
        "repeated_payload_bytes",
    )
    for key, row in summary.items():
        selected = [
            record
            for record in records
            if (record.experiment, record.context_scale) == key
        ]
        if int(row["run_count"]) != len(selected):
            raise ValueError(f"Context summary run_count mismatch: {key}")
        for field in metric_fields:
            actual = fmean(float(getattr(item, field)) for item in selected)
            _assert_summary_value(
                actual,
                row[f"{field}_mean"],
                f"context {key} {field}",
            )


def _validate_memory_summary(
    records: Sequence[MemoryReuseRecord],
    rows: Sequence[dict[str, str]],
) -> None:
    required = {
        "scenario",
        "condition",
        "run_count",
        "memory_reuse_precision_mean",
        "repeated_steps_mean",
        "avoided_steps_mean",
        "repeated_payload_bytes_mean",
        "correct_reuse_rate",
        "irrelevant_reuse_rate",
    }
    _require_fields(rows, required, "memory_reuse_summary.csv")
    summary = {
        (row["scenario"], row["condition"]): row for row in rows
    }
    expected = {
        (record.scenario, condition)
        for record in records
        for condition in CONDITION_ORDER
    }
    if set(summary) != expected:
        raise ValueError("Memory summary matrix does not match raw data")
    for key, row in summary.items():
        selected = [
            record
            for record in records
            if (record.scenario, record.condition) == key
        ]
        if int(row["run_count"]) != len(selected):
            raise ValueError(f"Memory summary run_count mismatch: {key}")
        metrics: dict[str, float] = {
            "memory_reuse_precision_mean": fmean(
                item.memory_reuse_precision for item in selected
            ),
            "repeated_steps_mean": fmean(
                float(item.repeated_steps) for item in selected
            ),
            "avoided_steps_mean": fmean(
                float(item.avoided_steps) for item in selected
            ),
            "repeated_payload_bytes_mean": fmean(
                float(item.repeated_payload_bytes) for item in selected
            ),
            "correct_reuse_rate": fmean(
                float(item.relevant_memory_reused) for item in selected
            ),
            "irrelevant_reuse_rate": fmean(
                float(item.irrelevant_memory_reused) for item in selected
            ),
        }
        for field, actual in metrics.items():
            _assert_summary_value(actual, row[field], f"memory {key} {field}")
        for field in (
            "memory_reuse_precision_mean",
            "correct_reuse_rate",
            "irrelevant_reuse_rate",
        ):
            value = _finite_float(row[field], f"memory {key} {field}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"Memory proportion is outside 0..1: {key} {field}"
                )


def _assert_summary_value(
    actual: float,
    encoded: str,
    label: str,
) -> None:
    expected = _finite_float(encoded, label)
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError(
            f"Summary value does not match raw data: {label} "
            f"raw={actual} summary={expected}"
        )


def _finite_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric summary value: {label}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Non-finite summary value: {label}")
    return result


def _validate_json_summary(path: Path, *, expected_rows: int) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON summary: {path.name}") from exc
    if not isinstance(payload, list) or len(payload) != expected_rows:
        raise ValueError(
            f"JSON summary row count mismatch: {path.name}"
        )


def _context_series(
    records: Sequence[ContextScalingRecord],
    experiments: Sequence[str],
    value: Callable[[ContextScalingRecord], float],
) -> dict[str, list[float]]:
    return {
        experiment: [
            _mean_context(records, experiment, scale, value)
            for scale in CONTEXT_ORDER
        ]
        for experiment in experiments
    }


def _mean_context(
    records: Sequence[ContextScalingRecord],
    experiment: str,
    scale: str,
    value: Callable[[ContextScalingRecord], float],
) -> float:
    selected = [
        value(record)
        for record in records
        if record.experiment == experiment and record.context_scale == scale
    ]
    return fmean(selected) if selected else 0.0


def _mean_memory(
    records: Sequence[MemoryReuseRecord],
    condition: str,
    value: Callable[[MemoryReuseRecord], float],
) -> float:
    selected = [
        value(record) for record in records if record.condition == condition
    ]
    return fmean(selected) if selected else 0.0


def _draw_line_chart(
    path: Path,
    *,
    title: str,
    x_labels: Sequence[str],
    series: dict[str, Sequence[float]],
    y_title: str,
    percent_axis: bool = False,
    note: str,
) -> None:
    image, draw, fonts = _canvas(title, note)
    minimum = min(
        (value for values in series.values() for value in values),
        default=0.0,
    )
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    minimum = min(minimum, 0.0)
    maximum = max(maximum, 1.0)
    _axes(
        draw,
        fonts,
        x_labels,
        minimum,
        maximum,
        y_title,
        percent_axis,
    )
    x_positions = _x_positions(len(x_labels))
    for index, (name, values) in enumerate(series.items()):
        color = COLORS[index % len(COLORS)]
        points = [
            (
                x_positions[position],
                _y_position(value, minimum, maximum),
            )
            for position, value in enumerate(values)
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=6, joint="curve")
        for point, value in zip(points, values, strict=True):
            draw.ellipse(
                (point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8),
                fill=color,
            )
            label = (
                f"{value:.1f}%"
                if percent_axis
                else _formatted_number(value)
            )
            label_y = (
                point[1] + 28
                if point[1] <= PLOT_TOP + 28
                else point[1] - 34
            )
            draw.text(
                (point[0], label_y),
                label,
                font=fonts["small"],
                fill="#334155",
                anchor="mm",
            )
    _legend(draw, fonts, list(series), list(COLORS))
    image.save(path, format="PNG", optimize=True)


def _draw_bar_chart(
    path: Path,
    *,
    title: str,
    x_labels: Sequence[str],
    series: dict[str, Sequence[float]],
    y_title: str,
    percent_axis: bool = False,
    note: str,
) -> None:
    image, draw, fonts = _canvas(title, note)
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1.0)
    _axes(draw, fonts, x_labels, 0.0, maximum, y_title, percent_axis)
    centers = _x_positions(len(x_labels))
    series_count = max(1, len(series))
    group_width = min(190, (PLOT_RIGHT - PLOT_LEFT) // max(len(x_labels), 1) - 35)
    bar_width = max(24, group_width // series_count)
    for series_index, (name, values) in enumerate(series.items()):
        color = COLORS[series_index % len(COLORS)]
        for index, value in enumerate(values):
            offset = (series_index - (series_count - 1) / 2) * bar_width
            left = centers[index] + offset - bar_width * 0.38
            right = centers[index] + offset + bar_width * 0.38
            top = _y_position(value, 0.0, maximum)
            draw.rounded_rectangle(
                (left, top, right, PLOT_BOTTOM),
                radius=5,
                fill=color,
            )
            label = (
                f"{value:.1f}%"
                if percent_axis
                else _formatted_number(value)
            )
            inside = top <= PLOT_TOP + 35
            label_y = (
                top + 22 + series_index * 24
                if inside
                else top - 18
            )
            draw.text(
                ((left + right) / 2, label_y),
                label,
                font=fonts["tiny"] if inside else fonts["small"],
                fill="#0F172A",
                anchor="ms",
            )
    _legend(draw, fonts, list(series), list(COLORS))
    image.save(path, format="PNG", optimize=True)


def _draw_two_panel_bars(
    path: Path,
    *,
    title: str,
    x_labels: Sequence[str],
    top_series: dict[str, Sequence[float]],
    bottom_series: dict[str, Sequence[float]],
    top_title: str,
    bottom_title: str,
    note: str,
) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    fonts = _fonts()
    draw.text(
        (WIDTH / 2, 55),
        title,
        font=fonts["title"],
        fill="#0F172A",
        anchor="mm",
    )
    _draw_panel(
        draw,
        fonts,
        box=(100, 115, 1500, 430),
        title=top_title,
        x_labels=x_labels,
        series=top_series,
    )
    _draw_panel(
        draw,
        fonts,
        box=(100, 455, 1500, 770),
        title=bottom_title,
        x_labels=x_labels,
        series=bottom_series,
    )
    draw.text(
        (WIDTH / 2, 840),
        note,
        font=fonts["small"],
        fill="#64748B",
        anchor="mm",
    )
    image.save(path, format="PNG", optimize=True)


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    *,
    box: tuple[int, int, int, int],
    title: str,
    x_labels: Sequence[str],
    series: dict[str, Sequence[float]],
) -> None:
    left, top, right, bottom = box
    draw.text(
        ((left + right) / 2, top),
        title,
        font=fonts["subtitle"],
        fill="#0F172A",
        anchor="ma",
    )
    plot_top = top + 82
    plot_bottom = bottom - 55
    axis_left = left + 90
    axis_right = right - 30
    draw.line(
        (axis_left, plot_top, axis_left, plot_bottom),
        fill="#64748B",
        width=2,
    )
    draw.line(
        (axis_left, plot_bottom, axis_right, plot_bottom),
        fill="#64748B",
        width=2,
    )
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1.0)
    centers = [
        axis_left
        + 120
        + index * (axis_right - axis_left - 240) / max(len(x_labels) - 1, 1)
        for index in range(len(x_labels))
    ]
    count = max(1, len(series))
    width = min(80, 220 // count)
    for step in range(5):
        ratio = step / 4
        y = plot_bottom - ratio * (plot_bottom - plot_top)
        value = maximum * ratio
        draw.line((axis_left, y, axis_right, y), fill="#E2E8F0", width=1)
        draw.text(
            (axis_left - 14, y),
            _compact_number(value),
            font=fonts["tiny"],
            fill="#475569",
            anchor="rm",
        )
    for series_index, (name, values) in enumerate(series.items()):
        color = COLORS[series_index]
        for index, value in enumerate(values):
            offset = (series_index - (count - 1) / 2) * width
            bar_left = centers[index] + offset - width * 0.35
            bar_right = centers[index] + offset + width * 0.35
            bar_top = _y_position(
                value,
                0.0,
                maximum,
                plot_top=plot_top,
                plot_bottom=plot_bottom,
            )
            draw.rectangle(
                (bar_left, bar_top, bar_right, plot_bottom),
                fill=color,
            )
            draw.text(
                ((bar_left + bar_right) / 2, bar_top - 18),
                _formatted_number(value),
                font=fonts["tiny"],
                fill="#334155",
                anchor="ms",
            )
        legend_x = left + 120 + series_index * 260
        legend_y = top + 48
        draw.rectangle(
            (legend_x, legend_y - 12, legend_x + 24, legend_y + 12),
            fill=color,
        )
        draw.text(
            (legend_x + 34, legend_y),
            name,
            font=fonts["small"],
            fill="#334155",
            anchor="lm",
        )
    for index, label in enumerate(x_labels):
        draw.text(
            (centers[index], plot_bottom + 28),
            label,
            font=fonts["tiny"],
            fill="#334155",
            anchor="ma",
        )


def _canvas(
    title: str,
    note: str,
) -> tuple[
    Image.Image,
    ImageDraw.ImageDraw,
    dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
]:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    fonts = _fonts()
    draw.text(
        (WIDTH / 2, 55),
        title,
        font=fonts["title"],
        fill="#0F172A",
        anchor="mm",
    )
    draw.text(
        (WIDTH / 2, 830),
        note,
        font=fonts["small"],
        fill="#64748B",
        anchor="mm",
    )
    return image, draw, fonts


def _axes(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    x_labels: Sequence[str],
    minimum: float,
    maximum: float,
    y_title: str,
    percent_axis: bool,
) -> None:
    draw.line(
        (PLOT_LEFT, PLOT_TOP, PLOT_LEFT, PLOT_BOTTOM),
        fill="#64748B",
        width=3,
    )
    draw.line(
        (PLOT_LEFT, PLOT_BOTTOM, PLOT_RIGHT, PLOT_BOTTOM),
        fill="#64748B",
        width=3,
    )
    for step in range(6):
        ratio = step / 5
        y = PLOT_BOTTOM - ratio * (PLOT_BOTTOM - PLOT_TOP)
        value = minimum + (maximum - minimum) * ratio
        draw.line(
            (PLOT_LEFT, y, PLOT_RIGHT, y),
            fill="#E2E8F0",
            width=1,
        )
        label = f"{value:.0f}%" if percent_axis else _compact_number(value)
        draw.text(
            (PLOT_LEFT - 18, y),
            label,
            font=fonts["small"],
            fill="#475569",
            anchor="rm",
        )
    for x, label in zip(_x_positions(len(x_labels)), x_labels, strict=True):
        draw.text(
            (x, PLOT_BOTTOM + 32),
            label,
            font=fonts["body"],
            fill="#334155",
            anchor="ma",
        )
    draw.text(
        (5, (PLOT_TOP + PLOT_BOTTOM) / 2),
        y_title,
        font=fonts["body"],
        fill="#334155",
        anchor="lm",
    )


def _legend(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    names: Sequence[str],
    colors: Sequence[str],
) -> None:
    total_width = sum(60 + len(name) * 19 for name in names)
    x = max(PLOT_LEFT, (WIDTH - total_width) / 2)
    for name, color in zip(names, colors, strict=False):
        draw.rectangle((x, 92, x + 28, 116), fill=color)
        draw.text(
            (x + 40, 104),
            name,
            font=fonts["small"],
            fill="#334155",
            anchor="lm",
        )
        x += 60 + len(name) * 19


def _x_positions(count: int) -> list[float]:
    if count <= 1:
        return [(PLOT_LEFT + PLOT_RIGHT) / 2]
    padding = 280 if count == 2 else 110
    return [
        PLOT_LEFT
        + padding
        + index * (PLOT_RIGHT - PLOT_LEFT - 2 * padding) / (count - 1)
        for index in range(count)
    ]


def _y_position(
    value: float,
    minimum: float,
    maximum: float,
    *,
    plot_top: float = PLOT_TOP,
    plot_bottom: float = PLOT_BOTTOM,
) -> float:
    if maximum <= minimum:
        return plot_bottom
    ratio = (value - minimum) / (maximum - minimum)
    return plot_bottom - ratio * (plot_bottom - plot_top)


def _compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    if value.is_integer():
        return f"{value:.0f}"
    return f"{value:.1f}"


def _formatted_number(value: float) -> str:
    if value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _fonts() -> dict[
    str,
    ImageFont.FreeTypeFont | ImageFont.ImageFont,
]:
    font_path = _font_path()
    if font_path is None:
        return {
            "title": ImageFont.load_default(size=36),
            "subtitle": ImageFont.load_default(size=28),
            "body": ImageFont.load_default(size=22),
            "small": ImageFont.load_default(size=18),
            "tiny": ImageFont.load_default(size=15),
        }
    return {
        "title": ImageFont.truetype(str(font_path), 42),
        "subtitle": ImageFont.truetype(str(font_path), 30),
        "body": ImageFont.truetype(str(font_path), 24),
        "small": ImageFont.truetype(str(font_path), 19),
        "tiny": ImageFont.truetype(str(font_path), 16),
    }


def _font_path() -> Path | None:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate delivery figures from existing, validated evidence CSV files."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate existing Fake evidence results and generate six "
            "1600x900 delivery PNGs."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_RESULTS_DIR,
        help="Evidence results directory containing raw and summary files.",
    )
    args = parser.parse_args(argv)
    figures = generate_evidence_figures_from_results(args.results_dir)
    context_count = len(
        _read_csv_rows(args.results_dir / "context_scaling_raw.csv")
    )
    memory_count = len(
        _read_csv_rows(args.results_dir / "memory_reuse_raw.csv")
    )
    print(f"Validated context records: {context_count}")
    print(f"Validated memory target records: {memory_count}")
    for figure in figures:
        print(figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
