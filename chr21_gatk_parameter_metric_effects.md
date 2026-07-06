# chr21 GATK Parameter Effects vs AdvancedScorer Metrics

Source: `/root/minos/chr21_gatk_advanced_history.csv`
Region control: subtract median within `2,500,000` bp center bins before rank correlation.

Positive correlations help score-like metrics. For overcall metrics, negative correlations are good because lower is better.

## Strongest Score Effects

| parameter | score | core | complete | fp | quality | overcall penalty | fp/target | region FP | direction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `indel_heterozygosity` | +0.47 | +0.48 | +0.43 | +0.35 | +0.30 | n/a | -0.25 | -0.25 | higher better |
| `max_reads_per_alignment_start` | -0.47 | -0.47 | -0.39 | -0.42 | -0.27 | n/a | +0.29 | +0.29 | lower better |
| `recover_all_dangling_branches` | -0.42 | -0.40 | -0.34 | -0.43 | -0.29 | n/a | +0.32 | +0.32 | lower better |
| `max_alternate_alleles` | +0.42 | +0.43 | +0.36 | +0.33 | +0.22 | n/a | -0.23 | -0.23 | higher better |
| `assembly_region_padding` | -0.42 | -0.41 | -0.33 | -0.40 | -0.34 | n/a | +0.38 | +0.38 | lower better |
| `min_mapping_quality_score` | -0.33 | -0.32 | -0.30 | -0.24 | -0.22 | n/a | +0.05 | +0.05 | lower better |
| `pruning_lod_threshold` | +0.32 | +0.30 | +0.32 | +0.25 | +0.10 | n/a | -0.12 | -0.12 | higher better |
| `contamination_fraction_to_filter` | -0.31 | -0.27 | -0.26 | -0.35 | -0.56 | n/a | +0.49 | +0.49 | lower better |
| `max_num_haplotypes_in_population` | -0.30 | -0.31 | -0.26 | -0.30 | -0.29 | n/a | +0.33 | +0.33 | lower better |
| `max_assembly_region_size` | -0.27 | -0.30 | -0.22 | -0.25 | -0.33 | n/a | +0.35 | +0.35 | lower better |
| `heterozygosity` | +0.27 | +0.27 | +0.19 | +0.15 | +0.09 | n/a | -0.11 | -0.11 | higher better |
| `base_quality_score_threshold` | -0.27 | -0.27 | -0.22 | -0.27 | -0.12 | n/a | -0.09 | -0.09 | lower better |
| `min_pruning` | -0.23 | -0.26 | -0.19 | -0.20 | -0.07 | n/a | +0.13 | +0.13 | lower better |
| `standard_min_confidence_threshold_for_calling` | -0.17 | -0.19 | -0.12 | -0.15 | -0.00 | n/a | -0.07 | -0.07 | lower better |
| `adaptive_pruning_initial_error_rate` | +0.17 | +0.18 | +0.12 | +0.11 | +0.02 | n/a | -0.14 | -0.14 | higher better |
| `pair_hmm_gap_continuation_penalty` | +0.17 | +0.21 | +0.15 | +0.18 | +0.03 | n/a | -0.11 | -0.11 | higher better |
| `min_assembly_region_size` | -0.16 | -0.15 | -0.13 | -0.11 | -0.05 | n/a | +0.06 | +0.06 | lower better |
| `min_dangling_branch_length` | +0.14 | +0.12 | +0.17 | +0.11 | +0.24 | n/a | -0.11 | -0.11 | higher better |

## Reading Guide

- `score`: final AdvancedScorer score.
- `core`: 60-point truth-weighted F1 component.
- `complete`: 15-point recall/coverage component.
- `fp`: 15-point assessed false-positive/call-count component.
- `quality`: 10-point Ti/Tv and Het/Hom ratio component.
- `overcall penalty`, `fp/target`, and `region FP` are lower-is-better guardrail metrics.
