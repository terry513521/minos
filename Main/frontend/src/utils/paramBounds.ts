/**
 * Parameter bounds for the worker card UI.
 * Hard min/max: templates/tool_params.py (GATK validator whitelist).
 * Default search intervals: docs/config-optimization-plan.md §6 + Worker/app/param_specs.py.
 */

export type ParamValueType = "int" | "float" | "enum" | "bool";

export interface ParamBoundSpec {
  type: ParamValueType;
  /** Validator hard minimum (tool_params). */
  min?: number;
  /** Validator hard maximum (tool_params). */
  max?: number;
  /** Default grid step when selected. */
  step?: number;
  allowedValues?: string[];
  /** Narrower default min/max when the param is first selected (search slice). */
  searchMin?: number;
  searchMax?: number;
}

export interface ParamInterval {
  min?: number;
  max?: number;
  step?: number;
  delta?: number;
  values?: string[];
}

type BoundMap = Record<string, ParamBoundSpec>;

function n(
  type: "int" | "float",
  min: number,
  max: number,
  step?: number,
  search?: { min: number; max: number },
): ParamBoundSpec {
  const spec: ParamBoundSpec = { type, min, max, step };
  if (search) {
    spec.searchMin = search.min;
    spec.searchMax = search.max;
  }
  return spec;
}

function en(allowedValues: string[]): ParamBoundSpec {
  return { type: "enum", allowedValues };
}

/** GATK — templates/tool_params.py GATK_QUALITY_PARAMS */
const GATK_BOUNDS: BoundMap = {
  min_base_quality_score: n("int", 0, 50, 2, { min: 8, max: 18 }),
  min_mapping_quality_score: n("int", 0, 60, 5, { min: 15, max: 30 }),
  base_quality_score_threshold: n("int", 0, 50, 2),
  standard_min_confidence_threshold_for_calling: n("float", 0, 100, 2.5, {
    min: 20,
    max: 40,
  }),
  emit_ref_confidence: en(["NONE", "GVCF", "BP_RESOLUTION"]),
  pcr_indel_model: en(["NONE", "CONSERVATIVE"]),
  min_pruning: n("int", 1, 10, 1),
  max_alternate_alleles: n("int", 1, 20, 1),
  min_dangling_branch_length: n("int", 1, 20, 1),
  max_num_haplotypes_in_population: n("int", 8, 512, 16),
  adaptive_pruning_initial_error_rate: n("float", 0.0001, 0.1, 0.0001),
  pruning_lod_threshold: n("float", 0.5, 10, 0.1),
  active_probability_threshold: n("float", 0.0001, 0.05, 0.0005),
  min_assembly_region_size: n("int", 1, 300, 10),
  max_assembly_region_size: n("int", 100, 1000, 50),
  assembly_region_padding: n("int", 0, 500, 10),
  pair_hmm_gap_continuation_penalty: n("int", 1, 30, 1),
  phred_scaled_global_read_mismapping_rate: n("int", 10, 60, 5),
  heterozygosity: n("float", 0.0001, 0.01, 0.0001),
  indel_heterozygosity: n("float", 0.00001, 0.001, 0.00001),
  sample_ploidy: n("int", 1, 10, 1),
  contamination_fraction_to_filter: n("float", 0, 0.5, 0.05),
  max_reads_per_alignment_start: n("int", 0, 1000, 10),
  recover_all_dangling_branches: { type: "bool" },
  dont_use_soft_clipped_bases: { type: "bool" },
};

/** bcftools — BCFTOOLS_QUALITY_PARAMS (common mpileup/call params) */
const BCFTOOLS_BOUNDS: BoundMap = {
  min_MQ: n("int", 0, 60, 5),
  min_BQ: n("int", 0, 50, 2),
  max_BQ: n("int", 1, 90, 5),
  delta_BQ: n("int", 0, 99, 5),
  adjust_MQ: n("int", 0, 100, 5),
  max_depth: n("int", 0, 10000, 50),
  max_idepth: n("int", 1, 10000, 50),
  no_BAQ: { type: "bool" },
  full_BAQ: { type: "bool" },
  no_indel_baq: { type: "bool" },
  no_orphan: { type: "bool" },
  no_overlap: { type: "bool" },
  no_exclude: { type: "bool" },
  no_filter: { type: "bool" },
};

/** DeepVariant — DEEPVARIANT_QUALITY_PARAMS */
const DEEPVARIANT_BOUNDS: BoundMap = {
  model_type: en(["WGS", "WES", "PACBIO", "HYBRID_PACBIO_ILLUMINA"]),
  vsc_min_fraction_indels: n("float", 0, 1, 0.01),
  vsc_min_fraction_snps: n("float", 0, 1, 0.01),
  vsc_min_count_snps: n("int", 0, 50, 1),
  vsc_min_count_indels: n("int", 0, 50, 1),
  min_mapping_quality: n("int", 0, 60, 5, { min: 3, max: 12 }),
  min_base_quality: n("int", 0, 50, 2, { min: 8, max: 15 }),
  max_reads_per_partition: n("int", 100, 5000, 100),
  qual_filter: n("float", 0, 50, 0.5, { min: 0.5, max: 3.0 }),
  multi_allelic_qual_filter: n("float", 0, 50, 1),
  cnn_homref_call_min_gq: n("float", 0, 50, 1),
  realign_reads: { type: "bool" },
  normalize_reads: { type: "bool" },
  keep_duplicates: { type: "bool" },
  sort_by_haplotypes: { type: "bool" },
  phase_reads: { type: "bool" },
};

const BOUNDS_BY_TOOL: Record<string, BoundMap> = {
  gatk: GATK_BOUNDS,
  bcftools: BCFTOOLS_BOUNDS,
  deepvariant: DEEPVARIANT_BOUNDS,
};

export function getParamBound(tool: string, param: string): ParamBoundSpec | null {
  return BOUNDS_BY_TOOL[tool.toLowerCase()]?.[param] ?? null;
}

function clampNum(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Clamp interval fields to validator hard limits. */
export function clampParamInterval(
  tool: string,
  param: string,
  interval: ParamInterval,
): ParamInterval {
  const spec = getParamBound(tool, param);
  if (!spec || spec.type === "enum" || spec.type === "bool") {
    return interval;
  }
  if (spec.min == null || spec.max == null) {
    return interval;
  }

  const out: ParamInterval = { ...interval };
  if (out.min != null) out.min = clampNum(out.min, spec.min, spec.max);
  if (out.max != null) out.max = clampNum(out.max, spec.min, spec.max);
  if (out.min != null && out.max != null && out.min > out.max) {
    out.max = out.min;
  }
  if (out.step != null && out.step <= 0) {
    out.step = spec.step ?? 1;
  }
  return out;
}

export function formatBoundHint(tool: string, param: string): string | null {
  const spec = getParamBound(tool, param);
  if (!spec) return null;
  if (spec.type === "enum" && spec.allowedValues?.length) {
    return `Allowed: ${spec.allowedValues.join(", ")}`;
  }
  if (spec.type === "bool") {
    return "Allowed: false, true";
  }
  if (spec.min == null || spec.max == null) return null;
  let hint = `Allowed: ${spec.min}–${spec.max}`;
  if (spec.searchMin != null && spec.searchMax != null) {
    hint += ` · default search: ${spec.searchMin}–${spec.searchMax}`;
  }
  return hint;
}

export function defaultParamInterval(
  tool: string,
  param: string,
  baseValue: string,
): ParamInterval {
  const spec = getParamBound(tool, param);
  if (!spec) {
    const num = Number(baseValue);
    if (Number.isFinite(num)) {
      return { min: num, max: num, step: 1 };
    }
    return { values: [baseValue] };
  }

  if (spec.type === "enum" || spec.type === "bool") {
    const allowed = spec.allowedValues ?? (spec.type === "bool" ? ["false", "true"] : []);
    const normalized = baseValue.trim();
    if (allowed.includes(normalized)) {
      return { values: [normalized] };
    }
    return { values: allowed.length > 0 ? [allowed[0]] : [normalized] };
  }

  const hardMin = spec.min ?? 0;
  const hardMax = spec.max ?? hardMin;
  const step = spec.step ?? 1;

  if (spec.searchMin != null && spec.searchMax != null) {
    return {
      min: clampNum(spec.searchMin, hardMin, hardMax),
      max: clampNum(spec.searchMax, hardMin, hardMax),
      step,
    };
  }

  const base = Number(baseValue);
  if (Number.isFinite(base)) {
    const margin = step * 2;
    return {
      min: clampNum(base - margin, hardMin, hardMax),
      max: clampNum(base + margin, hardMin, hardMax),
      step,
    };
  }

  return { min: hardMin, max: hardMax, step };
}

/** Default ± perturbation for delta search (falls back to step or a narrow slice). */
export function defaultParamDelta(
  tool: string,
  param: string,
  baseValue: string,
): number {
  const interval = defaultParamInterval(tool, param, baseValue);
  if (interval.step != null && interval.step > 0) {
    return interval.step;
  }
  const spec = getParamBound(tool, param);
  if (spec?.type === "int") {
    return Math.max(1, Math.round((spec.max ?? 1) - (spec.min ?? 0)) / 10);
  }
  if (spec?.type === "float" && spec.min != null && spec.max != null) {
    return Math.max(0.01, Math.round(((spec.max - spec.min) / 20) * 1000) / 1000);
  }
  return 1;
}

export function intervalForDispatch(interval: ParamInterval | undefined): ParamInterval | undefined {
  if (!interval) return undefined;
  const out: ParamInterval = {};
  if (interval.min != null && Number.isFinite(interval.min)) out.min = interval.min;
  if (interval.max != null && Number.isFinite(interval.max)) out.max = interval.max;
  if (interval.step != null && Number.isFinite(interval.step) && interval.step > 0) {
    out.step = interval.step;
  }
  if (interval.delta != null && Number.isFinite(interval.delta) && interval.delta > 0) {
    out.delta = interval.delta;
  }
  if (interval.values?.length) {
    out.values = interval.values.map((v) => v.trim()).filter(Boolean);
  }
  if (Object.keys(out).length === 0) return undefined;
  return out;
}

export function buildDispatchParamIntervals(
  tool: string,
  selectedParams: string[],
  paramIntervals: Record<string, ParamInterval>,
  algorithm?: string,
): Record<string, ParamInterval> | undefined {
  const out: Record<string, ParamInterval> = {};
  const useDelta = String(algorithm ?? "").toLowerCase() === "delta";
  for (const param of selectedParams) {
    const clamped = clampParamInterval(tool, param, paramIntervals[param] ?? {});
    const interval = intervalForDispatch(clamped);
    if (!interval) continue;
    if (useDelta && interval.delta == null && clamped.delta != null) {
      interval.delta = clamped.delta;
    }
    out[param] = interval;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

/** Reference GATK conf for auto-mode param picker (all whitelisted params). */
const GATK_REFERENCE_VALUES: Record<string, string | number | boolean> = {
  min_base_quality_score: 10,
  min_mapping_quality_score: 20,
  base_quality_score_threshold: 18,
  standard_min_confidence_threshold_for_calling: 30,
  emit_ref_confidence: "NONE",
  pcr_indel_model: "CONSERVATIVE",
  min_pruning: 2,
  max_alternate_alleles: 6,
  min_dangling_branch_length: 4,
  recover_all_dangling_branches: false,
  max_num_haplotypes_in_population: 128,
  adaptive_pruning_initial_error_rate: 0.001,
  pruning_lod_threshold: 2.302585,
  active_probability_threshold: 0.002,
  min_assembly_region_size: 50,
  max_assembly_region_size: 300,
  assembly_region_padding: 100,
  pair_hmm_gap_continuation_penalty: 10,
  phred_scaled_global_read_mismapping_rate: 45,
  heterozygosity: 0.001,
  indel_heterozygosity: 0.000125,
  sample_ploidy: 2,
  contamination_fraction_to_filter: 0,
  max_reads_per_alignment_start: 50,
  dont_use_soft_clipped_bases: false,
};

export function listGatkParamNames(): string[] {
  return Object.keys(GATK_BOUNDS);
}

export function listToolParamNames(tool: string): string[] {
  return Object.keys(BOUNDS_BY_TOOL[tool.toLowerCase()] ?? GATK_BOUNDS);
}

function buildReferenceConfForBounds(
  bounds: BoundMap,
  referenceValues: Record<string, string | number | boolean>,
  optionsKey: string,
): Record<string, unknown> {
  const options: Record<string, unknown> = { ...referenceValues };
  for (const [name, spec] of Object.entries(bounds)) {
    if (name in options) continue;
    if (spec.type === "enum") {
      options[name] = spec.allowedValues?.[0] ?? "";
    } else if (spec.type === "bool") {
      options[name] = false;
    } else {
      options[name] = spec.min ?? 0;
    }
  }
  return { [optionsKey]: options };
}

const DEEPVARIANT_REFERENCE_VALUES: Record<string, string | number | boolean> = {
  model_type: "WGS",
  vsc_min_fraction_indels: 0.12,
  vsc_min_fraction_snps: 0.12,
  vsc_min_count_snps: 2,
  vsc_min_count_indels: 2,
  min_mapping_quality: 5,
  min_base_quality: 10,
  realign_reads: true,
  normalize_reads: false,
  keep_duplicates: false,
  max_reads_per_partition: 1500,
  sort_by_haplotypes: false,
  phase_reads: false,
  qual_filter: 1.0,
  multi_allelic_qual_filter: 1.0,
  cnn_homref_call_min_gq: 20.0,
  use_multiallelic_model: false,
};

export function buildGatkReferenceConf(): Record<string, unknown> {
  return buildReferenceConfForBounds(GATK_BOUNDS, GATK_REFERENCE_VALUES, "gatk_options");
}

export function buildDeepvariantReferenceConf(): Record<string, unknown> {
  return buildReferenceConfForBounds(
    DEEPVARIANT_BOUNDS,
    DEEPVARIANT_REFERENCE_VALUES,
    "deepvariant_options",
  );
}

export function buildToolReferenceConf(tool: string): Record<string, unknown> {
  const toolKey = tool.toLowerCase().trim();
  if (toolKey === "deepvariant") return buildDeepvariantReferenceConf();
  if (toolKey === "bcftools") {
    return buildReferenceConfForBounds(BCFTOOLS_BOUNDS, { min_MQ: 0, min_BQ: 13 }, "bcftools_options");
  }
  return buildGatkReferenceConf();
}
