#!/usr/bin/env python3
"""Render the Experiment 05 public charts with Python's standard library."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = EXPERIMENT_DIR.parent
RESULTS_DIR = EXPERIMENT_DIR / "results"
OUTPUT_DIR = SEED_DIR / "images" / "stage-2"
WIDTH = 1600
HEIGHT = 900

BG = "#090b12"
PANEL = "#111522"
GRID = "#2b3040"
TEXT = "#f4f3ee"
MUTED = "#aeb4c2"
CYAN = "#4de2ff"
VIOLET = "#a78bfa"
GOLD = "#ffd166"
GREEN = "#63e6be"
RED = "#ff7a90"


def text(x: float, y: float, value: str, size: int, *, fill: str = TEXT,
         weight: int = 400, anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" '
        f'font-family="Inter, ui-sans-serif, system-ui, -apple-system, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
        f'{escape(value)}</text>'
    )


def svg_document(title: str, description: str, body: list[str]) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{escape(title)}</title>",
        f"<desc id=\"desc\">{escape(description)}</desc>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>',
        *body,
        "</svg>",
        "",
    ])


def write_svg(name: str, title: str, description: str, body: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(
        svg_document(title, description, body), encoding="utf-8"
    )


def load_progress() -> list[dict[str, str]]:
    with (RESULTS_DIR / "fresh-gate-progress.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def load_gate03() -> dict:
    path = RESULTS_DIR / "fresh-80-gate-03" / "score.json"
    return json.loads(path.read_text(encoding="utf-8"))


def render_progress(rows: list[dict[str, str]]) -> None:
    primary = [
        row for row in rows
        if row["status"] != "posthoc_development_only"
    ]
    posthoc = next(
        row for row in rows if row["status"] == "posthoc_development_only"
    )
    body = [
        text(110, 105, "THE SEARCH LEARNED TO VERIFY", 52, weight=500),
        text(110, 158, "Fresh 24-sequence gates, exact next-five accuracy", 25, fill=MUTED),
    ]
    left, right, top, bottom = 180, 1460, 250, 735
    for pct in (40, 50, 60, 70, 80, 90, 100):
        y = bottom - (pct - 40) / 60 * (bottom - top)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        body.append(text(left - 24, y + 8, f"{pct}%", 20, fill=MUTED, anchor="end"))
    labels = ["Gate 01", "Gate 02", "Gate 03"]
    xs = [330, 820, 1310]
    for x, label in zip(xs, labels):
        body.append(text(x, 792, label, 23, fill=MUTED, anchor="middle"))

    def y_for(value: float) -> float:
        return bottom - (value * 100 - 40) / 60 * (bottom - top)

    base = [float(row["base_accuracy"]) for row in primary]
    adaptive = [float(row["exact_accuracy"]) for row in primary]
    for series_index, (values, color, label) in enumerate(((base, VIOLET, "15-lens plurality"), (adaptive, CYAN, "adaptive system"))):
        points = " ".join(f"{x},{y_for(value):.1f}" for x, value in zip(xs, values))
        body.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>')
        for point_index, (x, value) in enumerate(zip(xs, values)):
            y = y_for(value)
            body.append(f'<circle cx="{x}" cy="{y:.1f}" r="13" fill="{BG}" stroke="{color}" stroke-width="7"/>')
            label_offset = 48 if series_index == 1 and point_index == 0 else -28
            body.append(text(x, y + label_offset, f"{value:.1%}", 25, fill=color, weight=500, anchor="middle"))
        body.append(text(1460, y_for(values[-1]) + (44 if series_index == 0 else 47), label, 22, fill=color, anchor="end"))

    p_value = float(posthoc["exact_accuracy"])
    p_y = y_for(p_value)
    body.extend([
        f'<circle cx="820" cy="{p_y:.1f}" r="12" fill="{BG}" stroke="{GOLD}" stroke-width="5" stroke-dasharray="5 4"/>',
        text(845, p_y - 12, "87.5% development replay", 20, fill=GOLD),
        text(845, p_y + 18, "not a validation result", 18, fill=MUTED),
        text(110, 858, "Gate 03 froze the rule before generating the cases.", 21, fill=MUTED),
    ])
    write_svg(
        "fresh-gate-progress.svg",
        "Adaptive sequence accuracy across three fresh gates",
        "The base plurality rises from 58.3 to 66.7 percent. The adaptive system rises from 54.2 to 91.7 percent. A Gate 02 post-hoc replay at 87.5 percent is labeled development only.",
        body,
    )


def render_outcomes(score: dict) -> None:
    decisions = score["case_decisions"]
    categories = []
    for case_id in sorted(decisions):
        row = decisions[case_id]
        if row["base_exact"] and row["final_exact"]:
            category = "stayed_correct"
        elif not row["base_exact"] and row["final_exact"]:
            category = "corrected"
        elif row["base_exact"] and not row["final_exact"]:
            category = "harmed"
        else:
            category = "still_wrong"
        categories.append((case_id, category))
    order = {"stayed_correct": 0, "corrected": 1, "still_wrong": 2, "harmed": 3}
    categories.sort(key=lambda item: (order[item[1]], item[0]))
    colors = {
        "stayed_correct": VIOLET,
        "corrected": GREEN,
        "still_wrong": "#555d70",
        "harmed": RED,
    }
    counts = {key: sum(cat == key for _, cat in categories) for key in order}
    body = [
        text(110, 105, "VISIBLE CHECKS FIXED 6 ERRORS", 52, weight=500),
        text(110, 158, "Gate 03, 24 fresh sequences", 25, fill=MUTED),
    ]
    start_x, start_y, size, gap = 170, 275, 140, 25
    for index, (case_id, category) in enumerate(categories):
        col, row = index % 8, index // 8
        x = start_x + col * (size + gap)
        y = start_y + row * (size + gap)
        body.extend([
            f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="22" fill="{colors[category]}" fill-opacity="0.88"/>',
            text(x + size / 2, y + 64, case_id, 22, fill=BG, weight=500, anchor="middle"),
            text(x + size / 2, y + 96, "fixed" if category == "corrected" else "correct" if category == "stayed_correct" else "missed" if category == "still_wrong" else "harmed", 17, fill=BG, anchor="middle"),
        ])
    body.extend([
        text(110, 844, f"{counts['stayed_correct']} stayed correct", 22, fill=VIOLET),
        text(450, 844, f"+{counts['corrected']} corrected", 22, fill=GREEN),
        text(730, 844, f"{counts['still_wrong']} remained wrong", 22, fill=MUTED),
        text(1100, 844, f"{counts['harmed']} harmful overrides", 22, fill=RED),
    ])
    write_svg(
        "gate03-paired-outcomes.svg",
        "Gate 03 paired outcomes",
        "Sixteen base answers stayed correct, six base errors were corrected, two remained wrong, and no correct base answer was harmed.",
        body,
    )


def render_flow(score: dict) -> None:
    body = [
        text(110, 105, "SPEND MORE REASONING ONLY WHERE NEEDED", 52, weight=500),
        text(110, 158, "The frozen Gate 03 orchestration", 25, fill=MUTED),
    ]
    stages = [
        ("15 base lenses", "24 sequences", "60 bundled calls", 360, CYAN),
        ("Visible holdout", "11 uncertain sequences", "88 calls", 88, VIOLET),
        ("Recovery", "8 weakly verified sequences", "64 calls", 64, GOLD),
        ("Worksheets", "7 unresolved sequences", "56 calls", 56, GREEN),
    ]
    xs = [115, 500, 885, 1270]
    for index, ((name, scope, calls, analyses, color), x) in enumerate(zip(stages, xs)):
        body.extend([
            f'<rect x="{x}" y="280" width="280" height="300" rx="28" fill="{PANEL}" stroke="{color}" stroke-width="3"/>',
            text(x + 30, 340, f"0{index + 1}", 21, fill=color, weight=500),
            text(x + 30, 405, name, 29, weight=500),
            text(x + 30, 452, scope, 20, fill=MUTED),
            text(x + 30, 520, calls, 27, fill=color, weight=500),
        ])
        if index < len(stages) - 1:
            body.extend([
                f'<line x1="{x + 280}" y1="430" x2="{xs[index + 1] - 28}" y2="430" stroke="{GRID}" stroke-width="5"/>',
                f'<path d="M {xs[index + 1] - 28} 430 l -18 -11 v 22 z" fill="{GRID}"/>',
            ])
    body.extend([
        text(250, 690, "268", 74, fill=TEXT, weight=500, anchor="middle"),
        text(250, 730, "actual Luna Light calls", 21, fill=MUTED, anchor="middle"),
        text(800, 690, "568", 74, fill=TEXT, weight=500, anchor="middle"),
        text(800, 730, "per-sequence analyses", 21, fill=MUTED, anchor="middle"),
        text(1350, 690, "22 / 24", 74, fill=GREEN, weight=500, anchor="middle"),
        text(1350, 730, "exact next-five answers", 21, fill=MUTED, anchor="middle"),
        text(110, 838, "Base calls handled six independent sequences each. Later calls handled one sequence each.", 20, fill=MUTED),
    ])
    write_svg(
        "adaptive-call-flow.svg",
        "Adaptive call flow",
        "Fifteen base lenses analyze all 24 sequences. Extra calls are routed to 11, then 8, then 7 difficult cases. The run uses 268 actual Luna Light calls and 568 per-sequence analyses to solve 22 of 24 sequences.",
        body,
    )


def render_family(score: dict) -> None:
    family_rows = sorted(score["family_exact"].items())
    body = [
        text(110, 105, "THE RESULT WAS BROAD, NOT UNIFORM", 52, weight=500),
        text(110, 158, "Exact next-five answers by generator family", 25, fill=MUTED),
    ]
    left, top = 250, 245
    bar_width, row_gap = 1030, 68
    for index, (family, values) in enumerate(family_rows):
        y = top + index * row_gap
        exact, total = values["exact"], values["cases"]
        body.extend([
            text(left - 28, y + 27, family, 21, fill=MUTED, anchor="end"),
            f'<rect x="{left}" y="{y}" width="{bar_width}" height="34" rx="17" fill="{GRID}"/>',
            f'<rect x="{left}" y="{y}" width="{bar_width * exact / total:.1f}" height="34" rx="17" fill="{GREEN if exact == total else GOLD}"/>',
            text(left + bar_width + 28, y + 27, f"{exact}/{total}", 22, fill=GREEN if exact == total else GOLD, weight=500),
        ])
    body.extend([
        text(250, 828, "6 families perfect", 24, fill=GREEN, weight=500),
        text(640, 828, "AFFINE and GROWBLOCK: 2/3", 24, fill=GOLD, weight=500),
    ])
    write_svg(
        "gate03-family-results.svg",
        "Gate 03 accuracy by sequence family",
        "Six of eight sequence families scored three of three. Affine and growing-block families scored two of three.",
        body,
    )


def render_holdout_example() -> None:
    body = [
        text(110, 100, "A REAL CORRECTION: S016", 52, weight=500),
        text(110, 153, "Predict the hidden public suffix before the unknown future", 25, fill=MUTED),
        text(110, 235, "BASE PLURALITY", 19, fill=VIOLET, weight=500),
        text(330, 235, "44, -2, 8, 79, 71", 28, fill=VIOLET, weight=500),
        text(700, 235, "wrong", 20, fill=RED),
        text(110, 310, "VISIBLE HOLDOUT", 19, fill=GOLD, weight=500),
        text(330, 310, "agent sees terms 1 to 12", 23, fill=MUTED),
        text(760, 310, "must recover", 20, fill=MUTED),
        text(915, 310, "24, 60", 28, fill=GOLD, weight=500),
        text(1070, 310, "before forecasting", 20, fill=MUTED),
        text(110, 385, "VERIFIED OUTPUT", 19, fill=GREEN, weight=500),
        text(330, 385, "24, 60", 28, fill=GOLD, weight=500),
        text(470, 385, "|", 28, fill=MUTED),
        text(505, 385, "8, -2, 44, 79, 28", 28, fill=GREEN, weight=500),
        text(875, 385, "exact", 20, fill=GREEN),
        f'<line x1="110" y1="438" x2="1490" y2="438" stroke="{GRID}" stroke-width="2"/>',
        text(110, 492, "WHY IT WORKS", 19, fill=CYAN, weight=500),
        text(330, 492, "Split every fourth term. Each row has a linear change in its step.", 23, fill=MUTED),
    ]
    rows = [
        ("positions 1,5,9...", ["6", "5", "11", "24", "44"], "steps -1, 6, 13, 20  (+7)"),
        ("positions 2,6,10...", ["27", "34", "45", "60", "79"], "steps 7, 11, 15, 19  (+4)"),
        ("positions 3,7,11...", ["-28", "-20", "-8", "8", "28"], "steps 8, 12, 16, 20  (+4)"),
        ("positions 4,8,12...", ["-20", "-16", "-10", "-2", ""], "steps 4, 6, 8  (+2)"),
    ]
    for row_index, (label, values, step_label) in enumerate(rows):
        y = 570 + row_index * 70
        body.append(text(110, y, label, 18, fill=MUTED))
        for value_index, value in enumerate(values):
            x = 390 + value_index * 130
            if not value:
                continue
            is_withheld = (row_index, value_index) in {(0, 3), (1, 3)}
            is_future = value_index == 4 or (row_index in (2, 3) and value_index == 3)
            color = GOLD if is_withheld else GREEN if is_future else TEXT
            body.append(text(x, y, value, 24, fill=color, weight=500, anchor="middle"))
            if value_index < 4 and values[value_index + 1]:
                body.append(f'<line x1="{x + 35}" y1="{y - 8}" x2="{x + 95}" y2="{y - 8}" stroke="{GRID}" stroke-width="3"/>')
        body.append(text(1100, y, step_label, 18, fill=CYAN))
    body.extend([
        text(110, 862, "Gold terms were already public but hidden from the verifier. Green terms are the continuation.", 19, fill=MUTED),
    ])
    write_svg(
        "visible-holdout-example.svg",
        "A concrete visible-holdout correction",
        "On sequence S016 the base plurality was wrong. Holdout agents first recovered the removed public terms 24 and 60, then correctly predicted 8, minus 2, 44, 79, and 28. The sequence splits into four residue streams whose step changes are linear.",
        body,
    )


def main() -> int:
    progress = load_progress()
    gate03 = load_gate03()
    render_progress(progress)
    render_outcomes(gate03)
    render_flow(gate03)
    render_family(gate03)
    render_holdout_example()
    print(json.dumps({"output_dir": str(OUTPUT_DIR), "charts": 5}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
