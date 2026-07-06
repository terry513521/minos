import json
from pathlib import Path

from app.services.portfolio_rounds import build_summary, flatten_portfolio_rows


def test_flatten_portfolio_rows_from_list():
    payload = [
        {
            "round_id": "2026-07-02T17:52:00+00:00",
            "region": "chr21:14558002-19558002",
            "leader_score": 92.0,
            "instances": {
                "gatk": {
                    "score_100": 88.5,
                    "combined_final": 0.885,
                    "rank": 3,
                    "gap_to_leader": -3.5,
                    "runtime_seconds": 120.5,
                    "f1_snp": 0.99,
                    "f1_indel": 0.91,
                    "score_breakdown": {
                        "components": [
                            {"id": "core", "contribution": 53.1},
                            {"id": "completeness", "contribution": 14.8},
                            {"id": "fp", "contribution": 12.0},
                            {"id": "quality", "contribution": 8.6},
                        ]
                    },
                }
            },
        }
    ]

    rows = flatten_portfolio_rows(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["round_id"] == "2026-07-02T17:52:00+00:00"
    assert row["chrom"] == "chr21"
    assert row["score_100"] == 88.5
    assert row["gap_to_leader"] == -3.5
    assert row["core"] == 53.1
    assert row["instance"] == "gatk"


def test_build_summary():
    rows = [
        {"round_id": "a", "chrom": "chr21", "instance": "gatk", "score_100": 80.0},
        {"round_id": "a", "chrom": "chr21", "instance": "newgatk", "score_100": 90.0},
        {"round_id": "b", "chrom": "chr20", "instance": "gatk", "score_100": 85.0},
    ]
    summary = build_summary(rows)
    assert summary["rounds"] == 2
    assert summary["rows"] == 3
    assert summary["chroms"] == ["chr20", "chr21"]
    assert summary["instances"] == ["gatk", "newgatk"]
    assert summary["best_score"] == 90.0
    assert summary["avg_score"] == 85.0


def test_flatten_repo_rounds_json_sample():
    path = Path(__file__).resolve().parents[3] / "rounds.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = flatten_portfolio_rows(payload)
    assert len(rows) > 100
    assert all(r["score_100"] > 0 for r in rows[:20])
