"""Worker GIAB scoring behavior vs validator expectations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.benchmark.giab.runner import score_tool_on_region
from app.benchmark.giab.scoring import score_giab


@pytest.fixture
def giab_paths(tmp_path: Path):
    truth_vcf = tmp_path / "truth.vcf.gz"
    truth_bed = tmp_path / "truth.bed"
    query_vcf = tmp_path / "query.vcf.gz"
    ref = tmp_path / "ref.fa"
    for path in (truth_vcf, truth_bed, query_vcf, ref):
        path.write_text("stub", encoding="utf-8")
    return truth_vcf, truth_bed, query_vcf, ref


def test_score_giab_returns_none_when_hap_fails(giab_paths):
    truth_vcf, truth_bed, query_vcf, ref = giab_paths
    with (
        patch("app.benchmark.giab.scoring.ensure_sdf", return_value=Path("/tmp/sdf")),
        patch("app.benchmark.giab.scoring.ensure_repo_imports"),
        patch("utils.scoring.HappyScorer") as happy_cls,
    ):
        happy_cls.return_value.score_vcf.return_value = None
        result = score_giab(
            truth_vcf,
            truth_bed,
            query_vcf,
            ref,
            "chr20:10000000-10001000",
            "chr20",
            use_metrics_cache=False,
        )
    assert result is None


def test_score_tool_on_region_surfaces_hap_failure(giab_paths, tmp_path: Path):
    truth_vcf, truth_bed, query_vcf, ref = giab_paths
    with (
        patch("app.benchmark.giab.runner.ensure_truth_assets", return_value=(truth_vcf, truth_bed)),
        patch("app.benchmark.giab.runner.reference_for_chrom", return_value=ref),
        patch("app.benchmark.giab.runner.ensure_bam_for_region", return_value=tmp_path / "bam.bam"),
        patch("app.benchmark.giab.runner.chrom_from_region", return_value="chr20"),
        patch("templates._common.count_variants", return_value=42),
        patch(
            "app.benchmark.giab.runner._run_gatk",
            return_value={"success": True, "variant_count": 42},
        ),
        patch("app.benchmark.giab.runner.score_giab", return_value=None),
        patch("app.benchmark.giab.runner.ensure_repo_imports"),
        patch("app.benchmark.giab.runner.giab_vcf_dir", return_value=query_vcf.parent),
    ):
        result = score_tool_on_region(
            "gatk",
            {"standard_min_confidence_threshold_for_calling": 30},
            "chr20:10000000-10001000",
            instance_id="test",
            reuse_vcf=False,
        )
    assert result.get("error") == "hap.py scoring failed"
    assert "score" not in result
