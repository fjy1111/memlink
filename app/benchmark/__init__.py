"""Reproducible stage-three benchmark infrastructure."""

from app.benchmark.matrix import EXPERIMENT_MATRIX, select_experiments
from app.benchmark.models import (
    BenchmarkArtifacts,
    BenchmarkConfig,
    BenchmarkRunRecord,
    ExperimentDefinition,
    ExperimentName,
    ExperimentSummary,
    StabilitySummary,
)
from app.benchmark.statistics import describe, percentile, summarize_records

__all__ = [
    "EXPERIMENT_MATRIX",
    "BenchmarkArtifacts",
    "BenchmarkConfig",
    "BenchmarkRunRecord",
    "ExperimentDefinition",
    "ExperimentName",
    "ExperimentSummary",
    "StabilitySummary",
    "describe",
    "percentile",
    "select_experiments",
    "summarize_records",
]
