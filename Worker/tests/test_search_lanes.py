from app.optimization.search import count_search_trials, split_params_for_lanes


def test_split_params_for_lanes_round_robin():
    assert split_params_for_lanes(["a", "b", "c", "d"], 2) == [["a", "c"], ["b", "d"]]
    assert split_params_for_lanes(["a", "b"], 4) == [["a"], ["b"]]
    assert split_params_for_lanes(["a"], 2) == [["a"]]


def test_count_search_trials_uses_adaptive_cap():
    base_conf = {
        "gatk_options": {
            "standard_min_confidence_threshold_for_calling": 30.0,
            "min_mapping_quality_score": 20,
        }
    }
    intervals = {
        "standard_min_confidence_threshold_for_calling": {"min": 20, "max": 30, "step": 5},
        "min_mapping_quality_score": {"min": 15, "max": 25, "step": 5},
    }
    assert count_search_trials(
        base_conf,
        "gatk",
        [
            "standard_min_confidence_threshold_for_calling",
            "min_mapping_quality_score",
        ],
        intervals,
        algorithm="gp",
        adaptive_max_trials=12,
    ) == 13
