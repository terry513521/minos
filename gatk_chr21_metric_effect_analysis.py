#!/usr/bin/env python3
"""Analyze chr21 GATK parameter effects against AdvancedScorer metrics."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple


METRICS = [
    "score_100",
    "core_points",
    "completeness_points",
    "fp_points",
    "quality_points",
    "overcall_penalty",
    "fp_per_target",
    "region_fp_total",
]

LOWER_IS_BETTER = {"overcall_penalty", "fp_per_target", "region_fp_total"}


def as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return 1.0
        if low == "false":
            return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def rank(values: List[float]) -> List[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg
        i = j
    return ranks


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 8:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    sx = math.sqrt(sum(x * x for x in dx))
    sy = math.sqrt(sum(y * y for y in dy))
    if sx == 0 or sy == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / (sx * sy)


def spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    return pearson(rank(xs), rank(ys))


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def region_bin(row: Dict[str, Any], bin_bp: int) -> int:
    center = as_float(row.get("center")) or 0.0
    return int(center // bin_bp)


def residualize(rows: List[Dict[str, Any]], field: str, bin_bp: int) -> Dict[int, float]:
    by_bin: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        value = as_float(row.get(field))
        if value is None:
            continue
        by_bin[region_bin(row, bin_bp)].append((idx, value))

    out: Dict[int, float] = {}
    for values in by_bin.values():
        med = median(v for _, v in values)
        for idx, value in values:
            out[idx] = value - med
    return out


def metric_effect_words(metric: str, corr: Optional[float]) -> str:
    if corr is None:
        return "n/a"
    beneficial = -corr if metric in LOWER_IS_BETTER else corr
    if abs(corr) < 0.10:
        return "weak"
    if beneficial > 0:
        return "improves"
    return "hurts"


def direction(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if abs(value) < 0.10:
        return "weak"
    return "higher better" if value > 0 else "lower better"


def analyze(rows: List[Dict[str, Any]], bin_bp: int) -> List[Dict[str, Any]]:
    cfg_fields = sorted(k for k in rows[0] if k.startswith("cfg_"))
    metric_resid = {metric: residualize(rows, metric, bin_bp) for metric in METRICS}
    results: List[Dict[str, Any]] = []

    for field in cfg_fields:
        param_resid = residualize(rows, field, bin_bp)
        values = [as_float(row.get(field)) for row in rows]
        numeric_values = [v for v in values if v is not None]
        if len(numeric_values) < 20 or len(set(numeric_values)) < 2:
            continue

        result: Dict[str, Any] = {
            "parameter": field.removeprefix("cfg_"),
            "n": len(numeric_values),
            "unique_values": len(set(numeric_values)),
            "min_value": min(numeric_values),
            "median_value": median(numeric_values),
            "max_value": max(numeric_values),
        }

        beneficial_scores: List[float] = []
        for metric in METRICS:
            xs: List[float] = []
            ys: List[float] = []
            for idx in set(param_resid) & set(metric_resid[metric]):
                xs.append(param_resid[idx])
                ys.append(metric_resid[metric][idx])
            corr = spearman(xs, ys)
            result[f"{metric}_corr"] = "" if corr is None else round(corr, 4)
            result[f"{metric}_effect"] = metric_effect_words(metric, corr)
            if corr is not None:
                beneficial_scores.append(-corr if metric in LOWER_IS_BETTER else corr)

        primary = [
            result.get("score_100_corr"),
            result.get("core_points_corr"),
            result.get("completeness_points_corr"),
            result.get("fp_points_corr"),
            result.get("quality_points_corr"),
        ]
        primary_floats = [float(v) for v in primary if v != ""]
        overcall = [
            result.get("overcall_penalty_corr"),
            result.get("fp_per_target_corr"),
            result.get("region_fp_total_corr"),
        ]
        overcall_floats = [-float(v) for v in overcall if v != ""]
        result["score_direction"] = direction(float(result["score_100_corr"]) if result["score_100_corr"] != "" else None)
        result["avg_scorer_benefit"] = round(sum(primary_floats) / len(primary_floats), 4) if primary_floats else ""
        result["avg_overcall_benefit"] = round(sum(overcall_floats) / len(overcall_floats), 4) if overcall_floats else ""
        all_benefit = primary_floats + overcall_floats
        result["overall_benefit_index"] = round(sum(all_benefit) / len(all_benefit), 4) if all_benefit else ""
        results.append(result)

    results.sort(key=lambda r: abs(float(r["score_100_corr"] or 0.0)), reverse=True)
    return results


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    preferred = [
        "parameter", "n", "unique_values", "min_value", "median_value", "max_value",
        "score_direction", "overall_benefit_index", "avg_scorer_benefit", "avg_overcall_benefit",
    ]
    fields = preferred + [k for k in rows[0] if k not in preferred]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any) -> str:
    if value == "":
        return "n/a"
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return str(value)


def write_report(path: Path, results: List[Dict[str, Any]], source_csv: Path, bin_bp: int) -> None:
    lines = [
        "# chr21 GATK Parameter Effects vs AdvancedScorer Metrics",
        "",
        f"Source: `{source_csv}`",
        f"Region control: subtract median within `{bin_bp:,}` bp center bins before rank correlation.",
        "",
        "Positive correlations help score-like metrics. For overcall metrics, negative correlations are good because lower is better.",
        "",
        "## Strongest Score Effects",
        "",
        "| parameter | score | core | complete | fp | quality | overcall penalty | fp/target | region FP | direction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in results[:18]:
        lines.append(
            f"| `{row['parameter']}` | {fmt(row['score_100_corr'])} | {fmt(row['core_points_corr'])} | "
            f"{fmt(row['completeness_points_corr'])} | {fmt(row['fp_points_corr'])} | "
            f"{fmt(row['quality_points_corr'])} | {fmt(row['overcall_penalty_corr'])} | "
            f"{fmt(row['fp_per_target_corr'])} | {fmt(row['region_fp_total_corr'])} | "
            f"{row['score_direction']} |"
        )

    lines += [
        "",
        "## Reading Guide",
        "",
        "- `score`: final AdvancedScorer score.",
        "- `core`: 60-point truth-weighted F1 component.",
        "- `complete`: 15-point recall/coverage component.",
        "- `fp`: 15-point assessed false-positive/call-count component.",
        "- `quality`: 10-point Ti/Tv and Het/Hom ratio component.",
        "- `overcall penalty`, `fp/target`, and `region FP` are lower-is-better guardrail metrics.",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default="/root/minos/chr21_gatk_advanced_history.csv")
    parser.add_argument("--out", default="/root/minos/chr21_gatk_parameter_metric_effects.csv")
    parser.add_argument("--report", default="/root/minos/chr21_gatk_parameter_metric_effects.md")
    parser.add_argument("--bin-bp", type=int, default=2_500_000)
    args = parser.parse_args()

    source_csv = Path(args.history)
    rows = load_rows(source_csv)
    results = analyze(rows, args.bin_bp)
    write_csv(Path(args.out), results)
    write_report(Path(args.report), results, source_csv, args.bin_bp)
    print(f"analyzed {len(rows)} rows and {len(results)} parameters")
    print(args.out)
    print(args.report)


if __name__ == "__main__":
    main()
