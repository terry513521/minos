from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import FindCandidatesRequest, FindCandidatesResponse
from app.services.candidate_finder import find_candidates

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.post("/find", response_model=FindCandidatesResponse)
async def find_base_candidates(
    body: FindCandidatesRequest,
    db: AsyncSession = Depends(get_db),
) -> FindCandidatesResponse:
    try:
        return await find_candidates(
            db,
            window=body.window,
            tool=body.tool,
            k_candidates=body.k_candidates,
            min_similarity=body.min_similarity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
