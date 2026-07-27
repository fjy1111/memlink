"""Dependency-free descriptive statistics for benchmark results."""

import math
import statistics
from collections.abc import Iterable

from app.benchmark.models import (
    BenchmarkRunRecord,
    DescriptiveStatistics,
    ExperimentSummary,
)

SUMMARY_METRICS = (
    "message_count",
    "protocol_message_count",
    "text_character_count",
    "estimated_token_count",
    "json_serialized_bytes",
    "msgpack_serialized_bytes",
    "semantic_state_transfer_count",
    "semantic_state_bytes",
    "memory_query_count",
    "memory_hit_count",
    "repeated_retrieval_count",
    "result_reference_count",
    "full_result_transfer_count",
    "retry_count",
    "error_count",
    "total_duration_ms",
)


def percentile(values: Iterable[float], percentile_value: float) -> float:
    """Return a linearly interpolated percentile for finite values."""

    if not 0.0 <= percentile_value <= 100.0:
        raise ValueError("percentile_value must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if any(not math.isfinite(value) for value in ordered):
        raise ValueError("percentile values must be finite")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def describe(values: Iterable[float]) -> DescriptiveStatistics:
    """Compute mean, range, P50/P95, and population standard deviation."""

    materialized = [float(value) for value in values]
    if not materialized:
        raise ValueError("describe requires at least one value")
    return DescriptiveStatistics(
        mean=statistics.fmean(materialized),
        minimum=min(materialized),
        maximum=max(materialized),
        p50=percentile(materialized, 50.0),
        p95=percentile(materialized, 95.0),
        standard_deviation=statistics.pstdev(materialized),
    )


def summarize_records(
    records: list[BenchmarkRunRecord],
) -> list[ExperimentSummary]:
    """Group raw records by experiment and calculate actual aggregates."""

    grouped: dict[str, list[BenchmarkRunRecord]] = {}
    for record in records:
        grouped.setdefault(record.experiment_name.value, []).append(record)
    summaries: list[ExperimentSummary] = []
    for group_records in grouped.values():
        count = len(group_records)
        successful = sum(record.success for record in group_records)
        errors = sum(record.error_count > 0 for record in group_records)
        summaries.append(
            ExperimentSummary(
                experiment_name=group_records[0].experiment_name,
                communication_mode=group_records[0].communication_mode,
                run_count=count,
                completion_rate=successful / count,
                error_rate=errors / count,
                average_memory_hit_rate=statistics.fmean(
                    record.memory_hit_rate for record in group_records
                ),
                metrics={
                    metric: describe(
                        getattr(record, metric) for record in group_records
                    )
                    for metric in SUMMARY_METRICS
                },
            )
        )
    return summaries

