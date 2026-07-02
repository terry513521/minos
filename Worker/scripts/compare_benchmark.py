#!/usr/bin/env python3
"""Run two GIAB benchmarks on the same region and print a side-by-side comparison."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from app.benchmark import run_benchmark, validate_benchmark_assets
from app.benchmark.conf import tool_params_from_conf
from app.benchmark.giab.runner import score_tool_on_region
from app.config import Settings, get_settings
from app.core.conf_hash import conf_fingerprint
from app.core.window import resolve_benchmark_window
from app.domain.result import BenchmarkResult

logger = logging.getLogger(__name__)

METRIC_KEYS = (
    "score",
    "f1_snp",
    "f1_indel",
    "fp_snp",
    "fn_snp",
    "fp_indel",
    "fn_indel",
    "variant_count",
)


def _parse_simple_conf(path: Path) -> dict[str, Any]:
    """Parse minos-style key=value .conf into gatk_options."""
    options: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.lower() in ("true", "false"):
            options[key] = value.lower() == "true"
        else:
            try:
                if "." in value:
                    options[key] = float(value)
                else:
                    options[key] = int(value)
            except ValueError:
                options[key] = value
    return {"gatk_options": options}


def load_config(path: Path) -> tuple[str, dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        label = str(payload.pop("label", path.stem))
        if "gatk_options" in payload or "bcftools_options" in payload:
            return label, payload
        return label, {"gatk_options": payload}
    return path.stem, _parse_simple_conf(path)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
    return str(value)


def _delta(a: Any, b: Any) -> str:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        diff = float(b) - float(a)
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.4f}" if abs(diff) < 10 else f"{sign}{diff:.2f}"
    return "—"


def _run_one(
    *,
    label: str,
    conf: dict[str, Any],
    window: str,
    tool: str,
    settings: Settings,
    work_root: Path,
    rich: bool,
) -> dict[str, Any]:
    started = time.time()
    work_dir = work_root / label.replace(" ", "_")
    work_dir.mkdir(parents=True, exist_ok=True)

    result: BenchmarkResult = run_benchmark(
        window=window,
        tool=tool,
        conf=conf,
        work_dir=work_dir,
        settings=settings,
    )

    row: dict[str, Any] = {
        "label": label,
        "success": result.success,
        "score_normalized": result.score,
        "score": result.raw_score,
        "variant_count": result.variant_count,
        "cached": result.cached,
        "error": result.error,
        "elapsed_s": round(time.time() - started, 1),
        "conf": conf,
    }

    if rich and result.success:
        params = tool_params_from_conf(conf, tool)
        tag = conf_fingerprint(window=window, tool=tool, conf=conf)
        raw = score_tool_on_region(
            tool,
            params,
            window,
            instance_id=f"compare_{label}",
            vcf_tag=tag,
            reuse_vcf=True,
            settings=settings,
        )
        for key in METRIC_KEYS:
            if key in raw:
                row[key] = raw[key]

    return row


def _print_table(a: dict[str, Any], b: dict[str, Any]) -> None:
    width = 14
    print()
    print(f"{'Metric':<22} {'A: ' + a['label']:<{width}} {'B: ' + b['label']:<{width}} {'Delta':<{width}}")
    print("-" * (22 + width * 3))

    rows: list[tuple[str, str, str, str]] = [
        ("Success", str(a["success"]), str(b["success"]), "—"),
        ("Score (0–100)", _fmt(a.get("score")), _fmt(b.get("score")), _delta(a.get("score"), b.get("score"))),
        (
            "Score (0–1)",
            _fmt(a.get("score_normalized")),
            _fmt(b.get("score_normalized")),
            _delta(a.get("score_normalized"), b.get("score_normalized")),
        ),
        ("Variant count", _fmt(a.get("variant_count")), _fmt(b.get("variant_count")), _delta(a.get("variant_count"), b.get("variant_count"))),
        ("Cached VCF", str(a.get("cached")), str(b.get("cached")), "—"),
        ("Elapsed (s)", _fmt(a.get("elapsed_s")), _fmt(b.get("elapsed_s")), _delta(a.get("elapsed_s"), b.get("elapsed_s"))),
    ]

    for key in ("f1_snp", "f1_indel", "fp_snp", "fn_snp", "fp_indel", "fn_indel"):
        if key in a or key in b:
            rows.append((key, _fmt(a.get(key)), _fmt(b.get(key)), _delta(a.get(key), b.get(key))))

    for name, left, right, delta in rows:
        print(f"{name:<22} {left:<{width}} {right:<{width}} {delta:<{width}}")

    if a.get("error"):
        print(f"\nA error: {a['error']}")
    if b.get("error"):
        print(f"B error: {b['error']}")

    winner = "—"
    if a.get("success") and b.get("success"):
        sa, sb = float(a.get("score") or 0), float(b.get("score") or 0)
        if sa > sb:
            winner = a["label"]
        elif sb > sa:
            winner = b["label"]
        else:
            winner = "tie"
    print(f"\nHigher score wins: {winner}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two benchmark configs on the same GIAB region (Worker local backend).",
    )
    parser.add_argument(
        "--window",
        default="chr21:35444092-40444092",
        help="Genomic window (default: chr21 Minos-like 5 Mb)",
    )
    parser.add_argument("--tool", default="gatk", choices=("gatk", "bcftools"))
    parser.add_argument("--config-a", type=Path, required=True, help="First config (.json or .conf)")
    parser.add_argument("--config-b", type=Path, required=True, help="Second config (.json or .conf)")
    parser.add_argument("--label-a", default="", help="Display name for config A")
    parser.add_argument("--label-b", default="", help="Display name for config B")
    parser.add_argument(
        "--subwindow-mb",
        type=int,
        default=0,
        help="Center-crop window to N Mb for faster smoke tests (0 = use full --window)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write full JSON results to this path",
    )
    parser.add_argument(
        "--rich",
        action="store_true",
        help="Re-query hap.py metrics after benchmark (uses VCF cache; extra hap.py pass)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    settings = get_settings()
    if args.subwindow_mb > 0:
        settings = settings.model_copy(update={"benchmark_subwindow_mb": args.subwindow_mb})

    label_a, conf_a = load_config(args.config_a)
    label_b, conf_b = load_config(args.config_b)
    label_a = args.label_a or label_a
    label_b = args.label_b or label_b

    benchmark_window, source_window = resolve_benchmark_window(
        args.window.strip(),
        settings.benchmark_subwindow_mb,
        seed=args.window.strip(),
    )

    print("Worker GIAB benchmark compare")
    print(f"  Window:  {benchmark_window}")
    if source_window:
        print(f"  Source:  {source_window} (random slice via subwindow)")
    print(f"  Tool:    {args.tool}")
    print(f"  A:       {label_a}  ({args.config_a})")
    print(f"  B:       {label_b}  ({args.config_b})")

    validate_benchmark_assets(benchmark_window, settings)

    work_root = ROOT / "runs" / "compare" / time.strftime("%Y%m%d_%H%M%S")
    work_root.mkdir(parents=True, exist_ok=True)

    print("\nRunning A …")
    row_a = _run_one(
        label=label_a,
        conf=conf_a,
        window=benchmark_window,
        tool=args.tool,
        settings=settings,
        work_root=work_root,
        rich=args.rich,
    )
    print("Running B …")
    row_b = _run_one(
        label=label_b,
        conf=conf_b,
        window=benchmark_window,
        tool=args.tool,
        settings=settings,
        work_root=work_root,
        rich=args.rich,
    )

    _print_table(row_a, row_b)

    payload = {
        "window": benchmark_window,
        "source_window": source_window,
        "tool": args.tool,
        "a": row_a,
        "b": row_b,
    }
    out_path = args.output or (work_root / "comparison.json")
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {out_path}")

    if not row_a.get("success") or not row_b.get("success"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
