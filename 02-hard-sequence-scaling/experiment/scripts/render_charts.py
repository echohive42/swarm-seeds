#!/usr/bin/env python3
"""Render deterministic, dependency-free SVG charts for Experiment 02.

The renderer accepts the canonical ``results/analysis.json`` shape documented in
``plots/README.md``.  It also accepts CSV files and several common field aliases
so that a final summary can be rendered without a conversion step.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Sequence


METHODS = ("Direct", "Vote10", "Swarm10", "Vote20", "Tournament20")
COLORS = {
    "light": "#0072B2",       # Okabe-Ito blue
    "medium": "#D55E00",      # Okabe-Ito vermillion
    "green": "#009E73",
    "orange": "#E69F00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "gray": "#6B7280",
    "dark": "#17212B",
    "grid": "#D8DEE6",
    "paper": "#FFFFFF",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def public_text(value: Any) -> str:
    """Keep provider-only effort terminology out of public chart text."""
    return re.sub(r"\blow\b", "Luna Light reasoning", str(value), flags=re.IGNORECASE)


def num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        for key in ("estimate", "mean", "value", "total_cost_usd", "cost_usd", "total", "usd"):
            if key in value:
                return num(value[key])
        return None
    try:
        text = str(value).strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        return float(text)
    except (TypeError, ValueError):
        return None


def first(row: dict[str, Any], names: Sequence[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and value != "":
            return value
    return None


def rate(row: dict[str, Any], names: Sequence[str]) -> float | None:
    value = num(first(row, names))
    if value is not None:
        return value / 100.0 if value > 1.0 and value <= 100.0 else value
    correct = num(first(row, ("correct", "n_correct", "exact_correct")))
    total = num(first(row, ("total", "n", "n_cases", "case_count")))
    if correct is not None and total:
        return correct / total
    return None


def flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "primary"}


def method_name(row: dict[str, Any]) -> str | None:
    raw = first(row, ("method", "condition", "strategy", "routing", "arm"))
    if raw is None:
        return None
    compact = "".join(ch for ch in str(raw).lower() if ch.isalnum())
    aliases = {
        "direct": "Direct",
        "directexpected": "Direct",
        "vote10": "Vote10",
        "majorityvote10": "Vote10",
        "swarm10": "Swarm10",
        "vote20": "Vote20",
        "majorityvote20": "Vote20",
        "tournament20": "Tournament20",
        "tournament": "Tournament20",
    }
    return aliases.get(compact, str(raw).strip())


def model_key(row: dict[str, Any]) -> str | None:
    raw = first(row, ("reasoning", "reasoning_effort", "model_tier", "tier", "model"))
    if raw is None:
        return None
    text = str(raw).strip().lower().replace("_", " ").replace("-", " ")
    if text in {"low", "light", "luna light", "luna light reasoning"} or "light" in text:
        return "light"
    if text in {"medium", "luna medium", "luna medium reasoning"} or "medium" in text:
        return "medium"
    return text


def model_label(key: str) -> str:
    if key == "light":
        return "Luna Light reasoning"
    if key == "medium":
        return "Luna Medium reasoning"
    return key.title()


def section_name(value: str) -> str:
    text = value.lower().replace("-", "_").replace(" ", "_")
    if "pair" in text or "comparison" in text or "contrast" in text:
        return "paired"
    if "block" in text:
        return "blocks"
    if "reliab" in text or "format" in text or "retry" in text:
        return "reliability"
    return "conditions"


def load_inputs(paths: Sequence[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        rows.append(dict(item, _section=item.get("section", "conditions")))
            elif isinstance(payload, dict):
                meta = payload.get("metadata")
                if isinstance(meta, dict):
                    metadata.update(meta)
                primary = payload.get("primary")
                if isinstance(primary, dict):
                    rows.append(dict(primary, _section="paired"))
                operational = payload.get("operational_reliability", payload.get("operational-reliability"))
                if isinstance(operational, dict):
                    nested_rows = first(operational, ("rows", "conditions", "by_condition", "by_method"))
                    if isinstance(nested_rows, list):
                        for item in nested_rows:
                            if isinstance(item, dict):
                                rows.append(dict(item, _section="reliability"))
                    elif method_name(operational) and model_key(operational):
                        rows.append(dict(operational, _section="reliability"))
                found = False
                for key, value in payload.items():
                    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                        found = True
                        section = section_name(key)
                        for item in value:
                            if section == "blocks" and isinstance(item.get("methods"), dict):
                                base = {name: field for name, field in item.items() if name != "methods"}
                                for method, fields in item["methods"].items():
                                    fields = fields if isinstance(fields, dict) else {"exact_accuracy": fields}
                                    rows.append(dict(base, **fields, method=method, _section="blocks"))
                            elif section == "blocks" and isinstance(item.get("methods"), list):
                                base = {name: field for name, field in item.items() if name != "methods"}
                                for fields in item["methods"]:
                                    if isinstance(fields, dict):
                                        rows.append(dict(base, **fields, _section="blocks"))
                            else:
                                rows.append(dict(item, _section=item.get("section", section)))
                if not found and any(not isinstance(v, (dict, list)) for v in payload.values()):
                    rows.append(dict(payload, _section=payload.get("section", "conditions")))
            else:
                raise ValueError(f"JSON root must be an object or array: {path}")
        elif path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for item in csv.DictReader(handle):
                    section = item.get("section") or section_name(path.stem)
                    rows.append(dict(item, _section=section))
        else:
            raise ValueError(f"Unsupported input type: {path}")
    return rows, metadata


class SVG:
    def __init__(self, width: int, height: int, title: str, description: str):
        self.width = width
        self.height = height
        self.parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">',
            f'<title id="chart-title">{esc(title)}</title>',
            f'<desc id="chart-desc">{esc(description)}</desc>',
            "<style>text{font-family:Inter,Arial,sans-serif;fill:#17212B}"
            ".title{font-size:24px;font-weight:700}.subtitle{font-size:13px;fill:#4B5563}"
            ".axis{font-size:12px;fill:#374151}.label{font-size:12px}.value{font-size:11px;font-weight:600}"
            ".note{font-size:11px;fill:#59636E}.legend{font-size:12px;font-weight:600}</style>",
            f'<rect width="{width}" height="{height}" fill="{COLORS["paper"]}"/>',
        ]

    def line(self, x1: float, y1: float, x2: float, y2: float, **attrs: Any) -> None:
        self.parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {self.attrs(attrs)}/>')

    def rect(self, x: float, y: float, w: float, h: float, **attrs: Any) -> None:
        self.parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(0,w):.2f}" height="{max(0,h):.2f}" {self.attrs(attrs)}/>')

    def circle(self, x: float, y: float, r: float, **attrs: Any) -> None:
        self.parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" {self.attrs(attrs)}/>')

    def polyline(self, points: Iterable[tuple[float, float]], **attrs: Any) -> None:
        value = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.parts.append(f'<polyline points="{value}" {self.attrs(attrs)}/>')

    def text(self, x: float, y: float, value: Any, css: str = "label", anchor: str = "start", **attrs: Any) -> None:
        self.parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" class="{esc(css)}" text-anchor="{anchor}" '
            f'{self.attrs(attrs)}>{esc(value)}</text>'
        )

    @staticmethod
    def attrs(attrs: dict[str, Any]) -> str:
        return " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())

    def finish(self) -> str:
        return "\n".join(self.parts + ["</svg>", ""])


def heading(svg: SVG, title: str, subtitle: str, source: str) -> None:
    svg.text(48, 42, title, "title")
    svg.text(48, 66, subtitle, "subtitle")
    svg.text(48, svg.height - 18, f"Source: {public_text(source)}", "note")


def legend(svg: SVG, entries: Sequence[tuple[str, str]], x: float, y: float) -> None:
    cursor = x
    for label, color in entries:
        svg.rect(cursor, y - 11, 13, 13, fill=color, rx=2)
        svg.text(cursor + 19, y, label, "legend")
        cursor += 36 + max(100, len(label) * 7)


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def chart_frame(svg: SVG, left: float, top: float, width: float, height: float,
                y_max: float = 1.0, y_label: str = "Exact accuracy") -> None:
    for i in range(6):
        value = y_max * i / 5
        y = top + height - height * i / 5
        svg.line(left, y, left + width, y, stroke=COLORS["grid"], stroke_width=1)
        shown = percent(value) if y_max <= 1.001 else f"{value:g}"
        svg.text(left - 10, y + 4, shown, "axis", "end")
    svg.line(left, top, left, top + height, stroke=COLORS["dark"], stroke_width=1.2)
    svg.line(left, top + height, left + width, top + height, stroke=COLORS["dark"], stroke_width=1.2)
    label_x = max(15, left - 62)
    svg.text(label_x, top + height / 2, y_label, "axis", "middle",
             transform=f"rotate(-90 {label_x:.2f} {top + height / 2:.2f})")


def condition_points(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        if str(row.get("_section", "conditions")).lower() not in {"conditions", "condition", "methods", "reliability"}:
            continue
        method = method_name(row)
        model = model_key(row)
        accuracy = rate(row, ("exact_accuracy", "accuracy", "exact_match_rate", "exact_rate"))
        if method and model and accuracy is not None:
            item = dict(row)
            item.update(_method=method, _model=model, _accuracy=accuracy)
            output.append(item)
    return output


def render_accuracy(rows: Sequence[dict[str, Any]], source: str) -> str | None:
    points = condition_points(rows)
    if not points:
        return None
    svg = SVG(1040, 610, "Luna Light vs Luna Medium exact accuracy",
              "Grouped bars compare exact accuracy by reasoning tier and inference method.")
    heading(svg, "Exact accuracy by method", "Luna Light and Luna Medium reasoning across the five preregistered conditions", source)
    legend(svg, [(model_label("light"), COLORS["light"]), (model_label("medium"), COLORS["medium"])], 600, 52)
    left, top, width, height = 88, 105, 900, 405
    chart_frame(svg, left, top, width, height)
    slot = width / len(METHODS)
    bar_w = 48
    lookup = {(p["_method"], p["_model"]): p["_accuracy"] for p in points}
    for index, method in enumerate(METHODS):
        center = left + slot * (index + 0.5)
        for offset, model in ((-27, "light"), (27, "medium")):
            value = lookup.get((method, model))
            if value is None:
                continue
            y = top + height * (1 - max(0, min(1, value)))
            svg.rect(center + offset - bar_w / 2, y, bar_w, top + height - y,
                     fill=COLORS[model], rx=3)
            svg.text(center + offset, y - 7, percent(value), "value", "middle")
        svg.text(center, top + height + 24, method, "axis", "middle")
    return svg.finish()


def render_equal_budget(rows: Sequence[dict[str, Any]], source: str) -> str | None:
    points = condition_points(rows)
    lookup = {(p["_method"], p["_model"]): p["_accuracy"] for p in points}
    comparisons = (("Vote10", "Swarm10", "10-call routing"),
                   ("Vote20", "Tournament20", "20-call routing"))
    available = [group for group in comparisons if any((m, model) in lookup for m in group[:2] for model in ("light", "medium"))]
    if not available:
        return None
    svg = SVG(1040, 610, "Equal-budget routing contrasts",
              "Bars compare routing methods that use the same nominal call budget.")
    heading(svg, "Equal-budget routing contrasts", "Accuracy differences isolate routing at matched nominal call counts", source)
    legend(svg, [(model_label("light"), COLORS["light"]), (model_label("medium"), COLORS["medium"])], 600, 52)
    left, top, width, height = 88, 110, 900, 390
    chart_frame(svg, left, top, width, height)
    groups: list[tuple[str, str, str]] = []
    for first_method, second_method, label in available:
        groups.extend(((first_method, label, first_method), (second_method, label, second_method)))
    slot = width / len(groups)
    for i, (method, budget, _) in enumerate(groups):
        center = left + slot * (i + 0.5)
        for offset, model in ((-24, "light"), (24, "medium")):
            value = lookup.get((method, model))
            if value is None:
                continue
            y = top + height * (1 - max(0, min(1, value)))
            svg.rect(center + offset - 20, y, 40, top + height - y, fill=COLORS[model], rx=3)
            svg.text(center + offset, y - 7, percent(value), "value", "middle")
        svg.text(center, top + height + 23, method, "axis", "middle")
        if i == 0 or groups[i - 1][1] != budget:
            end = min(len(groups) - 1, i + 1)
            mid = left + slot * ((i + end + 1) / 2)
            svg.text(mid, top + height + 45, budget, "legend", "middle")
    return svg.finish()


def calls_value(row: dict[str, Any]) -> float | None:
    value = num(first(row, ("mean_calls", "avg_calls", "calls", "call_count", "nominal_calls", "deployment_calls")))
    if value is not None:
        return value
    method = method_name(row)
    if method == "Direct":
        return 1.0
    if method in {"Vote10", "Swarm10"}:
        return 10.0
    if method in {"Vote20", "Tournament20"}:
        return 20.0
    return None


def cost_value(row: dict[str, Any]) -> tuple[float | None, str]:
    direct = num(first(row, ("mean_cost", "avg_cost", "total_cost_usd", "mean_cost_usd")))
    if direct is not None:
        return direct, "Mean cost (USD)"
    cost = first(row, ("cost",))
    if isinstance(cost, dict):
        for field in ("provider_cost_usd", "total_cost_usd", "cost_usd", "usd"):
            value = num(first(cost, (field,)))
            if value is not None:
                return value, "Mean cost (USD)"
        tokens = num(first(cost, ("total_tokens",)))
        if tokens is not None:
            return tokens, "Mean total tokens"
    value = num(cost)
    return (value, "Mean cost") if value is not None else (None, "Mean cost")


def render_frontier(rows: Sequence[dict[str, Any]], source: str, cost: bool = False) -> str | None:
    points = condition_points(rows)
    x_name = "Mean cost" if cost else "Mean model calls"
    unique: dict[tuple[str, str], tuple[float, float, str, str]] = {}
    for point in points:
        if cost:
            x, point_x_name = cost_value(point)
            if x is not None:
                x_name = point_x_name
        else:
            x = calls_value(point)
        if x is not None and x >= 0:
            unique[(point["_method"], point["_model"])] = (
                x, point["_accuracy"], point["_method"], point["_model"]
            )
    plotted = list(unique.values())
    if len(plotted) < 2:
        return None
    max_x = max(x for x, _, _, _ in plotted)
    if max_x <= 0:
        return None
    title = "Accuracy vs cost frontier" if cost else "Accuracy vs calls frontier"
    svg = SVG(1040, 620, title, f"Scatter plot of exact accuracy against {x_name.lower()}.")
    subtitle = "Farther right uses more resources; higher accuracy is better"
    heading(svg, title, subtitle, source)
    legend(svg, [(model_label("light"), COLORS["light"]), (model_label("medium"), COLORS["medium"])], 600, 52)
    left, top, width, height = 90, 110, 890, 390
    chart_frame(svg, left, top, width, height)
    x_cap = max_x * 1.08
    for i in range(6):
        x_val = x_cap * i / 5
        x = left + width * i / 5
        svg.text(x, top + height + 22, f"{x_val:.2f}" if cost else f"{x_val:g}", "axis", "middle")
    svg.text(left + width / 2, top + height + 46, x_name, "axis", "middle")
    # A frontier point is not dominated by a point with no greater x and no lower accuracy.
    frontier = []
    best = -math.inf
    for point in sorted(plotted, key=lambda p: (p[0], -p[1], p[2], p[3])):
        if point[1] > best + 1e-12:
            frontier.append(point)
            best = point[1]
    frontier_xy = [(left + width * x / x_cap, top + height * (1 - max(0, min(1, y)))) for x, y, _, _ in frontier]
    if len(frontier_xy) > 1:
        svg.polyline(frontier_xy, fill="none", stroke=COLORS["green"], stroke_width=2.5, stroke_dasharray="6 4")
    for x_val, accuracy, method, model in sorted(plotted):
        x = left + width * x_val / x_cap
        y = top + height * (1 - max(0, min(1, accuracy)))
        svg.circle(x, y, 7, fill=COLORS.get(model, COLORS["gray"]), stroke="#FFFFFF", stroke_width=2)
        label_y = y - 11 if method not in {"Vote20", "Tournament20"} else y + 20
        svg.text(x, label_y, method, "value", "middle")
    svg.text(980, 96, "Dashed line: nondominated observed points", "note", "end")
    return svg.finish()


def interval(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    estimate_pp = num(first(row, ("estimate_pp", "difference_pp")))
    estimate = estimate_pp / 100.0 if estimate_pp is not None else num(first(row, ("estimate", "difference", "accuracy_difference", "effect", "win_rate")))
    low_pp = num(first(row, ("ci95_low_pp", "ci_low_pp")))
    high_pp = num(first(row, ("ci95_high_pp", "ci_high_pp")))
    low = low_pp / 100.0 if low_pp is not None else num(first(row, ("ci_low", "lower", "lower_95", "interval_low", "confidence_low")))
    high = high_pp / 100.0 if high_pp is not None else num(first(row, ("ci_high", "upper", "upper_95", "interval_high", "confidence_high")))
    ci95 = first(row, ("ci95", "confidence_interval_95"))
    effect_object = first(row, ("difference", "effect", "accuracy_difference"))
    if ci95 is None and isinstance(effect_object, dict):
        ci95 = first(effect_object, ("ci95", "confidence_interval_95"))
    if isinstance(ci95, (list, tuple)) and len(ci95) >= 2:
        low, high = num(ci95[0]), num(ci95[1])
    elif isinstance(ci95, dict):
        low = num(first(ci95, ("low", "lower", "ci_low")))
        high = num(first(ci95, ("high", "upper", "ci_high")))
    for name, value in (("estimate", estimate), ("low", low), ("high", high)):
        if value is not None and abs(value) > 1 and abs(value) <= 100:
            if name == "estimate": estimate = value / 100
            elif name == "low": low = value / 100
            else: high = value / 100
    return estimate, low, high


def render_paired(rows: Sequence[dict[str, Any]], source: str) -> str | None:
    paired = []
    for item in rows:
        row = dict(item)
        paired_counts = first(row, ("paired_counts", "discordant_counts", "mcnemar"))
        if isinstance(paired_counts, dict):
            for key, value in paired_counts.items():
                row.setdefault(key, value)
        wins = num(first(row, ("wins", "b_only_wins", "right_only_wins", "tournament20_only_wins")))
        losses = num(first(row, ("losses", "a_only_wins", "left_only_wins", "vote20_only_wins")))
        ties = num(first(row, ("ties",)))
        if ties is None:
            both_correct = num(first(row, ("both_correct",)))
            both_wrong = num(first(row, ("both_wrong", "both_incorrect", "neither_correct")))
            if both_correct is not None and both_wrong is not None:
                ties = both_correct + both_wrong
        if wins is not None and losses is not None and ties is not None:
            row.update(wins=wins, losses=losses, ties=ties)
            paired.append(row)
    if not paired:
        return None
    row = next((item for item in paired if flag(first(item, ("primary", "is_primary")))), None)
    if row is None:
        row = next((item for item in paired
                    if method_name({"method": first(item, ("left", "method_a"))}) == "Vote20"
                    and method_name({"method": first(item, ("right", "method_b"))}) == "Tournament20"
                    and model_key(item) == "medium"), paired[0])
    wins = int(num(first(row, ("wins",))) or 0)
    losses = int(num(first(row, ("losses",))) or 0)
    ties = int(num(first(row, ("ties",))) or 0)
    estimate, low, high = interval(row)
    label_value = first(row, ("comparison", "label", "contrast", "contrast_id"))
    if label_value is None and first(row, ("left", "method_a")) and first(row, ("right", "method_b")):
        left_name = first(row, ("left", "method_a"))
        right_name = first(row, ("right", "method_b"))
        reasoning = model_key(row)
        suffix = f", {model_label(reasoning)}" if reasoning else ""
        label_value = f"{right_name} vs {left_name}{suffix}"
    label = public_text(label_value or "Primary paired comparison")
    svg = SVG(1040, 590, "Primary paired outcomes", "Wins, losses, ties, and the preregistered 95% interval.")
    heading(svg, "Primary paired comparison", label, source)
    values = (("Wins", wins, COLORS["green"]), ("Losses", losses, COLORS["medium"]), ("Ties", ties, COLORS["gray"]))
    maximum = max(1, wins, losses, ties)
    left, top, width = 155, 130, 760
    for i, (name, value, color) in enumerate(values):
        y = top + i * 72
        svg.text(left - 18, y + 25, name, "legend", "end")
        svg.rect(left, y, width, 36, fill="#EEF2F6", rx=4)
        svg.rect(left, y, width * value / maximum, 36, fill=color, rx=4)
        svg.text(left + width * value / maximum + 10, y + 25, value, "value")
    axis_left, axis_right, axis_y = 250, 790, 420
    svg.text(48, 355, "Preregistered effect interval", "legend")
    if estimate is not None and low is not None and high is not None:
        extent = max(abs(low), abs(high), 0.01) * 1.2
        svg.line(axis_left, axis_y, axis_right, axis_y, stroke=COLORS["dark"], stroke_width=1.2)
        zero_x = axis_left + (0 + extent) / (2 * extent) * (axis_right - axis_left)
        svg.line(zero_x, axis_y - 32, zero_x, axis_y + 32, stroke=COLORS["gray"], stroke_width=1.5, stroke_dasharray="4 3")
        lo_x = axis_left + (low + extent) / (2 * extent) * (axis_right - axis_left)
        hi_x = axis_left + (high + extent) / (2 * extent) * (axis_right - axis_left)
        est_x = axis_left + (estimate + extent) / (2 * extent) * (axis_right - axis_left)
        svg.line(lo_x, axis_y, hi_x, axis_y, stroke=COLORS["purple"], stroke_width=7)
        svg.line(lo_x, axis_y - 10, lo_x, axis_y + 10, stroke=COLORS["purple"], stroke_width=2)
        svg.line(hi_x, axis_y - 10, hi_x, axis_y + 10, stroke=COLORS["purple"], stroke_width=2)
        svg.circle(est_x, axis_y, 8, fill=COLORS["purple"], stroke="#FFFFFF", stroke_width=2)
        svg.text(axis_left, axis_y + 35, f"{extent * -100:.1f} pp", "axis", "middle")
        svg.text(zero_x, axis_y + 35, "0", "axis", "middle")
        svg.text(axis_right, axis_y + 35, f"+{extent * 100:.1f} pp", "axis", "middle")
        svg.text(520, 485, f"Estimate {estimate * 100:+.1f} pp; 95% interval [{low * 100:+.1f}, {high * 100:+.1f}] pp", "value", "middle")
    else:
        svg.text(520, axis_y, "95% interval fields were not supplied", "note", "middle")
    return svg.finish()


def render_blocks(rows: Sequence[dict[str, Any]], source: str) -> str | None:
    points = []
    for row in rows:
        block = first(row, ("block", "block_id", "run_block"))
        acc = rate(row, ("exact_accuracy", "accuracy", "exact_match_rate", "exact_rate"))
        method, model = method_name(row), model_key(row)
        if block is not None and acc is not None and method and model:
            points.append((str(block), acc, method, model))
    blocks = sorted({p[0] for p in points})
    series = sorted({(p[2], p[3]) for p in points}, key=lambda x: (METHODS.index(x[0]) if x[0] in METHODS else 99, x[1]))
    if len(blocks) < 2 or not series:
        return None
    svg = SVG(1040, 640, "Block sensitivity", "Exact accuracy by collection block and condition.")
    heading(svg, "Block sensitivity", "Variation across the frozen final collection blocks", source)
    left, top, width, height = 90, 115, 870, 390
    chart_frame(svg, left, top, width, height)
    palette = [COLORS["light"], COLORS["medium"], COLORS["green"], COLORS["orange"], COLORS["purple"], COLORS["sky"], COLORS["gray"]]
    table = {(block, method, model): acc for block, acc, method, model in points}
    for index, (method, model) in enumerate(series):
        color = palette[index % len(palette)]
        coords = []
        for i, block in enumerate(blocks):
            value = table.get((block, method, model))
            if value is None:
                continue
            x = left + width * i / max(1, len(blocks) - 1)
            y = top + height * (1 - max(0, min(1, value)))
            coords.append((x, y))
            svg.circle(x, y, 5, fill=color, stroke="#FFFFFF", stroke_width=1.5)
        if len(coords) > 1:
            svg.polyline(coords, fill="none", stroke=color, stroke_width=2)
        legend_y = 540 + (index // 3) * 22
        legend_x = 75 + (index % 3) * 320
        svg.line(legend_x, legend_y - 4, legend_x + 18, legend_y - 4, stroke=color, stroke_width=3)
        svg.text(legend_x + 25, legend_y, f"{method}: {model_label(model)}", "axis")
    for i, block in enumerate(blocks):
        x = left + width * i / max(1, len(blocks) - 1)
        svg.text(x, top + height + 24, block, "axis", "middle")
    svg.text(left + width / 2, top + height + 48, "Collection block", "axis", "middle")
    return svg.finish()


def render_reliability(rows: Sequence[dict[str, Any]], source: str) -> str | None:
    unique: dict[tuple[str, str], tuple[str, str, float | None, float | None]] = {}
    for row in rows:
        if str(row.get("_section", "conditions")).lower() not in {"conditions", "condition", "methods", "reliability"}:
            continue
        fmt = rate(row, ("format_valid_rate", "format_success_rate", "valid_format_rate", "parse_success_rate", "format_rate"))
        retry = rate(row, ("retry_failure_rate", "retry_rate", "retries_rate",
                           "failure_rate", "infrastructure_failure_rate"))
        if retry is None:
            retries = num(first(row, ("retry_count", "retries")))
            attempts = num(first(row, ("attempt_count", "attempts", "total")))
            if retries is not None and attempts:
                retry = retries / attempts
        method, model = method_name(row), model_key(row)
        if method and model and (fmt is not None or retry is not None):
            unique[(method, model)] = (method, model, fmt, retry)
    records = sorted(unique.values(), key=lambda value: (
        METHODS.index(value[0]) if value[0] in METHODS else 99,
        0 if value[1] == "light" else 1 if value[1] == "medium" else 2,
        value[1],
    ))
    if not records:
        return None
    svg = SVG(1040, 640, "Format and retry/failure reliability",
              "Format validity and retry or failure rates by condition.")
    heading(svg, "Format and retry/failure reliability",
            "Operational quality checks; higher format validity and lower retry/failure rate are preferred", source)
    labels = [f"{method}\n{model_label(model).replace(' reasoning', '')}" for method, model, _, _ in records]
    left, panel_w, gap, top, height = 75, 425, 70, 125, 355
    for panel, metric, title, color in ((0, 2, "Format-valid rate", COLORS["light"]),
                                        (1, 3, "Retry/failure rate", COLORS["orange"])):
        x0 = left + panel * (panel_w + gap)
        chart_frame(svg, x0, top, panel_w, height, y_label="Rate")
        svg.text(x0 + panel_w / 2, 105, title, "legend", "middle")
        bar_w = min(38, panel_w / max(1, len(records)) * 0.62)
        for i, record in enumerate(records):
            value = record[metric]
            if value is None:
                continue
            x = x0 + panel_w * (i + 0.5) / len(records)
            y = top + height * (1 - max(0, min(1, value)))
            svg.rect(x - bar_w / 2, y, bar_w, top + height - y, fill=color, rx=3)
            svg.text(x, y - 6, percent(value), "value", "middle")
            first_line, second_line = labels[i].split("\n", 1)
            svg.text(x, top + height + 20, first_line, "axis", "middle")
            svg.text(x, top + height + 36, second_line, "note", "middle")
    svg.text(520, 575, "Rates use supplied aggregate denominators; see analysis output for counts.", "note", "middle")
    return svg.finish()


def render_all(rows: Sequence[dict[str, Any]], metadata: dict[str, Any], output_dir: Path,
               source_override: str | None = None) -> list[Path]:
    source = source_override or str(metadata.get("source_note") or "Experiment 02 final analysis output")
    output_dir.mkdir(parents=True, exist_ok=True)
    renderers = (
        ("accuracy_by_condition.svg", render_accuracy(rows, source)),
        ("equal_budget_routing.svg", render_equal_budget(rows, source)),
        ("accuracy_vs_calls.svg", render_frontier(rows, source, cost=False)),
        ("primary_paired_outcomes.svg", render_paired(rows, source)),
        ("block_sensitivity.svg", render_blocks(rows, source)),
        ("format_retry_reliability.svg", render_reliability(rows, source)),
        ("accuracy_vs_cost.svg", render_frontier(rows, source, cost=True)),
    )
    written = []
    for filename, document in renderers:
        if document is None:
            continue
        path = output_dir / filename
        path.write_text(document, encoding="utf-8")
        ET.fromstring(document)  # Fail immediately if a renderer emitted invalid XML.
        written.append(path)
    return written


def synthetic_payload() -> dict[str, Any]:
    conditions = []
    bases = {"Direct": (0.42, 1), "Vote10": (0.54, 10), "Swarm10": (0.60, 10),
             "Vote20": (0.58, 20), "Tournament20": (0.66, 20)}
    for method, (base, calls) in bases.items():
        for model, lift in (("light", 0.0), ("medium", 0.08)):
            conditions.append({"method": method, "reasoning": model, "exact_accuracy": {"estimate": base + lift, "ci95": [base + lift - 0.03, base + lift + 0.03]},
                               "deployment_calls": calls, "cost": {"estimate": calls * (0.002 if model == "light" else 0.004)},
                               "format_rate": {"estimate": 0.98 - calls * 0.001},
                               "retry_rate": 0.01 + calls * 0.001})
    blocks = []
    for block_index, delta in enumerate((-0.03, 0.01, -0.01, 0.03), 1):
        for method in ("Direct", "Swarm10"):
            for model, lift in (("light", 0.0), ("medium", 0.08)):
                blocks.append({"block": f"B{block_index}", "reasoning": model,
                               "methods": {method: {"exact_accuracy": {"estimate": bases[method][0] + lift + delta}}}})
    return {"metadata": {"source_note": "Synthetic self-test data: not experimental results; provider effort low"},
            "conditions": conditions,
            "comparisons": [{"left": "Vote20", "right": "Tournament20", "reasoning": "medium",
                             "primary": True, "right_only_wins": 30, "left_only_wins": 20,
                             "both_correct": 25, "both_wrong": 25,
                             "difference": 0.08, "ci95": [0.02, 0.14]}],
            "blocks": blocks}


def realistic_analyzer_payload() -> dict[str, Any]:
    """Run the sibling analyzer on scored-like rows for a contract smoke test."""
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from analyze_results import analyze
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting

    cases = []
    calls = {"Direct expected": 1, "Vote10": 10, "Swarm10": 10,
             "Vote20": 20, "Tournament20": 20}
    for block in range(1, 5):
        for index in range(12):
            base = (block + index) % 2 == 0
            for reasoning in ("Light reasoning", "Medium reasoning"):
                medium = reasoning == "Medium reasoning"
                exact = {
                    "Direct expected": 0.50 if medium else 0.25,
                    "Vote10": base,
                    "Swarm10": base or medium,
                    "Vote20": (block + index) % 3 != 0,
                    "Tournament20": (block + index) % 4 != 0 if medium else base,
                }
                methods = {}
                for method, deployment_calls in calls.items():
                    value = exact[method]
                    methods[method] = {
                        "exact": value,
                        "term_accuracy": float(value),
                        "format_compliant": method != "Tournament20" or index != 0,
                        "per_term": [float(value)] * 5,
                        "deployment_calls": deployment_calls,
                        "cost": {
                            "total_tokens": deployment_calls * 100,
                            "provider_cost_usd": deployment_calls * 0.002,
                        },
                    }
                cases.append({"case_id": f"C{block}{index}", "block": f"B{block:02d}",
                              "reasoning": reasoning, "methods": methods})
    payload = analyze({"cases": cases}, replicates=120, seed=17)
    payload["metadata"] = {"source_note": "Realistic analyze_results integration fixture: not experimental results"}
    payload["operational_reliability"] = [
        {
            "reasoning": reasoning,
            "method": method,
            "format_rate": 0.97,
            "retry_failure_rate": 0.03 if method == "Tournament20" and reasoning == "Medium reasoning" else 0.01,
        }
        for reasoning in ("Light reasoning", "Medium reasoning")
        for method in ("Direct", "Vote10", "Swarm10", "Vote20", "Tournament20")
    ]
    return payload


def run_self_test() -> int:
    payload = synthetic_payload()
    with tempfile.TemporaryDirectory(prefix="experiment-02-svg-test-") as temp:
        input_path = Path(temp) / "analysis.json"
        input_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        rows, metadata = load_inputs([input_path])
        paths = render_all(rows, metadata, Path(temp) / "plots")
        expected = {"accuracy_by_condition.svg", "equal_budget_routing.svg", "accuracy_vs_calls.svg",
                    "primary_paired_outcomes.svg", "block_sensitivity.svg",
                    "format_retry_reliability.svg", "accuracy_vs_cost.svg"}
        actual = {path.name for path in paths}
        if actual != expected:
            raise AssertionError(f"expected {sorted(expected)}, rendered {sorted(actual)}")
        for path in paths:
            root = ET.parse(path).getroot()
            if not root.tag.endswith("svg") or path.stat().st_size < 1000:
                raise AssertionError(f"invalid or unexpectedly small SVG: {path}")
            text = path.read_text(encoding="utf-8")
            if "Synthetic self-test data" not in text or re.search(r"\blow\b", text, flags=re.IGNORECASE):
                raise AssertionError(f"source/public terminology check failed: {path}")
        accuracy_text = (Path(temp) / "plots" / "accuracy_by_condition.svg").read_text(encoding="utf-8")
        if "42.0%" not in accuracy_text:
            raise AssertionError("aggregate accuracy was replaced by a block-level estimate")
        second_paths = render_all(rows, metadata, Path(temp) / "plots-second")
        for first_path, second_path in zip(paths, second_paths):
            if first_path.read_bytes() != second_path.read_bytes():
                raise AssertionError(f"nondeterministic output: {first_path.name}")

        realistic_path = Path(temp) / "realistic-analysis.json"
        realistic_path.write_text(json.dumps(realistic_analyzer_payload(), sort_keys=True), encoding="utf-8")
        realistic_rows, realistic_metadata = load_inputs([realistic_path])
        integration_paths = render_all(realistic_rows, realistic_metadata, Path(temp) / "integration-plots")
        integration_names = {path.name for path in integration_paths}
        if integration_names != expected:
            raise AssertionError(f"analyzer integration expected {sorted(expected)}, rendered {sorted(integration_names)}")
        paired_text = (Path(temp) / "integration-plots" / "primary_paired_outcomes.svg").read_text(encoding="utf-8")
        if "Medium reasoning Tournament20 vs Medium reasoning Vote20" not in paired_text:
            raise AssertionError("top-level analyzer primary contrast was not rendered")
        reliability_text = (Path(temp) / "integration-plots" / "format_retry_reliability.svg").read_text(encoding="utf-8")
        if "Retry/failure rate" not in reliability_text or "3.0%" not in reliability_text:
            raise AssertionError("operational reliability retry/failure rate was not rendered")
    print("self-test passed: 7 deterministic SVG charts plus analyze_results integration smoke test")
    return 0


def default_inputs(experiment_dir: Path) -> list[Path]:
    canonical = experiment_dir / "results" / "analysis.json"
    summary = experiment_dir / "results" / "final_summary.csv"
    return [path for path in (canonical, summary) if path.exists()]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    script = Path(__file__).resolve()
    experiment_dir = script.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", dest="inputs",
                        help="analysis JSON or summary CSV; repeat to merge files")
    parser.add_argument("--output-dir", type=Path, default=experiment_dir / "plots",
                        help="destination directory (default: experiment/plots)")
    parser.add_argument("--source-note", help="override the footer source note")
    parser.add_argument("--self-test", action="store_true", help="render and validate synthetic charts in a temporary directory")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    script = Path(__file__).resolve()
    inputs = args.inputs or default_inputs(script.parent.parent)
    if not inputs:
        print("No result data found. Pass --input or create results/analysis.json. No charts were written.", file=sys.stderr)
        return 2
    try:
        rows, metadata = load_inputs(inputs)
        written = render_all(rows, metadata, args.output_dir, args.source_note)
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as error:
        print(f"render error: {error}", file=sys.stderr)
        return 1
    if not written:
        print("Inputs contained no recognized chart data. No charts were written.", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
