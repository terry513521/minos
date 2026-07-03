import pytest

from app.optimization.algorithms import normalize_algorithm
from app.optimization.search_runners import run_adaptive_search


@pytest.mark.parametrize("algorithm", ["gp", "sobol", "lhs"])
def test_run_adaptive_search_dispatches_algorithm(algorithm: str, monkeypatch):
    calls: list[str] = []

    if algorithm == "gp":
        def fake_gp(**kwargs):
            calls.append("gp")

        monkeypatch.setattr("app.optimization.search_runners.run_gp_search", fake_gp)
    else:
        def fake_quasi(algo, **kwargs):
            calls.append(algo)

        monkeypatch.setattr("app.optimization.search_runners.run_quasi_random_search", fake_quasi)

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
        concurrency=1,
        max_trials=5,
        timed_out=lambda: True,
        evaluate=lambda conf: None,
        record_result=lambda result, label: None,
        run_batch=lambda **kwargs: None,
    )

    assert calls == [algorithm if algorithm != "gp" else "gp"]
    assert normalize_algorithm(algorithm) == algorithm
