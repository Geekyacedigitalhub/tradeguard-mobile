"""Read-only endpoint for selected demo-account realized P/L."""
from fastapi import APIRouter, Depends, HTTPException

from .auth import current_user
from .ctrader_selected_realized_pl import selected_account_realized_pl

router = APIRouter(prefix="/v1/ctrader", tags=["ctrader"])


@router.get("/account/realized-pl")
async def account_realized_pl(user=Depends(current_user)):
    try:
        return await selected_account_realized_pl(str(user["id"]))
    except RuntimeError as exc:
        message = str(exc)
        status = 409 if "Select a cTrader" in message else 503
        raise HTTPException(status, message) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            "cTrader realized P/L is temporarily unavailable. No risk approval or order is permitted.",
        ) from exc
