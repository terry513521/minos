from app.optimization.search import build_optimization_plan, format_optimization_plan


def test_optimization_plan_adaptive():
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
        limit_seconds=1800,
        algorithm="gp",
        adaptive_max_trials=12,
    )

    assert plan["mode"] == "gp"
    assert plan["full_cartesian_grid"] == 9
    assert plan["planned_trials"] == 13

    text = format_optimization_plan(plan)
    assert "Optimization plan" in text
    assert "assigned window:" in text
    assert "search: gp up to 12 trials after base" in text
    assert "planned trials: 13" in text


def test_optimization_plan_shows_benchmark_slice():
    plan = build_optimization_plan(
        window="chr21:1000000-6000000",
        benchmark_window="chr21:2000000-5000000",
        tool="gatk",
        params=["min_mapping_quality_score"],
        param_intervals={"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}},
        base_conf={"gatk_options": {"min_mapping_quality_score": 20}},
        concurrency=1,
        limit_seconds=600,
        algorithm="optuna",
    )
    text = format_optimization_plan(plan)
    assert "assigned window: chr21:1000000-6000000" in text
    assert "benchmark slice: chr21:2000000-5000000" in text
