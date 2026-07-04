"""Tests for exhaustive grid search."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.benchmark import BenchmarkResult
from app.optimization.search import build_optimization_plan, count_search_trials, format_optimization_plan
from app.optimization.search_runners import run_adaptive_search, run_grid_search


def _result(conf: dict) -> BenchmarkResult:
    return BenchmarkResult(
        success=True,
        score=0.5,
        raw_score=50.0,
        conf=conf,
        variant_count=10,
    )


def test_grid_trial_count_matches_cartesian_size():
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
    params = list(intervals.keys())
    assert count_search_trials(
        base, "gatk", params, intervals, algorithm="grid", adaptive_max_trials=100
    ) == 9
    assert count_search_trials(
        base, "gatk", params, intervals, algorithm="grid", adaptive_max_trials=4
    ) == 5


def test_grid_search_evaluates_all_points_when_small():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    intervals = {"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}}
    evaluated: list[dict] = []

    def fake_batch(**kwargs):
        for conf in kwargs["candidate_variants"]:
            evaluated.append(conf)
            kwargs["record_result"](_result(conf), "grid")

    run_grid_search(
        base_conf=base,
        tool="gatk",
        param_names=["min_mapping_quality_score"],
        param_intervals=intervals,
        concurrency=2,
        max_trials=10,
        timed_out=lambda: False,
        evaluate=lambda conf: _result(conf),
        record_result=lambda result, label: None,
        run_batch=fake_batch,
    )

    # 3 grid values (15,20,25) minus base (20) => 2 search configs
    assert len(evaluated) == 2


def test_grid_search_uses_parallel_batches():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    intervals = {"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}}
    batch_sizes: list[int] = []

    def fake_batch(**kwargs):
        batch_sizes.append(len(kwargs["candidate_variants"]))

    run_grid_search(
        base_conf=base,
        tool="gatk",
        param_names=["min_mapping_quality_score"],
        param_intervals=intervals,
        concurrency=2,
        max_trials=10,
        timed_out=lambda: False,
        evaluate=lambda conf: _result(conf),
        record_result=lambda result, label: None,
        run_batch=fake_batch,
    )

    assert batch_sizes == [2]


def test_optimization_plan_grid_mode():
    base = {"gatk_options": {"min_mapping_quality_score": 20}}
    intervals = {"min_mapping_quality_score": {"min": 15, "max": 25, "step": 5}}
    plan = build_optimization_plan(
        window="chr21:1-100",
        tool="gatk",
        params=["min_mapping_quality_score"],
        param_intervals=intervals,
        base_conf=base,
        concurrency=2,
        limit_seconds=600,
        algorithm="grid",
        adaptive_max_trials=10,
    )
    assert plan["mode"] == "grid"
    assert plan["planned_trials"] == 3
    text = format_optimization_plan(plan)
    assert "search: grid 2 of 3 configs after base" in text


def test_run_adaptive_search_dispatches_grid(monkeypatch):
    calls: list[str] = []

    def fake_grid(**kwargs):
        calls.append("grid")

    monkeypatch.setattr("app.optimization.search_runners.run_grid_search", fake_grid)
    monkeypatch.setattr(
        "app.optimization.adaptive_search.resolve_search_specs",
        lambda tool, params, intervals: [],
    )

    class DummyRequest:
        job_id = "job-grid"
        tool = "gatk"
        params = ["min_mapping_quality_score"]

    run_adaptive_search(
        request=DummyRequest(),
        base_conf={"gatk_options": {}},
        intervals={},
        algorithm="grid",
        concurrency=2,
        max_trials=5,
        timed_out=lambda: True,
        evaluate=lambda conf: None,
        record_result=lambda result, label: None,
        run_batch=lambda **kwargs: None,
    )
    assert calls == ["grid"]
