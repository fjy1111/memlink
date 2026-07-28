"""Dependency-light 1600×900 PNG charts for evidence experiment results."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

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


def generate_context_figures(
    records: Sequence[ContextScalingRecord],
    output_dir: Path,
) -> list[Path]:
    """Generate the three context-scaling figures required for delivery."""

    output_dir.mkdir(parents=True, exist_ok=True)
    experiments = ("text", "structured", "structured_no_result_ref")
    payload_series = _context_series(
        records,
        experiments,
        lambda row: float(row.utf8_payload_bytes),
    )
    repeated_series = _context_series(
        records,
        experiments,
        lambda row: float(row.repeated_payload_bytes),
    )
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
            ((no_ref - structured) / no_ref * 100.0) if no_ref else 0.0
        )

    files = [
        output_dir / "context_scale_vs_payload_bytes.png",
        output_dir / "context_scale_vs_repeated_bytes.png",
        output_dir / "result_ref_saving_ratio.png",
    ]
    _draw_line_chart(
        files[0],
        title="上下文规模与累计文本载荷",
        x_labels=CONTEXT_ORDER,
        series=payload_series,
        y_title="UTF-8 载荷字节（B）",
    )
    _draw_line_chart(
        files[1],
        title="上下文规模与重复传输字节",
        x_labels=CONTEXT_ORDER,
        series=repeated_series,
        y_title="重复载荷字节（B）",
    )
    _draw_line_chart(
        files[2],
        title="result_ref 对结构化 JSON 总字节的节省比例",
        x_labels=CONTEXT_ORDER,
        series=saving_series,
        y_title="节省比例（%）",
        percent_axis=True,
    )
    return files


def generate_memory_figures(
    records: Sequence[MemoryReuseRecord],
    output_dir: Path,
) -> list[Path]:
    """Generate the three shared-memory figures required for delivery."""

    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_conditions = CONDITION_ORDER[:3]
    comparison_series = {
        "JSON 字节": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.json_bytes),
            )
            for condition in comparison_conditions
        ]
    }
    correctness_series = {
        "正确复用率": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.relevant_memory_reused) * 100.0,
            )
            for condition in CONDITION_ORDER
        ],
        "无关记忆误用率": [
            _mean_memory(
                records,
                condition,
                lambda row: float(row.irrelevant_memory_reused) * 100.0,
            )
            for condition in CONDITION_ORDER
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
        output_dir / "memory_condition_comparison.png",
        output_dir / "memory_reuse_correctness.png",
        output_dir / "memory_steps_and_payload.png",
    ]
    _draw_bar_chart(
        files[0],
        title="共享记忆条件通信字节对比",
        x_labels=comparison_conditions,
        series=comparison_series,
        y_title="平均 JSON 字节（B）",
    )
    _draw_bar_chart(
        files[1],
        title="共享记忆复用正确性",
        x_labels=CONDITION_ORDER,
        series=correctness_series,
        y_title="记录占比（%）",
        percent_axis=True,
    )
    _draw_two_panel_bars(
        files[2],
        title="共享记忆复用前后的步骤与重复载荷",
        x_labels=comparison_conditions,
        left_series=step_series,
        right_series=payload_series,
    )
    return files


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
) -> None:
    image, draw, fonts = _canvas(title)
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1.0)
    _axes(draw, fonts, x_labels, maximum, y_title, percent_axis)
    x_positions = _x_positions(len(x_labels))
    for index, (name, values) in enumerate(series.items()):
        color = COLORS[index % len(COLORS)]
        points = [
            (
                x_positions[position],
                _y_position(value, maximum),
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
            label = f"{value:.1f}%" if percent_axis else _compact_number(value)
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
) -> None:
    image, draw, fonts = _canvas(title)
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1.0)
    _axes(draw, fonts, x_labels, maximum, y_title, percent_axis)
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
            top = _y_position(value, maximum)
            draw.rounded_rectangle(
                (left, top, right, PLOT_BOTTOM),
                radius=5,
                fill=color,
            )
            label = f"{value:.1f}%" if percent_axis else _compact_number(value)
            inside = top <= PLOT_TOP + 35
            draw.text(
                ((left + right) / 2, top + 25 if inside else top - 18),
                label,
                font=fonts["small"],
                fill="white" if inside else "#334155",
                anchor="ms",
            )
    _legend(draw, fonts, list(series), list(COLORS))
    image.save(path, format="PNG", optimize=True)


def _draw_two_panel_bars(
    path: Path,
    *,
    title: str,
    x_labels: Sequence[str],
    left_series: dict[str, Sequence[float]],
    right_series: dict[str, Sequence[float]],
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
        box=(90, 130, 770, 760),
        title="计划步骤",
        x_labels=x_labels,
        series=left_series,
    )
    _draw_panel(
        draw,
        fonts,
        box=(830, 130, 1510, 760),
        title="重复载荷字节",
        x_labels=x_labels,
        series=right_series,
    )
    draw.text(
        (WIDTH / 2, 840),
        "所有标签保持水平显示；数值未做平滑或结果美化",
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
    plot_top = top + 75
    plot_bottom = bottom - 75
    draw.line((left + 60, plot_top, left + 60, plot_bottom), fill="#64748B", width=2)
    draw.line((left + 60, plot_bottom, right - 20, plot_bottom), fill="#64748B", width=2)
    maximum = max(
        (value for values in series.values() for value in values),
        default=1.0,
    )
    maximum = max(maximum, 1.0)
    centers = [
        left + 100 + index * (right - left - 140) / max(len(x_labels) - 1, 1)
        for index in range(len(x_labels))
    ]
    count = max(1, len(series))
    width = 60
    for series_index, (name, values) in enumerate(series.items()):
        color = COLORS[series_index]
        for index, value in enumerate(values):
            offset = (series_index - (count - 1) / 2) * width
            bar_left = centers[index] + offset - width * 0.35
            bar_right = centers[index] + offset + width * 0.35
            bar_top = plot_bottom - value / maximum * (plot_bottom - plot_top)
            draw.rectangle(
                (bar_left, bar_top, bar_right, plot_bottom),
                fill=color,
            )
            draw.text(
                ((bar_left + bar_right) / 2, bar_top - 18),
                _compact_number(value),
                font=fonts["tiny"],
                fill="#334155",
                anchor="ms",
            )
        legend_x = left + 90 + series_index * 200
        draw.rectangle(
            (legend_x, bottom - 28, legend_x + 24, bottom - 4),
            fill=color,
        )
        draw.text(
            (legend_x + 34, bottom - 16),
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
        "Fake 后端离线确定性实验；误差条未省略，详见 CSV 的标准差",
        font=fonts["small"],
        fill="#64748B",
        anchor="mm",
    )
    return image, draw, fonts


def _axes(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    x_labels: Sequence[str],
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
        value = maximum * ratio
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
    padding = 110
    return [
        PLOT_LEFT
        + padding
        + index * (PLOT_RIGHT - PLOT_LEFT - 2 * padding) / (count - 1)
        for index in range(count)
    ]


def _y_position(value: float, maximum: float) -> float:
    return PLOT_BOTTOM - value / maximum * (PLOT_BOTTOM - PLOT_TOP)


def _compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    if value.is_integer():
        return f"{value:.0f}"
    return f"{value:.1f}"


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
