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
        "realized_daily_pl_window_start": None,
        "realized_daily_pl_as_of": None,
        "realized_daily_pl_history_complete": False,
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
            history_complete = realized.get("history_complete") is True
            valid_metadata = (
                realized.get("source") == "ctrader_close_deal_history"
                and isinstance(realized.get("window_start"), str)
                and bool(realized.get("window_start").strip())
                and isinstance(realized.get("as_of"), str)
                and bool(realized.get("as_of").strip())
                and realized.get("status") == "broker_close_deal_components_summed"
            )
            overview["realized_daily_pl_status"] = realized.get("status", "unavailable")
            overview["realized_daily_pl_history_complete"] = history_complete
            if valid_net_pnl and history_complete and valid_metadata:
                overview["realized_daily_pl"] = float(net_pnl)
                overview["realized_daily_pl_source"] = realized.get("source")
                overview["realized_daily_pl_window_start"] = realized.get("window_start")
                overview["realized_daily_pl_as_of"] = realized.get("as_of")
                # Only expose today_pl when complete history and net P/L are present.
                overview["today_pl"] = float(net_pnl)
            else:
                # Require the expected broker-history source and explicit window
                # metadata as well as complete pagination and a finite net P/L.
                # Otherwise leave the metric and its provenance unavailable.
                overview["realized_daily_pl_status"] = (
                    "net_pnl_unavailable_or_invalid"
                    if not valid_net_pnl or not history_complete
                    else "realized_pl_metadata_incomplete_or_invalid"
                )
                overview["realized_daily_pl_history_complete"] = False
    except Exception:
        # Account positions/balance remain displayable, but missing history must
        # never be represented as zero P/L or as verified risk metrics.
        overview["realized_daily_pl_status"] = "unavailable"
    overview["risk_metrics_verified"] = False
    overview["risk_metrics_status"] = "daily_drawdown_and_persistent_risk_verification_unavailable"
    return overview
