from app.search import build_search_space


def test_int_param_linear_grid_uses_int_not_float():
    base = {
        "gatk_options": {
            "min_base_quality_score": 10,
            "min_mapping_quality_score": 20,
        }
    }
    intervals = {
        "min_base_quality_score": {"min": 8, "max": 18, "step": 2},
    }
    variants = build_search_space(base, "gatk", ["min_base_quality_score"], intervals)
    values = [v["gatk_options"]["min_base_quality_score"] for v in variants]
    assert values, "expected grid variants"
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in values)
    assert 8 in values and 18 in values


def test_int_param_with_float_json_bounds():
    """Dispatch may send min/max/step as floats from the UI JSON."""
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    intervals = {
        "min_mapping_quality_score": {"min": 15.0, "max": 30.0, "step": 5.0},
    }
    variants = build_search_space(base, "gatk", ["min_mapping_quality_score"], intervals)
    for variant in variants:
        value = variant["gatk_options"]["min_mapping_quality_score"]
        assert isinstance(value, int), f"expected int, got {value!r} ({type(value)})"
