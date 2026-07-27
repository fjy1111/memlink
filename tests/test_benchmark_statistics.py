"""Percentile and aggregate calculations used by stage-three reports."""

import math

import pytest

from app.benchmark.statistics import describe, percentile


def test_percentiles_use_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0]

    assert percentile(values, 50) == pytest.approx(2.5)
    assert percentile(values, 95) == pytest.approx(3.85)
    assert percentile([7.0], 95) == 7.0


def test_describe_uses_population_standard_deviation() -> None:
    result = describe([1.0, 2.0, 3.0, 4.0])

    assert result.mean == pytest.approx(2.5)
    assert result.minimum == 1.0
    assert result.maximum == 4.0
    assert result.standard_deviation == pytest.approx(math.sqrt(1.25))


def test_percentile_rejects_empty_or_non_finite_values() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([float("nan")], 50)
    with pytest.raises(ValueError):
        percentile([1.0], 101)

