"""Compatibility with Main optimizer dispatch payloads."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.domain.state import BestSnapshot, best_store
from app.main import app
from app.optimization.optimizer import validate_optimize_request
from app.domain.schemas import OptimizeRequest


def _main_style_payload(**overrides) -> dict:
  """Same shape as Main/backend/app/api/workers.py dispatch proxy."""
  payload = {
      "job_id": "main-abc12345-deadbeef",
      "window": "chr21:35444092-40444092",
      "tool": "gatk",
      "concurrency": "4",
      "algorithm": "optuna",
      "limit": "1800",
      "base_conf": {
          "gatk_options": {
              "pcr_indel_model": "NONE",
              "standard_min_confidence_threshold_for_calling": 30.0,
              "min_mapping_quality_score": 20,
          }
      },
      "params": ["pcr_indel_model", "standard_min_confidence_threshold_for_calling"],
      "param_intervals": {
          "pcr_indel_model": {"values": ["NONE", "CONSERVATIVE"]},
          "standard_min_confidence_threshold_for_calling": {
              "min": 28.0,
              "max": 32.0,
              "step": 1.0,
          },
      },
  }
  payload.update(overrides)
  return payload


@pytest.fixture
def client():
    best_store._snapshot = BestSnapshot()
    return TestClient(app)


def test_main_payload_parses_to_optimize_request():
    req = OptimizeRequest.model_validate(_main_style_payload())
    assert req.concurrency == "4"
    assert req.limit == "1800"
    assert req.params[0] == "pcr_indel_model"


def _deepvariant_payload(**overrides) -> dict:
    payload = _main_style_payload(
        tool="deepvariant",
        base_conf={
            "deepvariant_options": {
                "model_type": "WGS",
                "min_mapping_quality": 5,
                "qual_filter": 1.0,
            }
        },
        params=["min_mapping_quality", "qual_filter"],
        param_intervals={
            "min_mapping_quality": {"min": 3, "max": 10, "step": 1},
            "qual_filter": {"min": 0.5, "max": 2.0, "step": 0.5},
        },
    )
    payload.update(overrides)
    return payload


def test_validate_accepts_deepvariant():
    req = OptimizeRequest.model_validate(_deepvariant_payload())
    size = validate_optimize_request(req)
    assert size > 0


def test_validate_rejects_unknown_algorithm():
    req = OptimizeRequest.model_validate(_main_style_payload(algorithm="bayesian"))
    with pytest.raises(ValueError, match="Unsupported algorithm"):
        validate_optimize_request(req)


def test_main_payload_accepts_adaptive_max_trials():
    req = OptimizeRequest.model_validate(_main_style_payload(adaptive_max_trials=50))
    assert req.adaptive_max_trials == 50


def test_main_payload_accepts_adaptive_max_trials_zero_for_conf_check():
    req = OptimizeRequest.model_validate(_main_style_payload(adaptive_max_trials=0))
    assert req.adaptive_max_trials == 0


@patch("app.api.routes.submit_optimize_job")
@patch("app.api.routes.validate_optimize_request", return_value=4)
def test_optimize_accepts_main_dispatch_shape(mock_validate, mock_submit, client):
    response = client.post("/optimize", json=_main_style_payload())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["search_space_size"] == 4
    assert body["job_id"] == "main-abc12345-deadbeef"
    mock_submit.assert_called_once()


@patch("app.api.routes.submit_optimize_job")
@patch("app.api.routes.validate_optimize_request", return_value=31)
@pytest.mark.parametrize("algorithm", ["gp", "sobol", "lhs"])
def test_optimize_accepts_gp_sobol_lhs(mock_validate, mock_submit, client, algorithm):
    response = client.post("/optimize", json=_main_style_payload(algorithm=algorithm))
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["algorithm"] == algorithm
    mock_submit.assert_called_once()


@patch("app.api.routes.submit_optimize_job")
@patch("app.api.routes.validate_optimize_request", return_value=4)
def test_optimize_accepts_deepvariant(mock_validate, mock_submit, client):
    response = client.post("/optimize", json=_deepvariant_payload())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["tool"] == "deepvariant"
    mock_submit.assert_called_once()


@patch("app.api.routes.submit_optimize_job")
@patch("app.api.routes.validate_optimize_request", return_value=2)
def test_best_idle_before_job(mock_validate, mock_submit, client):
    response = client.get("/best")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"
