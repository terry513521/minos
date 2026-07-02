import pytest

from app.optimization.algorithms import is_adaptive_algorithm, normalize_algorithm
from app.optimization.param_specs import resolve_tune_specs
from app.optimization.quasi_random import (
    build_quasi_sample_confs,
    generate_unit_samples,
    params_from_unit_row,
    seed_from_job_id,
    unit_to_index,
)
from app.optimization.search import build_optimization_plan


def test_normalize_sobol_lhs():
    assert normalize_algorithm("Sobol") == "sobol"
    assert normalize_algorithm("LHS") == "lhs"
    assert is_adaptive_algorithm("sobol")
    assert is_adaptive_algorithm("lhs")


def test_unit_to_index_edges():
    assert unit_to_index(0.0, 5) == 0
    assert unit_to_index(0.999, 5) == 4
    assert unit_to_index(0.5, 1) == 0


def test_lhs_and_sobol_are_deterministic():
    lhs_a = generate_unit_samples("lhs", 8, 3, seed=42)
    lhs_b = generate_unit_samples("lhs", 8, 3, seed=42)
    sobol_a = generate_unit_samples("sobol", 8, 3, seed=42)
    sobol_b = generate_unit_samples("sobol", 8, 3, seed=42)
    assert lhs_a == lhs_b
    assert sobol_a == sobol_b
    assert lhs_a != sobol_a


def test_lhs_stratifies_each_dimension():
    samples = generate_unit_samples("lhs", 6, 2, seed=7)
    for dim in range(2):
        strata = {int(u * 6) for u in (row[dim] for row in samples)}
        assert strata == set(range(6))


def test_params_from_unit_row_maps_discrete_axes():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    specs = resolve_tune_specs(
        "gatk",
        ["min_mapping_quality_score"],
        {"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}},
    )
    params = params_from_unit_row(
        [0.5],
        base_conf=base,
        tool="gatk",
        specs=specs,
    )
    assert params["min_mapping_quality_score"] in {15, 20, 25}


def test_build_quasi_sample_confs_respects_job_seed():
    base = {
        "gatk_options": {
            "standard_min_confidence_threshold_for_calling": 30.0,
            "min_mapping_quality_score": 20,
        }
    }
    intervals = {
        "standard_min_confidence_threshold_for_calling": {"min": 25, "max": 35, "step": 5},
        "min_mapping_quality_score": {"min": 15, "max": 25, "step": 5},
    }
    specs = resolve_tune_specs("gatk", list(intervals), intervals)
    seed = seed_from_job_id("job-abc")
    lhs = build_quasi_sample_confs(
        "lhs",
        n=5,
        base_conf=base,
        tool="gatk",
        specs=specs,
        seed=seed,
    )
    sobol = build_quasi_sample_confs(
        "sobol",
        n=5,
        base_conf=base,
        tool="gatk",
        specs=specs,
        seed=seed,
    )
    assert len(lhs) == 5
    assert len(sobol) == 5
    for row in lhs + sobol:
        conf_val = row["standard_min_confidence_threshold_for_calling"]
        mq = row["min_mapping_quality_score"]
        assert conf_val in {25, 30, 35}
        assert mq in {15, 20, 25}


@pytest.mark.parametrize("algorithm", ["sobol", "lhs"])
def test_optimization_plan_quasi_random(algorithm: str):
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    plan = build_optimization_plan(
        window="chr21:1-100",
        tool="gatk",
        params=["min_mapping_quality_score"],
        param_intervals={"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}},
        base_conf=base,
        concurrency=1,
        limit_seconds=600,
        algorithm=algorithm,
        adaptive_max_trials=12,
        vcf_cache_enabled=True,
        gatk_persistent_container=False,
    )
    assert plan["mode"] == algorithm
    assert plan["planned_trials"] == 13
