# GATK HaplotypeCaller Parameters — Minos Miner Reference

Guide to every tunable GATK parameter in Minos (Subnet 107): what each knob does, valid ranges, and which ones matter most for scoring.

**Related docs:** [tuning_guide.md](tuning_guide.md) (strategy & score components), [configs/gatk.conf](../configs/gatk.conf) (your editable config).

---

## How GATK Fits in Minos

Minos miners run **GATK HaplotypeCaller 4.5.0.0** in Docker on a benchmark BAM for a fixed genomic window (e.g. `chr20:10000000-15000000`). You submit **quality parameters only** from `configs/gatk.conf`. Validators re-run the same config and score the resulting VCF with **hap.py** and **AdvancedScorer** (0–100).

GATK has the most tunable parameters of the supported callers (GATK, DeepVariant, bcftools). That makes it the best choice for maximizing score — if you tune for Minos scoring, not generic defaults.

### What you cannot submit

Infrastructure settings are handled by the miner/validator runtime and stripped before submission:

- `threads`, `memory_gb`, `timeout`, `ref_build`, `num_threads`

Only parameters whitelisted in `templates/tool_params.py` are accepted.

---

## How Parameters Affect Your Score

AdvancedScorer combines hap.py metrics into four components:

| Component    | Weight | What moves it |
|--------------|--------|---------------|
| Core F1      | 60%    | SNP/INDEL precision and recall vs truth |
| Completeness | 15%    | Recall + fraction of sites hap.py could assess |
| FP Rate      | 15%    | False positives + total call count vs truth |
| Quality      | 10%    | Ti/Tv (~2.0) and Het/Hom (~1.5) ratios |

**Universal tradeoff:**

```
More aggressive calling  → higher recall, more false positives
More conservative calling → higher precision, lower recall
```

Minos weights slightly favor precision (Core F1 + steep FP penalty), but over-filtering hurts Completeness. Tune for balance, not maximum variant count.

---

## Most Important Parameters (Start Here)

Change these before touching anything else.

| Priority | Parameter | Default | Recommended | Why |
|----------|-----------|---------|-------------|-----|
| **1** | `pcr_indel_model` | `CONSERVATIVE` | **`NONE`** | Minos BAMs are PCR-free (GIAB-style). Default over-filters indels and hurts Core F1 and Completeness. |
| **2** | `standard_min_confidence_threshold_for_calling` | `30.0` | **20–40** | Main precision/recall dial. Primary lever for Core F1, Completeness, and FP Rate. |
| **3** | `min_mapping_quality_score` | `20` | **20–30** | Cuts false calls from poorly mapped reads when FP Rate is weak. |
| **4** | `min_base_quality_score` | `10` | **10–20** | Secondary quality filter. Raise only if FP Rate is clearly too high. |

### Minimal competitive starting config

```ini
pcr_indel_model=NONE
standard_min_confidence_threshold_for_calling=30
min_base_quality_score=10
```

### Tuning workflow

1. Set `pcr_indel_model=NONE` and run several rounds for a baseline.
2. Adjust `standard_min_confidence_threshold_for_calling` in steps of **5** (one change at a time).
3. If FP Rate is still low, raise `min_mapping_quality_score` before raising base quality filters.
4. Only then tune Tier 2/3 parameters below based on which score component is weak.

See [tuning_guide.md §4](tuning_guide.md#4-tuning-strategy) for diagnosis by component.

---

## Full Parameter Reference

All parameters live in `configs/gatk.conf`. Format: one `key=value` per line; `#` for comments.

Legend for **Score impact**:

- **F1** — Core F1 (60%)
- **Comp** — Completeness (15%)
- **FP** — FP Rate (15%)
- **Qual** — Quality (10%)

Direction: **↑ param** = increase the value.

---

### Quality filtering

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `min_base_quality_score` | 10 | 0–50 | `--min-base-quality-score` | Ignore bases below this Phred quality. | ↑ → ↑ precision, ↓ recall → **FP** ↑, **Comp** ↓. Avoid 30+. |
| `min_mapping_quality_score` | 20 | 0–60 | `--minimum-mapping-quality` | Exclude reads with MAPQ below this. | ↑ → cleaner calls, fewer FPs → **FP** ↑, **F1** often ↑. |
| `base_quality_score_threshold` | 18 | 0–50 | `--base-quality-score-threshold` | Downgrade (not drop) bases below this quality. | Softer than `min_base_quality_score`. Minor unless extreme. |

---

### Calling confidence

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `standard_min_confidence_threshold_for_calling` | 30.0 | 0–100 | `--standard-min-confidence-threshold-for-calling` | Minimum Phred confidence to emit a variant. | **Primary tuner.** ↑ → fewer, confident calls. ↓ → more calls. Affects **F1**, **Comp**, **FP**. |
| `emit_ref_confidence` | NONE | NONE, GVCF, BP_RESOLUTION | `--emit-ref-confidence` | Emit gVCF reference confidence. | Keep **`NONE`**. Minos scores variant VCFs, not gVCF. |

---

### PCR error model

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `pcr_indel_model` | CONSERVATIVE | NONE, HOSTILE, AGGRESSIVE, CONSERVATIVE | `--pcr-indel-model` | Model PCR stutter for indel calling. | **`NONE` for Minos.** Default hurts indel recall → **F1**, **Comp** ↓. |

---

### Assembly graph

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `min_pruning` | 2 | 1–10 | `--min-pruning` | Min read support before pruning assembly paths. | ↑ → **FP** ↑, **Comp** ↓. |
| `max_alternate_alleles` | 6 | 1–20 | `--max-alternate-alleles` | Max alternate alleles per site. | ↓ → may miss complex truth; ↑ → more FPs. **F1** (indels). |
| `min_dangling_branch_length` | 4 | 1–20 | `--min-dangling-branch-length` | Min branch length for dangling-end recovery. | ↓ → more indel recovery → **Comp** ↑, slight **FP** ↓. |
| `recover_all_dangling_branches` | false | bool | `--recover-all-dangling-branches` | Recover all dangling branches. | `true` → **Comp** ↑, **FP** ↓ on noisy data. |
| `max_num_haplotypes_in_population` | 128 | 8–512 | `--max-num-haplotypes-in-population` | Max haplotypes from assembly graph. | ↑ → complex regions; ↓ → may miss truth. **F1**. |
| `adaptive_pruning_initial_error_rate` | 0.001 | 0.0001–0.1 | `--adaptive-pruning-initial-error-rate` | Starting error rate for adaptive pruning. | ↑ → aggressive pruning → **FP** ↑, **Comp** ↓. Fine-tuning. |
| `pruning_lod_threshold` | 2.302585 | 0.5–10.0 | `--pruning-lod-threshold` | Log-odds pruning threshold; higher = more aggressive. | ↑ → **FP** ↑, **Comp** ↓. |

---

### Active region determination

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `active_probability_threshold` | 0.002 | 0.0001–0.05 | `--active-probability-threshold` | Min probability a locus is active. | ↑ → skip weak signal → **Comp** ↓. ↓ → **Comp** ↑, **FP** ↓. |
| `min_assembly_region_size` | 50 | 1–300 | `--min-assembly-region-size` | Minimum assembly region (bp). | Secondary; extreme values can miss edge variants. |
| `max_assembly_region_size` | 300 | 100–1000 | `--max-assembly-region-size` | Maximum assembly region (bp). | ↑ → better in dense clusters, slower. |
| `assembly_region_padding` | 100 | 0–500 | `--assembly-region-padding` | Extra bases around active regions. | ↑ → better boundary recall → **Comp** ↑ near window edges. |

---

### Pair-HMM / likelihood computation

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `pair_hmm_gap_continuation_penalty` | 10 | 1–30 | `--pair-hmm-gap-continuation-penalty` | Penalty for extending gaps in Pair-HMM. | ↑ → fewer long indels → indel **F1** ↓, **FP** ↑. |
| `phred_scaled_global_read_mismapping_rate` | 45 | 10–60 | `--phred-scaled-global-read-mismapping-rate` | Prior that reads are mismapped (Phred). | Usually leave default. Minor unless alignments are systematically bad. |

---

### Genotyping priors

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `heterozygosity` | 0.001 | 0.0001–0.01 | `--heterozygosity` | Prior SNP heterozygosity rate. | Wrong prior skews Het/Hom → **Qual**. Default is fine for WGS. |
| `indel_heterozygosity` | 0.000125 | 0.00001–0.001 | `--indel-heterozygosity` | Prior indel heterozygosity rate. | Too high → extra indel calls → **FP** ↓. |
| `sample_ploidy` | 2 | 1–10 | `--sample-ploidy` | Assumed sample ploidy. | **Must be 2** for diploid Minos samples. Not a tuning knob. |
| `contamination_fraction_to_filter` | 0.0 | 0.0–0.5 | `--contamination-fraction-to-filter` | Assumed contamination for downsampling. | Keep **0.0** unless contamination is known. |

---

### Downsampling

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `max_reads_per_alignment_start` | 50 | 0–1000 | `--max-reads-per-alignment-start` | Max reads per alignment start (0 = disable). | ↓ → may **Comp** ↓ at high-coverage sites. 0 = slowest, most evidence. |

---

### Read filtering

| Parameter | Default | Range | GATK flag | Description | Score impact |
|-----------|---------|-------|-----------|-------------|--------------|
| `dont_use_soft_clipped_bases` | false | bool | `--dont-use-soft-clipped-bases` | Ignore soft-clipped read ends. | `true` → **FP** ↑, may **Comp** ↓ at clip boundaries. |

---

## Diagnose by Weak Score Component

| Weak component | Likely cause | Try first |
|----------------|--------------|-----------|
| Core F1 | Precision/recall imbalance | `standard_min_confidence_threshold_for_calling` ±5; confirm `pcr_indel_model=NONE` |
| Completeness | Over-filtering | Lower confidence threshold; lower `min_base_quality_score`; lower `active_probability_threshold` |
| FP Rate | Too many calls | Raise confidence threshold; raise `min_mapping_quality_score`; raise `min_pruning` |
| Quality | Bad Ti/Tv or Het/Hom | Fix PCR model first; check `sample_ploidy=2`; avoid extreme confidence |

---

## Parameter Tiers (Quick Reference)

### Tier 1 — Always set / tune first

1. `pcr_indel_model`
2. `standard_min_confidence_threshold_for_calling`
3. `min_mapping_quality_score`
4. `min_base_quality_score`

### Tier 2 — After Tier 1 is stable

- `pair_hmm_gap_continuation_penalty`
- `active_probability_threshold`
- `min_pruning` / `pruning_lod_threshold`
- `max_alternate_alleles`, dangling-branch recovery params

### Tier 3 — Fine-tuning only

- Assembly region sizes and padding
- Heterozygosity priors
- Adaptive pruning rates
- Soft-clip and downsampling settings

### Do not change for scoring

- `emit_ref_confidence` — keep `NONE`
- `sample_ploidy` — keep `2`

---

## Common Mistakes

| Mistake | Effect |
|---------|--------|
| Leaving `pcr_indel_model=CONSERVATIVE` on PCR-free data | Lost indel recall |
| `standard_min_confidence_threshold_for_calling` > 50 | Crushed recall and Completeness |
| `min_base_quality_score` > 30 | Same — over-filtering |
| Changing many parameters at once | Cannot tell what helped |
| Expecting one round to prove a change | Region varies each round; trend over multiple rounds |

---

## Where Parameters Are Defined in Code

| Location | Purpose |
|----------|---------|
| [configs/gatk.conf](../configs/gatk.conf) | Miner-editable values |
| [templates/tool_params.py](../templates/tool_params.py) | Whitelist, ranges, GATK CLI flags |
| [templates/gatk.py](../templates/gatk.py) | Docker invocation |
| [docs/tuning_guide.md](tuning_guide.md) | Scoring strategy and tool comparison |

After editing `configs/gatk.conf`, restart the miner (or wait for the next round if already running). The miner loads config at submission time via `extract_tool_options()`.

---

## Summary

- **Most important:** `pcr_indel_model=NONE`, then `standard_min_confidence_threshold_for_calling`.
- **Goal:** Balance precision and recall for AdvancedScorer — not maximum variant count.
- **Method:** One parameter change at a time; compare component scores across rounds.
- **Config file:** `configs/gatk.conf`
