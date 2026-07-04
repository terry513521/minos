"""Shared default configs (no service imports)."""

MAX_TRIAL_THREADS = 100

DEFAULT_GATK_CONF = {
    "gatk_options": {
        "pcr_indel_model": "NONE",
        "standard_min_confidence_threshold_for_calling": 30.0,
        "min_base_quality_score": 10,
        "min_mapping_quality_score": 20,
    }
}

DEFAULT_DEEPVARIANT_CONF = {
    "deepvariant_options": {
        "model_type": "WGS",
        "vsc_min_fraction_indels": 0.12,
        "vsc_min_fraction_snps": 0.12,
        "vsc_min_count_snps": 2,
        "vsc_min_count_indels": 2,
        "min_mapping_quality": 5,
        "min_base_quality": 10,
        "realign_reads": True,
        "normalize_reads": False,
        "keep_duplicates": False,
        "max_reads_per_partition": 1500,
        "sort_by_haplotypes": False,
        "phase_reads": False,
        "qual_filter": 1.0,
        "multi_allelic_qual_filter": 1.0,
        "cnn_homref_call_min_gq": 20.0,
        "use_multiallelic_model": False,
    }
}

DEFAULT_BCFTOOLS_CONF = {
    "bcftools_options": {
        "min_MQ": 0,
        "min_BQ": 13,
    }
}

_TOOL_DEFAULTS = {
    "gatk": DEFAULT_GATK_CONF,
    "deepvariant": DEFAULT_DEEPVARIANT_CONF,
    "bcftools": DEFAULT_BCFTOOLS_CONF,
}

DEFAULT_TRIAL_MEMORY_GB_BY_TOOL = {
    "gatk": 6,
    "bcftools": 6,
    "deepvariant": 16,
}


def default_tool_conf(tool: str) -> dict:
    tool_key = tool.lower().strip()
    return _TOOL_DEFAULTS.get(tool_key, {f"{tool_key}_options": {}})


def default_trial_memory_gb_for_tool(tool: str, *, fallback: int = 6) -> int:
    tool_key = tool.lower().strip()
    return DEFAULT_TRIAL_MEMORY_GB_BY_TOOL.get(tool_key, fallback)
