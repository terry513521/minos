#!/usr/bin/env python3
"""Export chr21 GATK history with AdvancedScorer components.

This produces flat CSV/JSONL files that are easier for optimization models and
human review than the nested rounds.json structure.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


GATK_LABELS = {"gatk", "newgatk", "oldgatk"}


def parse_region(region: str) -> Tuple[str, int, int]:
    chrom, coords = region.split(":", 1)
    start_s, end_s = coords.replace(",", "").split("-", 1)
    return chrom, int(start_s), int(end_s)


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def emphasis(metric: float, gamma: float) -> float:
    metric = max(0.0, min(metric, 0.999999))
    return 1.0 - (1.0 - metric) ** gamma


def ratio_penalty(delta: float, tolerance: float) -> float:
    return math.exp(-abs(delta) / tolerance)


def scorer_breakdown(metrics: Dict[str, Any]) -> Dict[str, float]:
    f1_snp = number(metrics.get("f1_snp"))
    f1_indel = number(metrics.get("f1_indel"))
    recall_snp = number(metrics.get("recall_snp"))
    recall_indel = number(metrics.get("recall_indel"))

    truth_total_snp = number(metrics.get("truth_total_snp"))
    truth_total_indel = number(metrics.get("truth_total_indel"))
    query_total_snp = number(metrics.get("query_total_snp"))
    query_total_indel = number(metrics.get("query_total_indel"))
    fp_snp = number(metrics.get("fp_snp"))
    fp_indel = number(metrics.get("fp_indel"))
    frac_na_snp = number(metrics.get("frac_na_snp"))
    frac_na_indel = number(metrics.get("frac_na_indel"))

    total_truth = truth_total_snp + truth_total_indel
    if total_truth <= 0:
        return {
            "weighted_f1_truth": 0.0,
            "core_component": 0.0,
            "completeness_component": 0.0,
            "fp_component": 0.0,
            "quality_component": 0.0,
            "core_points": 0.0,
            "completeness_points": 0.0,
            "fp_points": 0.0,
            "quality_points": 0.0,
            "raw_score_before_overcall": 0.0,
            "computed_advanced_score": 0.0,
        }

    weighted_f1 = (f1_snp * truth_total_snp + f1_indel * truth_total_indel) / total_truth
    core = emphasis(weighted_f1, gamma=0.5)

    avg_recall = (recall_snp + recall_indel) / 2.0
    coverage = 1.0 - max(frac_na_snp, frac_na_indel)
    completeness = (emphasis(avg_recall, gamma=3.0) + emphasis(coverage, gamma=2.0)) / 2.0

    total_fp = fp_snp + fp_indel
    total_calls = query_total_snp + query_total_indel
    fp_rate = total_fp / max(total_calls, 1.0)
    size_ratio = total_calls / max(total_truth, 1.0)
    target_fp = max(0.002, 1.0 / max(total_truth, 1.0))
    fp_pen = math.exp(-max(0.0, fp_rate - target_fp) / target_fp)
    size_pen = math.exp(-abs(size_ratio - 1.0) / 0.10)
    fp_component = (fp_pen + size_pen) / 2.0

    titv_truth = number(metrics.get("titv_truth_snp"))
    titv_query = number(metrics.get("titv_query_snp"))
    hethom_truth_snp = number(metrics.get("hethom_truth_snp"))
    hethom_query_snp = number(metrics.get("hethom_query_snp"))
    hethom_truth_indel = number(metrics.get("hethom_truth_indel"))
    hethom_query_indel = number(metrics.get("hethom_query_indel"))

    titv_penalties = []
    hethom_penalties = []
    if titv_truth > 0 and titv_query > 0:
        titv_penalties.append(ratio_penalty(titv_query - titv_truth, 0.1))
    if hethom_truth_snp > 0 and hethom_query_snp > 0:
        hethom_penalties.append(ratio_penalty(hethom_query_snp - hethom_truth_snp, 0.15))
    if hethom_truth_indel > 0 and hethom_query_indel > 0:
        hethom_penalties.append(ratio_penalty(hethom_query_indel - hethom_truth_indel, 0.15))

    titv_component = sum(titv_penalties) / len(titv_penalties) if titv_penalties else 1.0
    hethom_component = sum(hethom_penalties) / len(hethom_penalties) if hethom_penalties else 1.0
    quality = (titv_component + hethom_component) / 2.0

    overcall_penalty = number(metrics.get("overcall_penalty"))
    raw_score = 100.0 * (0.60 * core + 0.15 * completeness + 0.15 * fp_component + 0.10 * quality)
    computed = max(0.0, raw_score - overcall_penalty)

    return {
        "weighted_f1_truth": weighted_f1,
        "avg_recall": avg_recall,
        "coverage": coverage,
        "fp_rate": fp_rate,
        "size_ratio": size_ratio,
        "target_fp": target_fp,
        "titv_component": titv_component,
        "hethom_component": hethom_component,
        "core_component": core,
        "completeness_component": completeness,
        "fp_component": fp_component,
        "quality_component": quality,
        "core_points": 100.0 * 0.60 * core,
        "completeness_points": 100.0 * 0.15 * completeness,
        "fp_points": 100.0 * 0.15 * fp_component,
        "quality_points": 100.0 * 0.10 * quality,
        "raw_score_before_overcall": raw_score,
        "computed_advanced_score": computed,
    }


def flatten_rows(rounds: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for round_obj in rounds:
        for label, inst in (round_obj.get("instances") or {}).items():
            if label.lower() not in GATK_LABELS or not isinstance(inst, dict):
                continue
            region = inst.get("region") or round_obj.get("region")
            if not region:
                continue
            chrom, start, end = parse_region(region)
            if chrom != "chr21":
                continue
            metrics = inst.get("score_metrics") or {}
            config = inst.get("config_snapshot") or {}
            if not metrics or inst.get("score_100") is None:
                continue

            flat: Dict[str, Any] = {
                "round_id": inst.get("round_id") or round_obj.get("round_id"),
                "label": label,
                "tool": inst.get("tool") or "gatk",
                "region": region,
                "chrom": chrom,
                "start": start,
                "end": end,
                "center": (start + end) / 2.0,
                "window_bp": end - start,
                "score_100": number(inst.get("score_100")),
                "combined_final": number(inst.get("combined_final")),
                "rank": inst.get("rank"),
                "gap_to_leader": inst.get("gap_to_leader"),
                "runtime_seconds": number(inst.get("runtime_seconds")),
                "variant_count": number(inst.get("variant_count")),
            }
            for key in [
                "f1_snp", "precision_snp", "recall_snp", "tp_snp", "fp_snp", "fn_snp",
                "f1_indel", "precision_indel", "recall_indel", "tp_indel", "fp_indel", "fn_indel",
                "truth_total_snp", "truth_total_indel", "query_total_snp", "query_total_indel",
                "frac_na_snp", "frac_na_indel", "ti_tv_ratio", "het_hom_ratio",
                "titv_query_snp", "titv_truth_snp", "hethom_query_snp", "hethom_truth_snp",
                "hethom_query_indel", "hethom_truth_indel", "fp_per_target",
                "snp_fp_per_target", "region_fp_snp", "region_fp_indel", "region_fp_total",
                "overcall_penalty", "advanced_score",
            ]:
                flat[key] = metrics.get(key)
            flat.update(scorer_breakdown(metrics))
            for key, value in sorted(config.items()):
                flat[f"cfg_{key}"] = value
            rows.append(flat)
    rows.sort(key=lambda r: (r["center"], -(r["score_100"] or 0), r["round_id"] or ""))
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    preferred = [
        "round_id", "label", "tool", "region", "chrom", "start", "end", "center", "window_bp",
        "score_100", "computed_advanced_score", "combined_final", "rank", "gap_to_leader",
        "runtime_seconds", "variant_count", "weighted_f1_truth", "core_points",
        "completeness_points", "fp_points", "quality_points", "overcall_penalty",
        "raw_score_before_overcall", "f1_snp", "f1_indel", "precision_snp",
        "precision_indel", "recall_snp", "recall_indel", "fp_per_target",
        "region_fp_total", "titv_query_snp", "titv_truth_snp", "hethom_query_snp",
        "hethom_truth_snp", "hethom_query_indel", "hethom_truth_indel",
    ]
    ordered = [key for key in preferred if key in fieldnames] + [key for key in fieldnames if key not in preferred]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def summarize(rows: List[Dict[str, Any]], out_path: Path, csv_path: Path, jsonl_path: Path) -> None:
    scores = sorted(number(r.get("score_100")) for r in rows)
    top = sorted(rows, key=lambda r: number(r.get("score_100")), reverse=True)[:10]
    exact_near = min(rows, key=lambda r: abs(number(r.get("center")) - 25027963.0)) if rows else None

    def pct(p: float) -> float:
        if not scores:
            return 0.0
        idx = min(len(scores) - 1, max(0, round((len(scores) - 1) * p)))
        return scores[idx]

    lines = [
        "# chr21 GATK AdvancedScorer History",
        "",
        "Generated from `/root/minos/rounds.json`.",
        "",
        f"- Rows: {len(rows)} scored chr21 GATK/newgatk/oldgatk instances",
        f"- CSV: `{csv_path}`",
        f"- JSONL: `{jsonl_path}`",
        f"- Score min/median/max: {pct(0):.2f} / {pct(0.5):.2f} / {pct(1):.2f}",
        f"- Score p10/p90: {pct(0.1):.2f} / {pct(0.9):.2f}",
        "",
        "## Columns To Optimize",
        "",
        "- `score_100` / `computed_advanced_score`: final target score.",
        "- `core_points`: 60-point Core F1 contribution.",
        "- `completeness_points`: 15-point recall/coverage contribution.",
        "- `fp_points`: 15-point assessed false-positive and call-count contribution.",
        "- `quality_points`: 10-point Ti/Tv and Het/Hom ratio contribution.",
        "- `overcall_penalty`, `fp_per_target`, `region_fp_total`: full-region overcall guardrail.",
        "- `runtime_seconds`: retained as metadata only; not an optimization metric.",
        "",
        "## Top Rows",
        "",
        "| score | region | label | core | complete | fp | quality | overcall |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in top:
        lines.append(
            f"| {number(row.get('score_100')):.2f} | {row.get('region')} | {row.get('label')} | "
            f"{number(row.get('core_points')):.2f} | "
            f"{number(row.get('completeness_points')):.2f} | {number(row.get('fp_points')):.2f} | "
            f"{number(row.get('quality_points')):.2f} | {number(row.get('overcall_penalty')):.2f} |"
        )
    if exact_near:
        lines += [
            "",
            "## Closest Row To Current Target Center",
            "",
            f"- Target center used here: `chr21:22527963-27527963` center `25027963`",
            f"- Closest historical row: `{exact_near.get('region')}`",
            f"- Score: `{number(exact_near.get('score_100')):.2f}`",
            f"- Component points: core `{number(exact_near.get('core_points')):.2f}`, "
            f"completeness `{number(exact_near.get('completeness_points')):.2f}`, "
            f"fp `{number(exact_near.get('fp_points')):.2f}`, "
            f"quality `{number(exact_near.get('quality_points')):.2f}`, "
            f"overcall `{number(exact_near.get('overcall_penalty')):.2f}`",
        ]
    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", default="/root/minos/rounds.json")
    parser.add_argument("--out-dir", default="/root/minos")
    args = parser.parse_args()

    rounds = json.loads(Path(args.rounds).read_text())
    rows = flatten_rows(rounds)
    out_dir = Path(args.out_dir)
    csv_path = out_dir / "chr21_gatk_advanced_history.csv"
    jsonl_path = out_dir / "chr21_gatk_advanced_history.jsonl"
    summary_path = out_dir / "chr21_gatk_advanced_history_summary.md"
    write_csv(csv_path, rows)
    write_jsonl(jsonl_path, rows)
    summarize(rows, summary_path, csv_path, jsonl_path)
    print(f"wrote {len(rows)} rows")
    print(csv_path)
    print(jsonl_path)
    print(summary_path)


if __name__ == "__main__":
    main()
