from app.schemas import CandidatePreview
from app.services.auto_mode import (
    AUTO_SCORE_WEIGHT,
    AUTO_SIMILARITY_WEIGHT,
    composite_candidate_score,
    select_top_candidates,
)


def test_composite_candidate_score():
    candidate = CandidatePreview(
        index=0,
        base_conf={},
        rank_score=0.5,
        history_score=0.8,
        similarity=0.5,
    )
    expected = AUTO_SCORE_WEIGHT * 0.8 + AUTO_SIMILARITY_WEIGHT * 0.5
    assert composite_candidate_score(candidate) == expected


def test_select_top_candidates_prefers_similarity_weight():
    candidates = [
        CandidatePreview(
            index=0,
            base_conf={"a": 1},
            rank_score=0.9,
            history_score=0.9,
            similarity=0.1,
        ),
        CandidatePreview(
            index=1,
            base_conf={"b": 2},
            rank_score=0.5,
            history_score=0.5,
            similarity=0.9,
        ),
        CandidatePreview(
            index=2,
            base_conf={"c": 3},
            rank_score=0.7,
            history_score=0.7,
            similarity=0.7,
        ),
    ]
    selected = select_top_candidates(candidates, 2)
    assert len(selected) == 2
    assert selected[0].index == 1
    assert selected[1].index in {0, 2}
