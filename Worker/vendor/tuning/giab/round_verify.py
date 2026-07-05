"""Per-round local GIAB proxy scores — one independent run per portfolio hotkey.

Each hotkey schedules and scores itself on round open (background subprocess).
Use --region to score any Minos-style window; results are per-instance JSON files
plus an optional merged portfolio summary.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tuning.giab.calibrate import _run_gatk, _score_giab
from tuning.giab.data import chrom_from_region, ensure_bam_for_region, ensure_truth_assets, reference_for_chrom
from tuning.giab.paths import GIAB_RESULTS_DIR, GIAB_VCF_DIR

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]


def _enabled() -> bool:
    return os.getenv("GIAB_ROUND_VERIFY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _round_slug(round_id: str) -> str:
    from utils.path_utils import safe_round_dir_name

    return safe_round_dir_name(round_id)


def _region_slug(region: str) -> str:
    return region.replace(":", "_")


def _portfolio_result_path(round_id: str, region: str = "") -> Path:
    base = f"round_{_round_slug(round_id)}"
    if region:
        base = f"{base}_{_region_slug(region)}"
    return GIAB_RESULTS_DIR / f"{base}.json"


def _instance_result_path(round_id: str, instance_id: str, region: str = "") -> Path:
    base = f"round_{_round_slug(round_id)}_{instance_id}"
    if region:
        base = f"{base}_{_region_slug(region)}"
    return GIAB_RESULTS_DIR / f"{base}.json"


def _schedule_marker(round_id: str, instance_id: str, region: str = "") -> Path:
    base = f".scheduled_{_round_slug(round_id)}_{instance_id}"
    if region:
        base = f"{base}_{_region_slug(region)}"
    return GIAB_RESULTS_DIR / base


def _instance_config_fingerprint(instance_id: str) -> str:
    from tuning.config_manager import _load_from_path
    from tuning.instance import tool_conf_path

    path = tool_conf_path(instance_id=instance_id)
    if not path.exists():
        return ""
    cfg = _load_from_path(path)
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]


def _portfolio_config_fingerprint(instance_ids: Sequence[str]) -> str:
    parts = [f"{iid}:{_instance_config_fingerprint(iid)}" for iid in instance_ids]
    return "|".join(sorted(p for p in parts if p))


def load_instance_config(instance_id: str) -> Dict[str, Any]:
    from tuning.config_manager import _load_from_path
    from tuning.instance import instance_tool, tool_conf_path

    path = tool_conf_path(instance_id=instance_id)
    return {
        "instance": instance_id,
        "tool": instance_tool(instance_id),
        "config_path": str(path),
        "config": _load_from_path(path) if path.exists() else {},
    }


def load_portfolio_configs() -> Dict[str, Dict[str, Any]]:
    from tuning.instance import discover_instances

    return {iid: load_instance_config(iid) for iid in discover_instances()}


def _run_bcftools(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    from templates.bcftools import variant_call

    default_threads = max(1, (os.cpu_count() or 4) - 1)
    cfg = {
        "bcftools_options": params,
        "threads": int(os.getenv("GIAB_BCF_THREADS", str(default_threads))),
        "timeout": int(os.getenv("GIAB_BCF_TIMEOUT", "1800")),
    }
    return variant_call(bam, ref, out_vcf, region, cfg)


def score_tool_on_region(
    tool: str,
    params: Dict[str, Any],
    region: str,
    *,
    instance_id: str = "",
    skip_bam_download: bool = False,
    vcf_tag: str = "",
    reuse_vcf: bool = False,
) -> Dict[str, Any]:
    """Call + hap.py score one tool config on a GIAB regional BAM."""
    from templates._common import count_variants

    chrom = chrom_from_region(region)
    ref = reference_for_chrom(chrom)
    truth_vcf, truth_bed = ensure_truth_assets()
    if skip_bam_download:
        from tuning.giab.data import bam_cache_ready_for_region, regional_bam_cache_path

        bam = regional_bam_cache_path(region)
        if not bam_cache_ready_for_region(region):
            bam = ensure_bam_for_region(region)
    else:
        bam = ensure_bam_for_region(region)

    slug = _round_slug(f"{instance_id}_{tool}_{_region_slug(region)}")
    if vcf_tag:
        slug = f"{slug}_{vcf_tag}"
    out_vcf = GIAB_VCF_DIR / f"round_verify_{slug}.vcf.gz"
    GIAB_VCF_DIR.mkdir(parents=True, exist_ok=True)

    if reuse_vcf and out_vcf.exists():
        call = {
            "success": True,
            "variant_count": count_variants(out_vcf),
            "metadata": {"reused_vcf": True},
        }
    elif tool == "gatk":
        call = _run_gatk(bam, ref, region, out_vcf, params, instance_id=instance_id)
    elif tool == "bcftools":
        call = _run_bcftools(bam, ref, region, out_vcf, params)
    else:
        return {"tool": tool, "error": f"unsupported tool {tool}"}

    if not call.get("success"):
        return {
            "instance": instance_id,
            "tool": tool,
            "region": region,
            "error": call.get("error"),
            "variant_count": call.get("variant_count"),
        }

    metrics = _score_giab(truth_vcf, truth_bed, out_vcf, ref, region, chrom)
    from utils.scoring import AdvancedScorer

    numeric = {
        k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))
    }
    score_breakdown = AdvancedScorer.compute_breakdown(numeric)
    return {
        "instance": instance_id,
        "tool": tool,
        "region": region,
        "score": round(float(metrics.get("advanced_score") or 0.0), 2),
        "f1_snp": metrics.get("f1_snp"),
        "f1_indel": metrics.get("f1_indel"),
        "fp_snp": metrics.get("fp_snp"),
        "fn_snp": metrics.get("fn_snp"),
        "fp_indel": metrics.get("fp_indel"),
        "fn_indel": metrics.get("fn_indel"),
        "variant_count": call.get("variant_count"),
        "hap_metrics": numeric,
        "score_breakdown": score_breakdown,
        "proxy": True,
        "note": "GIAB HG002 proxy — not challenge truth",
    }


def verify_instance_config(
    instance_id: str,
    round_id: str,
    region: str,
    *,
    skip_bam_download: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Score one hotkey on the given region (GIAB proxy BAM)."""
    GIAB_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    row = load_instance_config(instance_id)
    config_fp = _instance_config_fingerprint(instance_id)
    out_path = _instance_result_path(round_id, instance_id, region)

    if not force and out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            if (
                prev.get("config_fingerprint") == config_fp
                and prev.get("status") == "done"
                and prev.get("region") == region
            ):
                return prev
        except (json.JSONDecodeError, OSError):
            pass

    payload: Dict[str, Any] = {
        "round_id": round_id,
        "region": region,
        "instance": instance_id,
        "tool": row["tool"],
        "config_fingerprint": config_fp,
        "config_path": row["config_path"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "proxy": True,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    logger.info("GIAB verify: %s (%s) @ %s", instance_id, row["tool"], region)
    try:
        result = score_tool_on_region(
            row["tool"],
            row["config"],
            region,
            instance_id=instance_id,
            skip_bam_download=skip_bam_download,
        )
    except Exception as exc:
        result = {"instance": instance_id, "tool": row["tool"], "error": str(exc)}

    payload.update(result)
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    payload["status"] = "done" if result.get("score") is not None else "failed"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    _write_instance_state(instance_id, round_id, region, config_fp, out_path, payload)
    _merge_portfolio_summary(round_id, region)
    return payload


def _write_instance_state(
    instance_id: str,
    round_id: str,
    region: str,
    config_fp: str,
    out_path: Path,
    payload: Dict[str, Any],
) -> None:
    state_path = GIAB_RESULTS_DIR / f"verify_state_{instance_id}.json"
    state_path.write_text(
        json.dumps(
            {
                "instance": instance_id,
                "round_id": round_id,
                "region": region,
                "config_fingerprint": config_fp,
                "status": payload.get("status"),
                "score": payload.get("score"),
                "result_path": str(out_path),
                "updated_at": payload.get("finished_at"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _merge_portfolio_summary(round_id: str, region: str) -> Dict[str, Any]:
    """Build merged portfolio view from per-instance result files."""
    from tuning.instance import discover_instances

    hotkeys: List[Dict[str, Any]] = []
    for iid in discover_instances():
        path = _instance_result_path(round_id, iid, region)
        if not path.exists():
            continue
        try:
            hotkeys.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue

    scores = [float(r["score"]) for r in hotkeys if r.get("score") is not None]
    summary: Dict[str, Any] = {
        "round_id": round_id,
        "region": region,
        "config_fingerprint": _portfolio_config_fingerprint([h.get("instance", "") for h in hotkeys]),
        "status": "done" if hotkeys and all(h.get("status") == "done" for h in hotkeys) else "partial",
        "proxy": True,
        "hotkeys": hotkeys,
        "avg_score": round(sum(scores) / max(len(scores), 1), 2) if scores else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _portfolio_result_path(round_id, region).write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def verify_round_configs(
    round_id: str,
    region: str,
    *,
    instance_ids: Optional[Sequence[str]] = None,
    skip_bam_download: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Score selected (or all) portfolio hotkeys on the region."""
    from tuning.instance import discover_instances

    targets = list(instance_ids) if instance_ids else list(discover_instances())
    for iid in targets:
        verify_instance_config(
            iid,
            round_id,
            region,
            skip_bam_download=skip_bam_download,
            force=force,
        )
    return _merge_portfolio_summary(round_id, region)


def latest_instance_verify(instance_id: str) -> Optional[Dict[str, Any]]:
    state_path = GIAB_RESULTS_DIR / f"verify_state_{instance_id}.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            path = state.get("result_path")
            if path and Path(path).exists():
                return json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if not GIAB_RESULTS_DIR.exists():
        return None
    pattern = f"round_*_{instance_id}*.json"
    candidates = sorted(
        GIAB_RESULTS_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") in ("done", "failed"):
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


def latest_round_verify(
    *,
    region: Optional[str] = None,
    round_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Latest merged or per-instance GIAB verify payloads."""
    from tuning.instance import discover_instances

    if round_id and region:
        path = _portfolio_result_path(round_id, region)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    hotkeys = []
    for iid in discover_instances():
        row = latest_instance_verify(iid)
        if row is None:
            continue
        if region and row.get("region") != region:
            continue
        if round_id and row.get("round_id") != round_id:
            continue
        hotkeys.append(row)

    if not hotkeys:
        return None

    scores = [float(r["score"]) for r in hotkeys if r.get("score") is not None]
    rid = round_id or hotkeys[0].get("round_id")
    reg = region or hotkeys[0].get("region")
    return {
        "round_id": rid,
        "region": reg,
        "status": "done" if all(h.get("status") == "done" for h in hotkeys) else "partial",
        "proxy": True,
        "hotkeys": hotkeys,
        "avg_score": round(sum(scores) / max(len(scores), 1), 2) if scores else None,
        "updated_at": max(h.get("finished_at") or "" for h in hotkeys),
    }


def schedule_round_verify(
    round_id: str,
    region: str,
    *,
    instance_id: Optional[str] = None,
) -> bool:
    """Background GIAB verify for one hotkey (or all when instance_id omitted)."""
    if not _enabled() or not round_id or not region:
        return False

    from tuning.instance import current_instance_id, discover_instances

    targets = [instance_id] if instance_id else list(discover_instances())
    launched = False

    GIAB_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for iid in targets:
        if iid is None:
            continue
        config_fp = _instance_config_fingerprint(iid)
        out_path = _instance_result_path(round_id, iid, region)
        if out_path.exists():
            try:
                prev = json.loads(out_path.read_text(encoding="utf-8"))
                if (
                    prev.get("config_fingerprint") == config_fp
                    and prev.get("status") == "done"
                    and prev.get("region") == region
                ):
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        marker = _schedule_marker(round_id, iid, region)
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "round_id": round_id,
                            "region": region,
                            "instance": iid,
                            "config_fingerprint": config_fp,
                            "scheduled_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
        except FileExistsError:
            continue

        log_path = GIAB_RESULTS_DIR / f"verify_{iid}.log"
        log_f = open(log_path, "a", encoding="utf-8")
        cmd = [
            sys.executable,
            "-m",
            "tuning.giab.round_verify",
            "--round-id",
            round_id,
            "--region",
            region,
            "--instance",
            iid,
        ]
        subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        logger.info("Scheduled GIAB verify for %s @ %s %s", iid, round_id[:19], region)
        launched = True

    return launched


def resolve_round_context(
    round_id: str = "",
    region: str = "",
    *,
    instance_id: Optional[str] = None,
) -> tuple[str, str]:
    """Fill round_id/region from coordinator or per-instance coordinator row."""
    rid = round_id
    reg = region
    try:
        from tuning.instance import bind_instance, reset_instance
        from tuning.portfolio_coordinator import active_coordinator_round_id, load_coordinator

        coord = load_coordinator()
        rid = rid or active_coordinator_round_id() or str(coord.get("round_id") or "")
        if not reg:
            if instance_id:
                token = bind_instance(instance_id)
                try:
                    inst = (coord.get("instances") or {}).get(instance_id) or {}
                    reg = str(inst.get("region") or "")
                finally:
                    reset_instance(token)
            if not reg:
                for inst in (coord.get("instances") or {}).values():
                    if inst.get("region"):
                        reg = str(inst["region"])
                        break
    except ImportError:
        pass
    return rid, reg


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="GIAB proxy score for portfolio hotkey config(s) on a region",
    )
    parser.add_argument("--round-id", default="", help="Round id (default: coordinator)")
    parser.add_argument(
        "--region",
        default="",
        help="Genomic region e.g. chr21:32534965-37534965 (default: coordinator)",
    )
    parser.add_argument(
        "--instance",
        default="",
        help="Hotkey id: gatk, bcftools, or omit/all for every active hotkey",
    )
    parser.add_argument("--skip-bam-download", action="store_true", help="Use cached BAM only")
    parser.add_argument("--force", action="store_true", help="Re-run even if result exists")
    parser.add_argument("--latest", action="store_true", help="Print latest result JSON")
    args = parser.parse_args(argv)

    instance_filter = (args.instance or "").strip().lower()
    if instance_filter in ("all", "*"):
        instance_filter = ""

    if args.latest:
        data = latest_round_verify(region=args.region or None, round_id=args.round_id or None)
        if instance_filter and data:
            data = dict(data)
            data["hotkeys"] = [
                h for h in data.get("hotkeys") or [] if h.get("instance") == instance_filter
            ]
            if len(data["hotkeys"]) == 1:
                print(json.dumps(data["hotkeys"][0], indent=2))
                return 0
        if not data:
            print("{}", file=sys.stderr)
            return 1
        print(json.dumps(data, indent=2))
        return 0

    round_id, region = resolve_round_context(
        args.round_id, args.region, instance_id=instance_filter or None
    )
    if not round_id or not region:
        print("--round-id and --region required (or set coordinator state)", file=sys.stderr)
        return 1

    if instance_filter:
        result = verify_instance_config(
            instance_filter,
            round_id,
            region,
            skip_bam_download=args.skip_bam_download,
            force=args.force,
        )
        print(json.dumps(result, indent=2))
        if result.get("score") is not None:
            print(
                f"\n{instance_filter}: {result['score']:.1f} "
                f"(SNP F1={result.get('f1_snp')}, FP={result.get('fp_snp')}) @ {region}"
            )
        else:
            print(f"\n{instance_filter}: FAILED — {result.get('error')}")
        return 0 if result.get("score") is not None else 1

    result = verify_round_configs(
        round_id,
        region,
        skip_bam_download=args.skip_bam_download,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    for row in result.get("hotkeys") or []:
        label = row.get("instance") or row.get("tool")
        if row.get("score") is not None:
            print(
                f"  {label}: {row['score']:.1f} "
                f"(SNP F1={row.get('f1_snp')}, FP={row.get('fp_snp')})"
            )
        else:
            print(f"  {label}: FAILED — {row.get('error')}")
    if result.get("avg_score") is not None:
        print(f"\nGIAB proxy avg @ {region}: {result['avg_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
