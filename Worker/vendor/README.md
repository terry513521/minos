# Bundled Minos libraries

The Worker ships its own copy of the code it needs for GIAB benchmarking:

- `templates/` — GATK, bcftools, DeepVariant variant callers
- `utils/` — hap.py scoring (`HappyScorer`, `AdvancedScorer`)
- `tuning/` — GIAB BAM slicing (samtools), calibration, and scoring helpers

All runtime data still lives under `Worker/datasets/`. No parent `minos/` checkout is required.
