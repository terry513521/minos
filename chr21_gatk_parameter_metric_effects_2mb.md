# chr21 GATK Parameter Effects vs AdvancedScorer Metrics

Source: `/root/minos/chr21_gatk_advanced_history.csv`
Region control: subtract median within `2,000,000` bp center bins before rank correlation.

Positive correlations help score-like metrics. For overcall metrics, negative correlations are good because lower is better.

## Strongest Score Effects

| parameter | score | core | complete | fp | quality | overcall penalty | fp/target | region FP | direction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `indel_heterozygosity` | +0.48 | +0.49 | +0.43 | +0.37 | +0.32 | n/a | -0.25 | -0.25 | higher better |
| `max_alternate_alleles` | +0.44 | +0.43 | +0.37 | +0.36 | +0.20 | n/a | -0.19 | -0.19 | higher better |
| `max_reads_per_alignment_start` | -0.42 | -0.43 | -0.34 | -0.33 | -0.25 | n/a | +0.25 | +0.24 | lower better |
| `assembly_region_padding` | -0.42 | -0.43 | -0.33 | -0.35 | -0.32 | n/a | +0.31 | +0.31 | lower better |
| `recover_all_dangling_branches` | -0.37 | -0.37 | -0.29 | -0.31 | -0.26 | n/a | +0.29 | +0.29 | lower better |
| `pruning_lod_threshold` | +0.33 | +0.31 | +0.34 | +0.29 | +0.10 | n/a | -0.15 | -0.14 | higher better |
| `heterozygosity` | +0.32 | +0.31 | +0.27 | +0.24 | +0.13 | n/a | -0.14 | -0.14 | higher better |
| `min_mapping_quality_score` | -0.31 | -0.31 | -0.27 | -0.23 | -0.20 | n/a | +0.00 | +0.00 | lower better |
| `max_num_haplotypes_in_population` | -0.30 | -0.32 | -0.24 | -0.25 | -0.29 | n/a | +0.31 | +0.31 | lower better |
| `max_assembly_region_size` | -0.27 | -0.28 | -0.22 | -0.24 | -0.31 | n/a | +0.34 | +0.34 | lower better |
| `contamination_fraction_to_filter` | -0.27 | -0.25 | -0.27 | -0.31 | -0.50 | n/a | +0.39 | +0.39 | lower better |
| `base_quality_score_threshold` | -0.22 | -0.24 | -0.16 | -0.21 | -0.13 | n/a | -0.12 | -0.12 | lower better |
| `standard_min_confidence_threshold_for_calling` | -0.22 | -0.21 | -0.12 | -0.19 | +0.01 | n/a | -0.07 | -0.07 | lower better |
| `min_pruning` | -0.21 | -0.23 | -0.21 | -0.18 | -0.08 | n/a | +0.10 | +0.10 | lower better |
| `pair_hmm_gap_continuation_penalty` | +0.20 | +0.23 | +0.21 | +0.22 | +0.03 | n/a | -0.13 | -0.13 | higher better |
| `adaptive_pruning_initial_error_rate` | +0.17 | +0.18 | +0.14 | +0.13 | +0.05 | n/a | -0.17 | -0.17 | higher better |
| `phred_scaled_global_read_mismapping_rate` | -0.16 | -0.16 | -0.11 | -0.09 | +0.03 | n/a | +0.01 | +0.01 | lower better |
| `min_assembly_region_size` | -0.15 | -0.14 | -0.14 | -0.12 | +0.00 | n/a | +0.05 | +0.05 | lower better |

## Reading Guide

- `score`: final AdvancedScorer score.
- `core`: 60-point truth-weighted F1 component.
- `complete`: 15-point recall/coverage component.
- `fp`: 15-point assessed false-positive/call-count component.
- `quality`: 10-point Ti/Tv and Het/Hom ratio component.
- `overcall penalty`, `fp/target`, and `region FP` are lower-is-better guardrail metrics.
