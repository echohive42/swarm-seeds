#!/usr/bin/env python3
"""Render Experiment 03 publication charts using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


COLORS = {
    "blue": "#0072B2",
    "orange": "#D55E00",
    "green": "#009E73",
    "gold": "#E69F00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "gray": "#6B7280",
    "dark": "#17212B",
    "grid": "#D8DEE6",
    "pale": "#F3F6F9",
    "white": "#FFFFFF",
}

METHOD_LABELS = {
    "Vote10": "Generalist Vote10",
    "FIXED-SWARM10": "Fixed Swarm10",
    "G-498E470E7808": "Best founder",
    "G-1407BDDB752D": "Evolved champion",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def pp(value: float) -> str:
    return f"{100 * value:+.1f} pp"


class SVG:
    def __init__(self, width: int, height: int, title: str, description: str, source_digest: str):
        self.width = width
        self.height = height
        self.parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">',
            f'<title id="chart-title">{esc(title)}</title>',
            f'<desc id="chart-desc">{esc(description)}</desc>',
            f'<metadata>source-digest:{source_digest}</metadata>',
            "<style>text{font-family:Inter,Arial,sans-serif;fill:#17212B}"
            ".title{font-size:25px;font-weight:700}.subtitle{font-size:13px;fill:#4B5563}"
            ".axis{font-size:12px;fill:#374151}.label{font-size:13px;font-weight:600}"
            ".value{font-size:12px;font-weight:700}.note{font-size:11px;fill:#59636E}"
            ".small{font-size:10px;fill:#59636E}.legend{font-size:12px;font-weight:600}</style>",
            f'<rect width="{width}" height="{height}" fill="{COLORS["white"]}"/>',
        ]

    @staticmethod
    def attrs(values: dict[str, Any]) -> str:
        return " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in values.items())

    def rect(self, x: float, y: float, width: float, height: float, **attrs: Any) -> None:
        self.parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(0, width):.2f}" '
            f'height="{max(0, height):.2f}" {self.attrs(attrs)}/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, **attrs: Any) -> None:
        self.parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {self.attrs(attrs)}/>'
        )

    def circle(self, x: float, y: float, radius: float, **attrs: Any) -> None:
        self.parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" {self.attrs(attrs)}/>')

    def polyline(self, points: Iterable[tuple[float, float]], **attrs: Any) -> None:
        joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.parts.append(f'<polyline points="{joined}" {self.attrs(attrs)}/>')

    def text(self, x: float, y: float, value: Any, css: str = "axis", anchor: str = "start", **attrs: Any) -> None:
        self.parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" class="{css}" text-anchor="{anchor}" '
            f'{self.attrs(attrs)}>{esc(value)}</text>'
        )

    def finish(self) -> str:
        return "\n".join(self.parts + ["</svg>", ""])


def heading(svg: SVG, title: str, subtitle: str, source: str) -> None:
    svg.text(52, 44, title, "title")
    svg.text(52, 69, subtitle, "subtitle")
    svg.text(52, svg.height - 18, f"Source: {source}", "note")


def y_axis(svg: SVG, left: float, top: float, width: float, height: float) -> None:
    for index in range(6):
        value = index / 5
        y = top + height * (1 - value)
        svg.line(left, y, left + width, y, stroke=COLORS["grid"], stroke_width=1)
        svg.text(left - 12, y + 4, pct(value), "axis", "end")
    svg.line(left, top, left, top + height, stroke=COLORS["dark"], stroke_width=1.2)
    svg.line(left, top + height, left + width, top + height, stroke=COLORS["dark"], stroke_width=1.2)
    label_x = left - 70
    svg.text(label_x, top + height / 2, "Exact accuracy", "axis", "middle",
             transform=f"rotate(-90 {label_x:.2f} {top + height / 2:.2f})")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def final_accuracy_chart(summary: dict[str, Any], digest: str) -> str:
    methods = summary["methods"]
    order = ("Vote10", "FIXED-SWARM10", "G-498E470E7808", "G-1407BDDB752D")
    colors = (COLORS["gray"], COLORS["sky"], COLORS["gold"], COLORS["green"])
    svg = SVG(1100, 680, "Final exact accuracy with 95% intervals",
              "Four final methods evaluated on the same 48 hidden cases.", digest)
    heading(svg, "Final exact accuracy", "Same 48 hidden final cases; bars show paired-sample accuracy and percentile 95% intervals",
            "results/final/summary.json")
    left, top, width, height = 110, 125, 930, 410
    y_axis(svg, left, top, width, height)
    slot = width / len(order)
    bar_width = 92
    for index, (method_id, color) in enumerate(zip(order, colors)):
        row = methods[method_id]
        estimate = float(row["exact_accuracy"])
        low, high = map(float, row["exact_ci95"])
        center = left + slot * (index + 0.5)
        y = top + height * (1 - estimate)
        svg.rect(center - bar_width / 2, y, bar_width, top + height - y, fill=color, rx=4)
        low_y = top + height * (1 - low)
        high_y = top + height * (1 - high)
        svg.line(center, high_y, center, low_y, stroke=COLORS["dark"], stroke_width=2.5)
        svg.line(center - 13, high_y, center + 13, high_y, stroke=COLORS["dark"], stroke_width=2.5)
        svg.line(center - 13, low_y, center + 13, low_y, stroke=COLORS["dark"], stroke_width=2.5)
        svg.circle(center, y, 5, fill=COLORS["dark"])
        svg.text(center, high_y - 11, pct(estimate), "value", "middle")
        svg.text(center, top + height + 26, METHOD_LABELS[method_id], "label", "middle")
        svg.text(center, top + height + 45, method_id, "small", "middle")
        svg.text(center, top + height + 64, f"{row['exact_cases']}/48 exact", "note", "middle")
    svg.text(left + width, 101, "Intervals reflect case uncertainty, not independent method samples.", "note", "end")
    return svg.finish()


def best_generation(summary: dict[str, Any]) -> dict[str, Any]:
    return max(summary["genome_scores"], key=lambda row: (
        int(row["exact_cases"]), -int(row["harmful_overrides"]), int(row["term_correct"]),
        int(row["format_valid"]), str(row["genome_id"]),
    ))


def trajectory_chart(search: list[dict[str, Any]], validation: dict[str, Any], final: dict[str, Any], digest: str) -> str:
    points: list[dict[str, Any]] = []
    for generation, summary in enumerate(search):
        winner = best_generation(summary)
        method = summary["methods"][winner["genome_id"]]
        points.append({"stage": f"Generation {generation}", "id": winner["genome_id"], "n": 12,
                       "accuracy": method["exact_accuracy"], "ci": method["exact_ci95"], "kind": "training"})
    validation_id = "G-1407BDDB752D"
    validation_row = validation["methods"][validation_id]
    points.append({"stage": "Validation", "id": validation_id, "n": 24,
                   "accuracy": validation_row["exact_accuracy"], "ci": validation_row["exact_ci95"], "kind": "validation"})
    final_row = final["methods"][validation_id]
    points.append({"stage": "Final", "id": validation_id, "n": 48,
                   "accuracy": final_row["exact_accuracy"], "ci": final_row["exact_ci95"], "kind": "final"})

    svg = SVG(1100, 700, "Evolution and selection trajectory",
              "Best training genomes followed by the selected champion on validation and final cases.", digest)
    heading(svg, "Evolution and selection trajectory",
            "Best observed training genome per generation, then the frozen validation champion on held-out stages",
            "search summaries, validation summary, and final summary")
    left, top, width, height = 110, 145, 930, 390
    slot = width / len(points)
    x_values = [left + slot * (index + 0.5) for index in range(len(points))]
    svg.rect(left, top, slot * 3, height, fill="#EAF4FA", opacity=0.34)
    svg.rect(left + slot * 3, top, slot, height, fill="#FFF4E5", opacity=0.42)
    svg.rect(left + slot * 4, top, slot, height, fill="#E8F5EF", opacity=0.55)
    y_axis(svg, left, top, width, height)
    coords = [(x, top + height * (1 - float(point["accuracy"]))) for x, point in zip(x_values, points)]
    svg.polyline(coords, fill="none", stroke=COLORS["gray"], stroke_width=2, stroke_dasharray="6 5")
    for x, point in zip(x_values, points):
        low, high = map(float, point["ci"])
        y = top + height * (1 - float(point["accuracy"]))
        low_y, high_y = top + height * (1 - low), top + height * (1 - high)
        color = COLORS["blue"] if point["kind"] == "training" else COLORS["orange"] if point["kind"] == "validation" else COLORS["green"]
        svg.line(x, high_y, x, low_y, stroke=color, stroke_width=3)
        svg.line(x - 11, high_y, x + 11, high_y, stroke=color, stroke_width=3)
        svg.line(x - 11, low_y, x + 11, low_y, stroke=color, stroke_width=3)
        svg.circle(x, y, 8, fill=color, stroke=COLORS["white"], stroke_width=2)
        svg.text(x, y - 14, pct(float(point["accuracy"])), "value", "middle")
        svg.text(x, top + height + 28, point["stage"], "label", "middle")
        svg.text(x, top + height + 47, point["id"], "small", "middle")
        svg.text(x, top + height + 65, f"n={point['n']}", "note", "middle")
    svg.text(left + slot * 1.5, 125, "Training search", "legend", "middle")
    svg.text(left + slot * 3.5, 125, "Validation selection", "legend", "middle")
    svg.text(left + slot * 4.5, 125, "Frozen final test", "legend", "middle")
    svg.text(left, 625, "Samples differ across stages; the connected line traces the selection process, not repeated measurement on one sample.", "note")
    return svg.finish()


def complementarity_chart(comparisons: dict[str, Any], digest: str) -> str:
    primary = comparisons["primary"]
    categories = [
        ("Both correct", int(primary["both_correct"]), COLORS["green"]),
        ("Champion only", int(primary["left_only_wins"]), COLORS["blue"]),
        ("Generalist Vote10 only", int(primary["right_only_wins"]), COLORS["orange"]),
        ("Both wrong", int(primary["both_wrong"]), COLORS["gray"]),
    ]
    n = int(primary["n"])
    svg = SVG(1100, 620, "Final case complementarity",
              "Overlap and disagreement between the evolved champion and corrected generalist Vote10 on 48 final cases.", digest)
    heading(svg, "Champion and generalist Vote10 complementarity",
            "Amended paired outcomes on the same 48 hidden final cases", "results/final/comparisons.json")
    left, top, width = 230, 130, 760
    for index, (label, count, color) in enumerate(categories):
        y = top + index * 76
        svg.text(left - 22, y + 25, label, "label", "end")
        svg.rect(left, y, width, 38, fill=COLORS["pale"], rx=4)
        svg.rect(left, y, width * count / n, 38, fill=color, rx=4)
        svg.text(left + width * count / n + 12, y + 25, f"{count} ({100 * count / n:.1f}%)", "value")
    estimate = float(primary["estimate"])
    low, high = map(float, primary["ci95"])
    svg.text(550, 470, f"Paired exact-accuracy difference: {pp(estimate)}", "label", "middle")
    svg.text(550, 494, f"95% interval: [{pp(low)}, {pp(high)}]", "axis", "middle")
    left_only = int(primary["left_only_wins"])
    right_only = int(primary["right_only_wins"])
    svg.text(
        550,
        522,
        f"Discordant cases split {left_only} to {right_only}; superiority was not supported.",
        "note",
        "middle",
    )
    return svg.finish()


def inputs(experiment: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], list[Path]]:
    final_summary_path = experiment / "results/final/summary.json"
    final_comparisons_path = experiment / "results/final/comparisons.json"
    validation_path = experiment / "results/validation/summary.json"
    search_paths = [experiment / f"results/search/generation-{index:02d}/summary.json" for index in range(3)]
    paths = [final_summary_path, final_comparisons_path, validation_path, *search_paths]
    return (load_json(final_summary_path), load_json(final_comparisons_path),
            [load_json(path) for path in search_paths], load_json(validation_path), paths)


def documents(experiment: Path) -> dict[str, str]:
    final, comparisons, search, validation, paths = inputs(experiment)
    if int(final.get("n_cases", 0)) != 48 or int(comparisons.get("primary", {}).get("n", 0)) != 48:
        raise ValueError("final evidence must contain the registered 48 paired cases")
    digest = source_digest(paths)
    return {
        "final-exact-accuracy.svg": final_accuracy_chart(final, digest),
        "selection-trajectory.svg": trajectory_chart(search, validation, final, digest),
        "final-complementarity.svg": complementarity_chart(comparisons, digest),
    }


def validate_documents(expected: dict[str, str], output: Path) -> None:
    for filename, document in expected.items():
        ET.fromstring(document)
        if "\u2013" in document or "\u2014" in document:
            raise ValueError(f"forbidden dash punctuation in {filename}")
        path = output / filename
        if not path.exists():
            raise ValueError(f"missing chart: {path}")
        actual = path.read_text(encoding="utf-8")
        ET.fromstring(actual)
        if actual != document:
            raise ValueError(f"stale or non-deterministic chart: {path}")


def parse_args() -> argparse.Namespace:
    script = Path(__file__).resolve()
    seed = script.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=seed / "images")
    parser.add_argument("--check", action="store_true", help="validate existing charts against final result data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    experiment = Path(__file__).resolve().parent.parent
    expected = documents(experiment)
    if args.check:
        validate_documents(expected, args.output_dir)
        print(f"validated {len(expected)} deterministic SVG charts")
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, document in expected.items():
        path = args.output_dir / filename
        path.write_text(document, encoding="utf-8")
        ET.fromstring(document)
        print(path)
    validate_documents(expected, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
