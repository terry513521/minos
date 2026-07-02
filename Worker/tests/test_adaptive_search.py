import pytest

from app.algorithms import is_adaptive_algorithm, normalize_algorithm
from app.adaptive_search import (
    build_conf_from_params,
    suggest_random_params,
)
from app.param_specs import resolve_tune_specs
from app.search import build_optimization_plan, count_search_trials


def test_normalize_algorithm():
    assert normalize_algorithm("GRID") == "grid"
    assert normalize_algorithm("optuna") == "optuna"
    with pytest.raises(ValueError):
        normalize_algorithm("bayesian")


def test_adaptive_trial_counts():
    base = {
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
        base, "gatk", list(intervals), intervals, algorithm="optuna", adaptive_max_trials=12
    ) == 13
    assert is_adaptive_algorithm("random")


def test_optimization_plan_optuna():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    plan = build_optimization_plan(
        window="chr21:1-100",
        tool="gatk",
        params=["min_mapping_quality_score"],
        param_intervals={"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}},
        base_conf=base,
        concurrency=2,
        param_split=True,
        limit_seconds=600,
        algorithm="optuna",
        adaptive_max_trials=20,
        vcf_cache_enabled=True,
        gatk_persistent_container=True,
    )
    assert plan["mode"] == "optuna"
    assert plan["planned_trials"] == 21
    assert plan["vcf_cache_enabled"] is True


def test_random_conf_sampler():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    specs = resolve_tune_specs(
        "gatk",
        ["min_mapping_quality_score"],
        {"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}},
    )
    params = suggest_random_params(__import__("random").Random(0), base, "gatk", specs)
    conf = build_conf_from_params(base, "gatk", params)
    assert conf["gatk_options"]["min_mapping_quality_score"] in {15, 20, 25}
