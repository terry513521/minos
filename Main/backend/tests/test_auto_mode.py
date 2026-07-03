from datetime import datetime, timezone

from app.schemas import AutoDispatchAssignment, CandidatePreview
from app.services.auto_mode import (
    AUTO_ALGORITHM,
    AUTO_SCORE_WEIGHT,
    AUTO_SIMILARITY_WEIGHT,
    AutoModeStore,
    AutoSession,
    assign_workers_by_metric,
    build_diverse_candidate_pool,
    candidate_dispatch_window,
    composite_candidate_score,
)


def test_candidate_dispatch_window_prefers_source_window():
    candidate = CandidatePreview(
        index=0,
        base_conf={},
        rank_score=0.5,
        source_window="chr21:35444092-40444092",
    )
    assert (
        candidate_dispatch_window(candidate, "chr21:1000000-6000000")
        == "chr21:35444092-40444092"
    )


def test_candidate_dispatch_window_falls_back_to_query_region():
    candidate = CandidatePreview(index=0, base_conf={}, rank_score=0.5)
    assert candidate_dispatch_window(candidate, "chr21:1000000-6000000") == "chr21:1000000-6000000"


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


def test_build_diverse_candidate_pool_prioritizes_score_similarity_composite():
    pool = [
        CandidatePreview(
            index=0,
            base_conf={"a": 1},
            rank_score=0.95,
            history_score=0.95,
            similarity=0.2,
            history_id="high-score",
        ),
        CandidatePreview(
            index=1,
            base_conf={"b": 2},
            rank_score=0.5,
            history_score=0.5,
            similarity=0.99,
            history_id="high-sim",
        ),
        CandidatePreview(
            index=2,
            base_conf={"c": 3},
            rank_score=0.7,
            history_score=0.7,
            similarity=0.7,
            history_id="balanced",
        ),
    ]
    diverse = build_diverse_candidate_pool(pool, 6)
    identities = [c.history_id for c in diverse[:3]]
    assert identities[0] == "high-score"
    assert identities[1] == "high-sim"
    assert identities[2] == "balanced"


def test_assign_workers_by_metric_maps_vm_big_igno():
    candidates = [
        CandidatePreview(
            index=0,
            base_conf={"a": 1},
            rank_score=0.95,
            history_score=0.95,
            similarity=0.2,
            history_id="high-score",
        ),
        CandidatePreview(
            index=1,
            base_conf={"b": 2},
            rank_score=0.5,
            history_score=0.5,
            similarity=0.99,
            history_id="high-sim",
        ),
        CandidatePreview(
            index=2,
            base_conf={"c": 3},
            rank_score=0.7,
            history_score=0.7,
            similarity=0.7,
            history_id="balanced",
        ),
    ]
    slots = assign_workers_by_metric(candidates)
    assert [slot.worker_name for slot in slots] == ["VM", "Big", "Igno"]
    assert slots[0].selection_reason == "top_score"
    assert slots[0].candidate.history_id == "high-score"
    assert slots[1].selection_reason == "most_similar"
    assert slots[1].candidate.history_id == "high-sim"
    assert slots[2].selection_reason == "best_composite"


def test_auto_dispatch_uses_fixed_algorithm():
    from app.services.auto_mode import build_dispatch_request, with_trial_resources

    body = build_dispatch_request(
        window="chr21:1-100",
        tool="gatk",
        base_conf={"gatk_options": {}},
        candidate_index=0,
    )
    assert body.algorithm == AUTO_ALGORITHM
    assert body.base_conf["threads"] == 4
    assert body.base_conf["memory_gb"] == 6

    merged = with_trial_resources({"gatk_options": {"x": 1}, "threads": 8})
    assert merged["threads"] == 4
    assert merged["memory_gb"] == 7


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


def test_finished_session_allows_new_start_check():
    store = AutoModeStore()
    store.enabled = True
    store.session = AutoSession(
        region="chr21:1-100",
        tool="gatk",
        started_at=datetime.now(timezone.utc),
        running=False,
    )
    status = store.status()
    assert status.running is False
    assert status.enabled is True


def test_auto_mode_status_includes_last_started_region():
    store = AutoModeStore()
    store.last_started_region = "chr21:35444092-40444092"
    assert store.status().last_started_region == "chr21:35444092-40444092"


def test_end_session_clears_running_session():
    store = AutoModeStore()
    store.enabled = True
    store.session = AutoSession(
        region="chr21:1-100",
        tool="gatk",
        started_at=datetime.now(timezone.utc),
        running=True,
    )
    store.last_started_region = "chr21:1-100"

    status = store.end_session()

    assert store.session is None
    assert store.last_started_region is None
    assert status.running is False
    assert status.assignments == []


def test_skipped_start_response_shape():
    from app.services.auto_mode import _skipped_start_response

    response = _skipped_start_response(
        region="chr21:1-100",
        tool="gatk",
        message="skipped",
    )
    assert response.skipped is True
    assert response.ok is False
    assert response.workers_dispatched == 0
