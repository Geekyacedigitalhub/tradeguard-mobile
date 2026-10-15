"""Combined read-only cTrader demo account overview.

Combines broker-reconciled account state with bounded UTC-day realized P/L.
This is display-only: it does not persist risk metrics or approve execution.
"""
from fastapi import APIRouter, Depends

from .auth import current_user
from .ctrader_oauth_api import ctrader_account_snapshot
from .ctrader_selected_realized_pl import selected_account_realized_pl

router = APIRouter(prefix="/v1/ctrader", tags=["ctrader"])


@router.get("/account/overview")
async def account_overview(user=Depends(current_user)):
    snapshot = await ctrader_account_snapshot(user)
    overview = {
        **snapshot,
        "today_pl": None,
        "realized_daily_pl": None,
        "realized_daily_pl_status": "unavailable",
        "realized_daily_pl_source": None,
        "risk_metrics_verified": False,
        "risk_metrics_status": "daily_drawdown_and_persistent_risk_verification_unavailable",
    }
    try:
        realized = await selected_account_realized_pl(str(user["id"]))
        overview["realized_daily_pl"] = realized.get("realized_net_pnl")
        overview["realized_daily_pl_status"] = realized.get("status", "unavailable")
        overview["realized_daily_pl_source"] = realized.get("source")
        # Only expose today_pl when complete history and net P/L are both present.
        if realized.get("history_complete") is True and realized.get("realized_net_pnl") is not None:
            overview["today_pl"] = realized["realized_net_pnl"]
    except Exception:
        # Account positions/balance remain displayable, but missing history must
        # never be represented as zero P/L or as verified risk metrics.
        overview["realized_daily_pl_status"] = "unavailable"
    overview["risk_metrics_verified"] = False
    overview["risk_metrics_status"] = "daily_drawdown_and_persistent_risk_verification_unavailable"
    return overview
