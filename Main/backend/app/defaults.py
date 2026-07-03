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


def default_tool_conf(tool: str) -> dict:
    tool_key = tool.lower().strip()
    if tool_key == "gatk":
        return DEFAULT_GATK_CONF
    return {f"{tool_key}_options": {}}
