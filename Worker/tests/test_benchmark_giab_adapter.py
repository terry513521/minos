from app.benchmark import tool_params_from_conf


def test_tool_params_from_conf_extracts_gatk_options():
    conf = {
        "gatk_options": {
            "pcr_indel_model": "NONE",
            "standard_min_confidence_threshold_for_calling": 30,
        },
        "threads": 4,
    }
    params = tool_params_from_conf(conf, "gatk")
    assert params["pcr_indel_model"] == "NONE"
    assert params["standard_min_confidence_threshold_for_calling"] == 30
    assert "threads" not in params


def test_tool_params_from_conf_flat_gatk():
    conf = {
        "pcr_indel_model": "NONE",
        "min_mapping_quality_score": 20,
    }
    params = tool_params_from_conf(conf, "gatk")
    assert params["min_mapping_quality_score"] == 20
