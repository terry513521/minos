"""Tests for PBT and cascade search algorithms."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.benchmark import BenchmarkResult
from app.optimization.evolutionary_search import (
    SearchTracker,
    extract_params_from_conf,
    generate_local_neighbors,
    mutate_params,
    run_cascade_search,
    run_pbt_search,
)
from app.optimization.param_specs import TuneSpec
from app.optimization.search_runners import ConfMemory, run_adaptive_search


def _spec(name: str, *, values: tuple | None = None, **kwargs) -> TuneSpec:
    if values is not None:
        return TuneSpec(name=name, values=values)
    return TuneSpec(name=name, value_type="int", min=10, max=30, step=5, **kwargs)


def _result(score: float, conf: dict) -> BenchmarkResult:
    return BenchmarkResult(
        success=True,
        score=score,
        raw_score=score * 100,
        conf=conf,
        variant_count=100,
    )


def test_mutate_params_changes_discrete_value():
    rng = __import__("random").Random(0)
    specs = [_spec("pcr_indel_model", values=("NONE", "CONSERVATIVE"))]
    params = {"pcr_indel_model": "NONE"}
    mutated = mutate_params(rng, params, {"gatk_options": {}}, "gatk", specs, strength=1.0)
    assert mutated["pcr_indel_model"] in ("NONE", "CONSERVATIVE")


def test_generate_local_neighbors_moves_one_step():
    specs = [_spec("min_mapping_quality_score")]
    params = {"min_mapping_quality_score": 20}
    neighbors = generate_local_neighbors(
        params,
        {"gatk_options": {"min_mapping_quality_score": 20}},
        "gatk",
        specs,
        max_neighbors=10,
    )
    assert neighbors
    assert all(len(n) == 1 for n in neighbors)


def test_extract_params_from_conf():
    conf = {"gatk_options": {"pcr_indel_model": "NONE", "min_base_quality_score": 10}}
    specs = [
        _spec("pcr_indel_model", values=("NONE", "CONSERVATIVE")),
        _spec("min_base_quality_score"),
    ]
    params = extract_params_from_conf(conf, "gatk", specs)
    assert params["pcr_indel_model"] == "NONE"
    assert params["min_base_quality_score"] == 10


def test_pbt_search_runs_trials():
    specs = [_spec("min_mapping_quality_score")]
    base_conf = {"gatk_options": {"min_mapping_quality_score": 20}}
    evaluated: list[dict] = []

    def evaluate(conf):
        evaluated.append(conf)
        return _result(0.5, conf)

    run_pbt_search(
        job_id="pbt-test",
        base_conf=base_conf,
        tool="gatk",
        specs=specs,
        concurrency=2,
        max_trials=4,
        timed_out=lambda: False,
        evaluate=evaluate,
        record_result=lambda result, label: None,
        memory=ConfMemory(base_conf),
    )
    assert len(evaluated) >= 2


def test_cascade_search_runs_all_stages():
    specs = [_spec("min_mapping_quality_score")]
    base_conf = {"gatk_options": {"min_mapping_quality_score": 20}}
    labels: list[str] = []

    def evaluate(conf):
        return _result(0.6, conf)

    def record_result(result, label):
        labels.append(label)

    run_cascade_search(
        job_id="cascade-test",
        base_conf=base_conf,
        tool="gatk",
        specs=specs,
        concurrency=2,
        max_trials=12,
        timed_out=lambda: False,
        evaluate=evaluate,
        record_result=record_result,
        run_batch=MagicMock(),
        memory=ConfMemory(base_conf),
    )
    assert "cascade-explore" in labels
    assert "cascade-refine" in labels or "pbt" in labels


@pytest.mark.parametrize("algorithm", ["pbt", "cascade"])
def test_run_adaptive_search_dispatches_new_algorithms(algorithm: str, monkeypatch):
    calls: list[str] = []

    def fake_pbt(**kwargs):
        calls.append("pbt")

    def fake_cascade(**kwargs):
        calls.append("cascade")

    monkeypatch.setattr("app.optimization.search_runners.run_pbt_search", fake_pbt)
    monkeypatch.setattr("app.optimization.search_runners.run_cascade_search", fake_cascade)
    monkeypatch.setattr(
        "app.optimization.adaptive_search.resolve_search_specs",
        lambda tool, params, intervals: [],
    )

    class DummyRequest:
        job_id = "job-test"
        tool = "gatk"
        params = ["min_mapping_quality_score"]

    run_adaptive_search(
        request=DummyRequest(),
        base_conf={"gatk_options": {}},
        intervals={},
        algorithm=algorithm,
        concurrency=4,
        max_trials=10,
        timed_out=lambda: True,
        evaluate=lambda conf: None,
        record_result=lambda result, label: None,
        run_batch=lambda **kwargs: None,
    )
    assert calls == [algorithm]


def test_search_tracker_keeps_best():
    tracker = SearchTracker()
    specs = [_spec("min_mapping_quality_score")]
    conf_a = {"gatk_options": {"min_mapping_quality_score": 20}}
    conf_b = {"gatk_options": {"min_mapping_quality_score": 25}}
    tracker.consider(_result(0.4, conf_a), {"min_mapping_quality_score": 20})
    tracker.consider(_result(0.7, conf_b), {"min_mapping_quality_score": 25})
    assert tracker.best_score == pytest.approx(0.7)
    assert tracker.best_params["min_mapping_quality_score"] == 25
