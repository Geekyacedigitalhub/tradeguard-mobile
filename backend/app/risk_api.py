import math

from fastapi import HTTPException
from .risk import RiskContext, RiskLimits, validate_signal


def scale_risk_envelope_for_multiplier(risk_per_trade: float, daily_loss_limit: float, max_drawdown: float, multiplier: float) -> tuple:
    """Scale the configured risk envelope by the bot's risk multiplier.

    Per-trade risk AND the daily/drawdown budgets scale by the same factor
    (capped at 100% of account value) so the "one trade must fit the daily
    budget" invariant keeps holding at the x100 profile instead of rejecting
    every aggressive trade. Raises when the scaled per-trade risk would
    exceed the scaled daily budget (fail closed, never silently re-size).
    """
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
        raise ValueError("risk multiplier must be a positive finite number")
    m = float(multiplier)
    if not math.isfinite(m) or m <= 0:
        raise ValueError("risk multiplier must be a positive finite number")
    risk = float(risk_per_trade) * m
    daily = min(float(daily_loss_limit) * m, 100.0)
    drawdown = min(float(max_drawdown) * m, 100.0)
    if not (math.isfinite(risk) and risk > 0):
        raise ValueError("scaled risk per trade is invalid")
    if risk > daily:
        raise ValueError("scaled risk per trade exceeds the scaled daily loss limit")
    return risk, daily, drawdown

def approve_trade(signal: dict, balance: float = 1000.0, equity: float = 1000.0,
                  today_pnl_percent: float = 0.0, drawdown_percent: float = 0.0,
                  open_trades: int = 0, consecutive_losses: int = 0,
                  risk_per_trade: float = 0.5, daily_loss_limit: float = 2.0,
                  max_open_trades: int = 3, max_drawdown: float = 5.0):
    decision = validate_signal(
        signal,
        RiskContext(balance, equity, today_pnl_percent, drawdown_percent, open_trades, consecutive_losses),
        RiskLimits(risk_per_trade, daily_loss_limit, max_open_trades, max_drawdown),
    )
    if not decision.approved:
        return {"approved": False, "reason": decision.reason, "risk_amount": 0, "quantity": None}
    return {"approved": True, "reason": decision.reason, "risk_amount": decision.risk_amount, "quantity": decision.quantity}
