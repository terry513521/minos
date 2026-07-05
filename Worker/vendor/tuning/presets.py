"""Preset GATK configurations for Minos mining."""

from __future__ import annotations

from typing import Dict

# Competitive baseline — applied on first setup and available as UI preset.
MINOS_BASELINE: Dict[str, object] = {
    "min_base_quality_score": 10,
    "min_mapping_quality_score": 20,
    "base_quality_score_threshold": 18,
    "standard_min_confidence_threshold_for_calling": 30.0,
    "emit_ref_confidence": "NONE",
    "pcr_indel_model": "NONE",
    "min_pruning": 2,
    "max_alternate_alleles": 6,
    "min_dangling_branch_length": 4,
    "recover_all_dangling_branches": False,
    "max_num_haplotypes_in_population": 128,
    "adaptive_pruning_initial_error_rate": 0.001,
    "pruning_lod_threshold": 2.302585,
    "active_probability_threshold": 0.002,
    "min_assembly_region_size": 50,
    "max_assembly_region_size": 300,
    "assembly_region_padding": 100,
    "pair_hmm_gap_continuation_penalty": 10,
    "phred_scaled_global_read_mismapping_rate": 45,
    "heterozygosity": 0.001,
    "indel_heterozygosity": 0.000125,
    "sample_ploidy": 2,
    "contamination_fraction_to_filter": 0.0,
    "max_reads_per_alignment_start": 50,
    "dont_use_soft_clipped_bases": False,
}

MINOS_INDEL_FOCUSED: Dict[str, object] = {
    **MINOS_BASELINE,
    "standard_min_confidence_threshold_for_calling": 28.0,
    "recover_all_dangling_branches": True,
    "min_dangling_branch_length": 2,
    "min_mapping_quality_score": 18,
}

MINOS_PRECISION_FOCUSED: Dict[str, object] = {
    **MINOS_BASELINE,
    "standard_min_confidence_threshold_for_calling": 33.0,
    "min_mapping_quality_score": 25,
    "min_base_quality_score": 12,
}

# Phase-1 competitive recall baseline (truth-set SNP tuning toward ~92 leaders).
COMPETITIVE_RECALL_BASELINE: Dict[str, object] = {
    "standard_min_confidence_threshold_for_calling": 31.0,
    "min_mapping_quality_score": 22,
    "min_pruning": 2,
    "recover_all_dangling_branches": True,
    "min_dangling_branch_length": 2,
    "active_probability_threshold": 0.0004,
    "assembly_region_padding": 120,
    "max_num_haplotypes_in_population": 256,
    "adaptive_pruning_initial_error_rate": 0.0015,
    "pair_hmm_gap_continuation_penalty": 8,
}

TRUTH_SNP_TARGET_F1 = 0.98
TRUTH_SNP_TARGET_MAX_ERRORS = 2

PRESETS: Dict[str, Dict[str, object]] = {
    "minos_baseline": MINOS_BASELINE,
    "minos_indel_focused": MINOS_INDEL_FOCUSED,
    "minos_precision_focused": MINOS_PRECISION_FOCUSED,
    "minos_competitive_recall": COMPETITIVE_RECALL_BASELINE,
}

PRESET_LABELS: Dict[str, str] = {
    "minos_baseline": "Minos Baseline (recommended start)",
    "minos_indel_focused": "Minos Indel-Focused (weak indel F1)",
    "minos_precision_focused": "Minos Precision-Focused (too many FPs)",
    "minos_competitive_recall": "Competitive Recall (toward 90+ leaders)",
}
