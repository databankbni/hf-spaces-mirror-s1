from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.case import CaseResponse
from app.policies.rules import MerchantPolicy
from app.agents.recovery_agent import run_recovery_investigation

router = APIRouter(tags=["Agent & Policies"])

# Shared in-memory policy state for merchant operations
active_policy = MerchantPolicy()

@router.post("/cases/{case_id}/investigate", response_model=CaseResponse)
async def investigate_case_endpoint(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        updated_case = await run_recovery_investigation(
            case_id=case_id,
            db=db,
            policy=active_policy,
        )
        return updated_case
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Investigation failed: {str(e)}")

@router.get("/policies", response_model=MerchantPolicy)
async def get_merchant_policy():
    return active_policy

@router.put("/policies", response_model=MerchantPolicy)
async def update_merchant_policy(payload: MerchantPolicy):
    global active_policy
    active_policy = payload
    return active_policy
