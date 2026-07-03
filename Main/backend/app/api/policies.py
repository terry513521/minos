from fastapi import APIRouter

from app.schemas import OptimizerPolicy, SearchBudget

router = APIRouter(prefix="/policies", tags=["policies"])

_DEFAULT_GATK_POLICY = OptimizerPolicy(
    tool="gatk",
    important_params=[
        "pcr_indel_model",
        "standard_min_confidence_threshold_for_calling",
        "min_base_quality_score",
        "min_mapping_quality_score",
    ],
    search_method="optuna",
    search_budget=SearchBudget(max_trials=12, timeout_seconds=3600),
    param_bounds={
        "pcr_indel_model": {"allowed": ["NONE", "CONSERVATIVE"]},
        "standard_min_confidence_threshold_for_calling": {"min": 20, "max": 40, "step": 2.5},
        "min_base_quality_score": {"min": 8, "max": 18, "step": 2},
        "min_mapping_quality_score": {"min": 15, "max": 30, "step": 5},
    },
)

_POLICIES: dict[str, OptimizerPolicy] = {"gatk": _DEFAULT_GATK_POLICY}


@router.get("/{tool}", response_model=OptimizerPolicy)
async def get_policy(tool: str) -> OptimizerPolicy:
    policy = _POLICIES.get(tool.lower())
    if policy is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"No policy for tool: {tool}")
    return policy


@router.put("/{tool}", response_model=OptimizerPolicy)
async def update_policy(tool: str, policy: OptimizerPolicy) -> OptimizerPolicy:
    _POLICIES[tool.lower()] = policy
    return policy
