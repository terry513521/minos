"""Tests for delta (±) local refinement search."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.optimization.delta_search import generate_delta_neighbors, resolve_delta_rounds
from app.optimization.param_specs import TuneSpec
from app.optimization.search_runners import run_adaptive_search


def _spec(name: str, *, values: tuple | None = None, **kwargs) -> TuneSpec:
    if values is not None:
        return TuneSpec(name=name, values=values)
    return TuneSpec(name=name, value_type="int", min=10, max=30, step=5, delta=2, **kwargs)


def test_generate_delta_neighbors_numeric_plus_minus():
    specs = [_spec("min_mapping_quality_score")]
    params = {"min_mapping_quality_score": 20}
    neighbors = generate_delta_neighbors(
        params,
        {"gatk_options": {"min_mapping_quality_score": 20}},
        "gatk",
        specs,
        {"min_mapping_quality_score": {"delta": 2}},
    )
    values = {n["min_mapping_quality_score"] for n in neighbors}
    assert values == {18, 22}


def test_resolve_delta_rounds_defaults_from_trial_budget():
    assert resolve_delta_rounds(None, max_trials=20, param_count=3) == 3


def test_run_adaptive_search_dispatches_delta(monkeypatch):
    captured: dict = {}

    def fake_delta(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.optimization.delta_search.run_delta_search",
        fake_delta,
    )
    monkeypatch.setattr(
        "app.optimization.adaptive_search.resolve_search_specs",
        lambda tool, params, intervals: [_spec("min_mapping_quality_score")],
    )

    request = MagicMock()
    request.tool = "gatk"
    request.params = ["min_mapping_quality_score"]
    request.delta_rounds = 4

    run_adaptive_search(
        request=request,
        base_conf={"gatk_options": {"min_mapping_quality_score": 20}},
        intervals={"min_mapping_quality_score": {"delta": 2}},
        algorithm="delta",
        concurrency=2,
        max_trials=10,
        timed_out=lambda: False,
        evaluate=MagicMock(),
        record_result=MagicMock(),
        run_batch=MagicMock(),
        anchor_conf={"gatk_options": {"min_mapping_quality_score": 21}},
    )

    assert captured["delta_rounds"] == 4
    assert captured["max_trials"] == 10
