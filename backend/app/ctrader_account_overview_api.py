"""Combined read-only cTrader demo account overview.

Combines broker-reconciled account state with bounded UTC-day realized P/L.
This is display-only: it does not persist risk metrics or approve execution.
"""
import math
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
        if realized.get("environment") != "demo" or realized.get("account_id") != snapshot.get("account_id"):
            overview["realized_daily_pl_status"] = "selected_account_changed_during_request"
        else:
            net_pnl = realized.get("realized_net_pnl")
            valid_net_pnl = (
                isinstance(net_pnl, (int, float))
                and not isinstance(net_pnl, bool)
                and math.isfinite(float(net_pnl))
            )
            overview["realized_daily_pl_status"] = realized.get("status", "unavailable")
            overview["realized_daily_pl_source"] = realized.get("source")
            if valid_net_pnl and realized.get("history_complete") is True:
                overview["realized_daily_pl"] = float(net_pnl)
                # Only expose today_pl when complete history and net P/L are present.
                overview["today_pl"] = float(net_pnl)
            else:
                overview["realized_daily_pl_status"] = "net_pnl_unavailable_or_invalid"
    except Exception:
        # Account positions/balance remain displayable, but missing history must
        # never be represented as zero P/L or as verified risk metrics.
        overview["realized_daily_pl_status"] = "unavailable"
    overview["risk_metrics_verified"] = False
    overview["risk_metrics_status"] = "daily_drawdown_and_persistent_risk_verification_unavailable"
    return overview
