from app.schemas import AutoDispatchAssignment, CandidatePreview
from app.services.auto_mode import (
    AUTO_SCORE_WEIGHT,
    AUTO_SIMILARITY_WEIGHT,
    AutoModeStore,
    AutoSession,
    composite_candidate_score,
    select_top_candidates,
)
from datetime import datetime, timezone


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


def test_disable_auto_mode_keeps_session_running():
    store = AutoModeStore()
    store.enabled = True
    store.session = AutoSession(
        region="chr21:1-100",
        tool="gatk",
        started_at=datetime.now(timezone.utc),
        assignments=[
            AutoDispatchAssignment(
                worker_id="w1",
                worker_name="VM",
                algorithm="optuna",
                candidate_index=0,
                composite_score=0.5,
            )
        ],
        running=True,
    )

    status = store.set_enabled(False)

    assert status.enabled is False
    assert status.running is True
    assert store.session is not None
    assert store.session.running is True
    assert len(status.assignments) == 1
