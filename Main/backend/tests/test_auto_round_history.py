from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.schemas import AutoDispatchAssignment, WorkerBestScoreResponse
from app.services.auto_mode import AutoSession, AutoModeStore
from app.services.auto_round_history import record_auto_round_if_needed


def test_record_auto_round_persists_per_worker_results():
    import asyncio

    store = AutoModeStore()
    started_at = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store.session = AutoSession(
        region="chr21:1-100",
        tool="gatk",
        started_at=started_at,
        assignments=[
            AutoDispatchAssignment(
                worker_id="w1",
                worker_name="VM",
                algorithm="optuna",
                candidate_index=0,
                composite_score=0.5,
                window="chr21:1-100",
                dispatch_ok=True,
            ),
            AutoDispatchAssignment(
                worker_id="w2",
                worker_name="Big",
                algorithm="gp",
                candidate_index=1,
                composite_score=0.4,
                window="chr21:1-100",
                dispatch_ok=True,
            ),
        ],
        running=False,
    )

    async def fake_fetch(_db, worker_id: str):
        scores = {
            "w1": WorkerBestScoreResponse(
                worker_id="w1",
                ok=True,
                best_score=0.82,
                best_conf={"threads": 4},
                trials_evaluated=12,
            ),
            "w2": WorkerBestScoreResponse(
                worker_id="w2",
                ok=True,
                best_score=0.91,
                best_conf={"threads": 6},
                trials_evaluated=20,
            ),
        }
        return scores[worker_id]

    async def _run():
        from unittest.mock import MagicMock

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with (
            patch("app.services.auto_mode.auto_mode_store", store),
            patch("app.services.auto_round_history.fetch_worker_best", side_effect=fake_fetch),
        ):
            row = await record_auto_round_if_needed(db, end_reason="best_export")
            assert row is not None
            assert row.winner_worker_name == "Big"
            assert row.winner_score == 0.91
            assert len(row.worker_results) == 2
            assert store.session is not None
            assert store.session.round_recorded is True
            db.add.assert_called_once()
            db.commit.assert_awaited_once()

    asyncio.run(_run())


def test_record_auto_round_skips_when_already_recorded():
    import asyncio

    store = AutoModeStore()
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
                dispatch_ok=True,
            )
        ],
        running=False,
        round_recorded=True,
    )

    async def _run():
        db = AsyncMock()
        with patch("app.services.auto_mode.auto_mode_store", store):
            row = await record_auto_round_if_needed(db, end_reason="restart")
            assert row is None
            db.add.assert_not_called()

    asyncio.run(_run())
