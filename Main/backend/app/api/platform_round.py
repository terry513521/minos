from fastapi import APIRouter

from app.schemas import PlatformRoundResponse
from app.services.platform_round import poller

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/round", response_model=PlatformRoundResponse)
async def get_platform_round() -> PlatformRoundResponse:
    """Return cached platform round (polled in background). Fast — no upstream call."""
    return PlatformRoundResponse(**poller.snapshot.to_dict())


@router.post("/round/refresh", response_model=PlatformRoundResponse)
async def refresh_platform_round() -> PlatformRoundResponse:
    """Force an immediate poll of the Minos platform."""
    snap = await poller.poll_once()
    return PlatformRoundResponse(**snap.to_dict())
