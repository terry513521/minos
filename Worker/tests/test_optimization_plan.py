from app.search import build_optimization_plan, format_optimization_plan


def test_optimization_plan_param_split():
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
    plan = build_optimization_plan(
        window="chr21:24742108-29742108",
        tool="gatk",
        params=[
            "standard_min_confidence_threshold_for_calling",
            "min_mapping_quality_score",
        ],
        param_intervals=intervals,
        base_conf=base_conf,
        concurrency=2,
        param_split=True,
        limit_seconds=1800,
        algorithm="grid",
    )

    assert plan["mode"] == "param_split"
    assert plan["full_cartesian_grid"] == 9
    assert plan["planned_trials"] == 5
    assert len(plan["lanes"]) == 2
    assert plan["lanes"][0]["param_pairs"] == 0
    assert plan["lanes"][1]["param_pairs"] == 0

    text = format_optimization_plan(plan)
    assert "Optimization plan" in text
    assert "full Cartesian grid: 9" in text
    assert "planned trials: 5" in text
    assert "lane 1:" in text
    assert "lane 2:" in text
