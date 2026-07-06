#!/usr/bin/env python3
"""Dependency-free chr21 GATK config optimizer for Minos round history.

Model shape:
  1. Predict score from region + config with two small regressors:
     - ridge linear regression
     - distance-weighted k-nearest-neighbor regression
  2. Generate candidate configs from historical chr21 configs and local
     perturbations around high-scoring nearby configs.
  3. Rank candidates for a target chr21 region and optionally write a .conf.

This is intentionally small and auditable. It does not need numpy/sklearn.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import re
import statistics
from pathlib import Path
from typing import Any


REGION_RE = re.compile(r"^(chr[^:]+):(\d+)-(\d+)$")

NUMERIC_PARAMS = [
    "standard_min_confidence_threshold_for_calling",
    "min_base_quality_score",
    "min_mapping_quality_score",
    "min_dangling_branch_length",
    "min_pruning",
    "max_alternate_alleles",
    "pruning_lod_threshold",
    "max_reads_per_alignment_start",
    "pair_hmm_gap_continuation_penalty",
    "phred_scaled_global_read_mismapping_rate",
    "active_probability_threshold",
    "assembly_region_padding",
    "max_num_haplotypes_in_population",
    "heterozygosity",
    "indel_heterozygosity",
    "sample_ploidy",
    "base_quality_score_threshold",
    "contamination_fraction_to_filter",
    "min_assembly_region_size",
    "max_assembly_region_size",
    "adaptive_pruning_initial_error_rate",
]

BOOL_PARAMS = [
    "recover_all_dangling_branches",
    "dont_use_soft_clipped_bases",
]

CONST_PARAMS = {
    "pcr_indel_model": "NONE",
    "emit_ref_confidence": "NONE",
}


def parse_region(region: str) -> tuple[str, int, int, float]:
    match = REGION_RE.match(region)
    if not match:
        raise ValueError(f"invalid region {region!r}; expected chr21:start-end")
    chrom, start_s, end_s = match.groups()
    start = int(start_s)
    end = int(end_s)
    if chrom != "chr21":
        raise ValueError("this optimizer is intentionally chr21-only")
    if start >= end:
        raise ValueError("region start must be < end")
    return chrom, start, end, (start + end) / 2.0


def load_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    rows: list[dict[str, Any]] = []
    for round_entry in data:
        region = round_entry.get("region") or ""
        try:
            chrom, start, end, center = parse_region(region)
        except ValueError:
            continue
        for instance_id, inst in (round_entry.get("instances") or {}).items():
            if inst.get("tool") != "gatk" or inst.get("score_100") is None:
                continue
            cfg = dict(inst.get("config_snapshot") or {})
            row = {
                "round_id": round_entry.get("round_id"),
                "region": region,
                "start": start,
                "end": end,
                "center": center,
                "cluster": int(center // 2_500_000),
                "instance_id": instance_id,
                "score": float(inst["score_100"]),
                "variant_count": inst.get("variant_count"),
                "runtime_seconds": inst.get("runtime_seconds"),
                "cfg": cfg,
            }
            rows.append(row)
    return rows


def median(values: list[float]) -> float:
    return statistics.median(values)


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty values")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def config_key(cfg: dict[str, Any]) -> str:
    payload = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def normalize_bool(value: Any) -> float:
    return 1.0 if bool(value) else 0.0


def build_feature_dict(region_center: float, cfg: dict[str, Any]) -> dict[str, float]:
    # Region features. chr21 has variable difficulty across position.
    center_mb = region_center / 1_000_000.0
    features: dict[str, float] = {
        "center_mb": center_mb,
        "center_mb_sq": center_mb * center_mb,
    }
    for name in NUMERIC_PARAMS:
        value = cfg.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            features[name] = float(value)
    for name in BOOL_PARAMS:
        features[name] = normalize_bool(cfg.get(name, False))
    # A few useful nonlinear transforms for scale-sensitive params.
    for name in ("heterozygosity", "indel_heterozygosity", "active_probability_threshold", "adaptive_pruning_initial_error_rate"):
        value = cfg.get(name)
        if isinstance(value, (int, float)) and value > 0:
            features[f"log_{name}"] = math.log10(float(value))
    return features


class Standardizer:
    def __init__(self, feature_names: list[str], rows: list[dict[str, float]]):
        self.feature_names = feature_names
        self.mean: dict[str, float] = {}
        self.std: dict[str, float] = {}
        for name in feature_names:
            values = [r.get(name, 0.0) for r in rows]
            mu = sum(values) / len(values)
            var = sum((v - mu) ** 2 for v in values) / max(1, len(values) - 1)
            sd = math.sqrt(var) or 1.0
            self.mean[name] = mu
            self.std[name] = sd

    def vector(self, features: dict[str, float]) -> list[float]:
        return [(features.get(name, 0.0) - self.mean[name]) / self.std[name] for name in self.feature_names]


def solve_linear_system(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        denom = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= denom
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor == 0:
                continue
            for j in range(col, n + 1):
                aug[r][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


class RidgeRegressor:
    def __init__(self, alpha: float = 5.0):
        self.alpha = alpha
        self.weights: list[float] = []
        self.y_mean = 0.0

    def fit(self, x_rows: list[list[float]], y: list[float]) -> None:
        self.y_mean = sum(y) / len(y)
        p = len(x_rows[0]) + 1  # intercept
        xtx = [[0.0 for _ in range(p)] for _ in range(p)]
        xty = [0.0 for _ in range(p)]
        for x, target in zip(x_rows, y):
            row = [1.0] + x
            for i in range(p):
                xty[i] += row[i] * target
                for j in range(p):
                    xtx[i][j] += row[i] * row[j]
        for i in range(1, p):
            xtx[i][i] += self.alpha
        self.weights = solve_linear_system(xtx, xty)

    def predict_one(self, x: list[float]) -> float:
        if not self.weights:
            return self.y_mean
        return self.weights[0] + sum(w * v for w, v in zip(self.weights[1:], x))


class KnnRegressor:
    def __init__(self, k: int = 25):
        self.k = k
        self.x_rows: list[list[float]] = []
        self.y: list[float] = []

    def fit(self, x_rows: list[list[float]], y: list[float]) -> None:
        self.x_rows = x_rows
        self.y = y

    def predict_one(self, x: list[float]) -> float:
        distances = []
        for train_x, target in zip(self.x_rows, self.y):
            d2 = sum((a - b) ** 2 for a, b in zip(x, train_x))
            distances.append((math.sqrt(d2), target))
        nearest = sorted(distances, key=lambda item: item[0])[: self.k]
        weights = [1.0 / (d + 0.25) for d, _ in nearest]
        return sum(w * target for w, (_, target) in zip(weights, nearest)) / sum(weights)


def train_models(rows: list[dict[str, Any]]):
    feature_dicts = [build_feature_dict(r["center"], r["cfg"]) for r in rows]
    feature_names = sorted({name for fd in feature_dicts for name in fd})
    std = Standardizer(feature_names, feature_dicts)
    x_rows = [std.vector(fd) for fd in feature_dicts]
    y = [float(r["score"]) for r in rows]
    ridge = RidgeRegressor(alpha=10.0)
    ridge.fit(x_rows, y)
    knn = KnnRegressor(k=min(25, max(5, len(rows) // 8)))
    knn.fit(x_rows, y)
    return feature_names, std, ridge, knn


def predict_score(center: float, cfg: dict[str, Any], std: Standardizer, ridge: RidgeRegressor, knn: KnnRegressor) -> tuple[float, float, float]:
    x = std.vector(build_feature_dict(center, cfg))
    ridge_pred = ridge.predict_one(x)
    knn_pred = knn.predict_one(x)
    # Favor KNN for local nonlinear behavior, but keep ridge to stabilize.
    ensemble = 0.65 * knn_pred + 0.35 * ridge_pred
    return ensemble, ridge_pred, knn_pred


def historical_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        cfg = dict(row["cfg"])
        for k, v in CONST_PARAMS.items():
            cfg[k] = v
        by_key.setdefault(config_key(cfg), cfg)
    return list(by_key.values())


def top_values(rows: list[dict[str, Any]], q: float = 0.80) -> dict[str, list[Any]]:
    scores = [r["score"] for r in rows]
    cut = quantile(scores, q)
    top = [r for r in rows if r["score"] >= cut]
    values: dict[str, list[Any]] = {}
    for name in NUMERIC_PARAMS:
        vals = sorted({r["cfg"].get(name) for r in top if isinstance(r["cfg"].get(name), (int, float))})
        if vals:
            # Keep a small set: low/median/high from strong configs.
            values[name] = sorted({vals[0], median(vals), vals[-1]})
    for name in BOOL_PARAMS:
        vals = sorted({bool(r["cfg"].get(name, False)) for r in top})
        if vals:
            values[name] = vals
    return values


def generate_local_candidates(rows: list[dict[str, Any]], center: float, rng: random.Random) -> list[dict[str, Any]]:
    # Seeds: top nearby configs + best repeated/high global chr21 configs.
    def dist(row):
        return abs(row["center"] - center)

    nearby = sorted(rows, key=lambda r: (dist(r), -r["score"]))[:80]
    strong = sorted(rows, key=lambda r: r["score"], reverse=True)[:60]
    seed_rows = sorted({id(r): r for r in nearby + strong}.values(), key=lambda r: -r["score"])[:80]
    topv = top_values(rows, 0.80)

    candidates: dict[str, dict[str, Any]] = {}
    for row in seed_rows:
        base = dict(row["cfg"])
        for k, v in CONST_PARAMS.items():
            base[k] = v
        candidates[config_key(base)] = base

        # Single-parameter swaps toward top chr21 values.
        for name in (
            "min_mapping_quality_score",
            "base_quality_score_threshold",
            "min_base_quality_score",
            "standard_min_confidence_threshold_for_calling",
            "contamination_fraction_to_filter",
            "heterozygosity",
            "indel_heterozygosity",
            "max_alternate_alleles",
            "pruning_lod_threshold",
            "pair_hmm_gap_continuation_penalty",
            "max_reads_per_alignment_start",
            "assembly_region_padding",
            "max_num_haplotypes_in_population",
            "max_assembly_region_size",
        ):
            for value in topv.get(name, []):
                cfg = dict(base)
                cfg[name] = value
                candidates[config_key(cfg)] = cfg

        # Random small mixes from strong values.
        names = [
            "min_mapping_quality_score",
            "base_quality_score_threshold",
            "standard_min_confidence_threshold_for_calling",
            "contamination_fraction_to_filter",
            "heterozygosity",
            "indel_heterozygosity",
            "max_alternate_alleles",
            "pruning_lod_threshold",
            "pair_hmm_gap_continuation_penalty",
        ]
        for _ in range(20):
            cfg = dict(base)
            for name in rng.sample(names, k=rng.randint(2, 5)):
                vals = topv.get(name) or []
                if vals:
                    cfg[name] = rng.choice(vals)
            # Keep runtime-heavy params conservative for chr21 unless a seed had them low.
            cfg["max_reads_per_alignment_start"] = min(int(cfg.get("max_reads_per_alignment_start", 28)), 28)
            cfg["assembly_region_padding"] = min(int(cfg.get("assembly_region_padding", 80)), 80)
            cfg["max_num_haplotypes_in_population"] = min(int(cfg.get("max_num_haplotypes_in_population", 224)), 224)
            cfg["max_assembly_region_size"] = min(int(cfg.get("max_assembly_region_size", 300)), 300)
            cfg["recover_all_dangling_branches"] = False
            cfg["dont_use_soft_clipped_bases"] = False
            for k, v in CONST_PARAMS.items():
                cfg[k] = v
            candidates[config_key(cfg)] = cfg

    return list(candidates.values())


def write_conf(path: Path, cfg: dict[str, Any], header: str) -> None:
    order = [
        "min_base_quality_score",
        "min_mapping_quality_score",
        "base_quality_score_threshold",
        "standard_min_confidence_threshold_for_calling",
        "emit_ref_confidence",
        "pcr_indel_model",
        "min_pruning",
        "max_alternate_alleles",
        "min_dangling_branch_length",
        "recover_all_dangling_branches",
        "max_num_haplotypes_in_population",
        "adaptive_pruning_initial_error_rate",
        "pruning_lod_threshold",
        "active_probability_threshold",
        "min_assembly_region_size",
        "max_assembly_region_size",
        "assembly_region_padding",
        "pair_hmm_gap_continuation_penalty",
        "phred_scaled_global_read_mismapping_rate",
        "heterozygosity",
        "indel_heterozygosity",
        "sample_ploidy",
        "contamination_fraction_to_filter",
        "max_reads_per_alignment_start",
        "dont_use_soft_clipped_bases",
    ]
    lines = [f"# {line}" if line else "#" for line in header.splitlines()]
    for name in order:
        value = cfg.get(name)
        if isinstance(value, bool):
            value_s = "true" if value else "false"
        else:
            value_s = str(value)
        lines.append(f"{name}={value_s}")
    path.write_text("\n".join(lines) + "\n")


def evaluate_cv(rows: list[dict[str, Any]]) -> dict[str, float]:
    # Leave one 2.5Mb neighborhood out. This is stricter than random split.
    clusters = sorted({r["cluster"] for r in rows})
    errors = []
    for cluster in clusters:
        train = [r for r in rows if r["cluster"] != cluster]
        test = [r for r in rows if r["cluster"] == cluster]
        if len(train) < 50 or not test:
            continue
        _, std, ridge, knn = train_models(train)
        for row in test:
            pred, _, _ = predict_score(row["center"], row["cfg"], std, ridge, knn)
            errors.append(pred - row["score"])
    if not errors:
        return {"mae": float("nan"), "rmse": float("nan")}
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    return {"mae": mae, "rmse": rmse}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default="/root/minos/rounds.json")
    parser.add_argument("--region", required=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", default="")
    parser.add_argument("--seed", type=int, default=107)
    args = parser.parse_args()

    _, _, _, center = parse_region(args.region)
    rows = load_rows(Path(args.history))
    if len(rows) < 50:
        raise SystemExit("not enough chr21 GATK history rows")

    cv = evaluate_cv(rows)
    _, std, ridge, knn = train_models(rows)
    rng = random.Random(args.seed)
    candidates = historical_candidates(rows) + generate_local_candidates(rows, center, rng)
    unique: dict[str, dict[str, Any]] = {}
    for cfg in candidates:
        for k, v in CONST_PARAMS.items():
            cfg[k] = v
        unique[config_key(cfg)] = cfg

    ranked = []
    for cfg in unique.values():
        pred, ridge_pred, knn_pred = predict_score(center, cfg, std, ridge, knn)
        ranked.append((pred, ridge_pred, knn_pred, cfg))
    ranked.sort(key=lambda item: item[0], reverse=True)

    print(f"history_rows={len(rows)} candidate_configs={len(ranked)}")
    print(f"leave-neighborhood-out MAE={cv['mae']:.2f} RMSE={cv['rmse']:.2f}")
    print(f"target_region={args.region} center_mb={center/1_000_000:.3f}")
    print()
    for i, (pred, ridge_pred, knn_pred, cfg) in enumerate(ranked[: args.top], 1):
        print(f"#{i} pred={pred:.2f} ridge={ridge_pred:.2f} knn={knn_pred:.2f} key={config_key(cfg)}")
        compact = {
            "standard_min_confidence_threshold_for_calling": cfg.get("standard_min_confidence_threshold_for_calling"),
            "min_base_quality_score": cfg.get("min_base_quality_score"),
            "min_mapping_quality_score": cfg.get("min_mapping_quality_score"),
            "base_quality_score_threshold": cfg.get("base_quality_score_threshold"),
            "contamination_fraction_to_filter": cfg.get("contamination_fraction_to_filter"),
            "heterozygosity": cfg.get("heterozygosity"),
            "indel_heterozygosity": cfg.get("indel_heterozygosity"),
            "max_alternate_alleles": cfg.get("max_alternate_alleles"),
            "min_pruning": cfg.get("min_pruning"),
            "pruning_lod_threshold": cfg.get("pruning_lod_threshold"),
            "max_reads_per_alignment_start": cfg.get("max_reads_per_alignment_start"),
            "pair_hmm_gap_continuation_penalty": cfg.get("pair_hmm_gap_continuation_penalty"),
            "assembly_region_padding": cfg.get("assembly_region_padding"),
            "max_num_haplotypes_in_population": cfg.get("max_num_haplotypes_in_population"),
            "max_assembly_region_size": cfg.get("max_assembly_region_size"),
            "recover_all_dangling_branches": cfg.get("recover_all_dangling_branches"),
        }
        print(json.dumps(compact, sort_keys=True))
        print()

    if args.out:
        best = ranked[0][3]
        header = (
            "Model-generated GATK config\n"
            f"target_region: {args.region}\n"
            f"predicted_score: {ranked[0][0]:.2f}\n"
            f"history_rows: {len(rows)}\n"
            f"cv_mae: {cv['mae']:.2f}\n"
            "model: 65% distance-weighted kNN + 35% ridge regression"
        )
        write_conf(Path(args.out), best, header)
        print(f"wrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
