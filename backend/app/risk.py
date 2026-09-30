from dataclasses import dataclass
from typing import Optional

@dataclass
class RiskContext:
    balance: float
    equity: float
    today_pnl_percent: float
    drawdown_percent: float
    open_trades: int
    consecutive_losses: int = 0

@dataclass
class RiskLimits:
    risk_per_trade_percent: float = 0.5
    daily_loss_limit_percent: float = 2.0
    max_open_trades: int = 3
    max_drawdown_percent: float = 5.0
    max_consecutive_losses: int = 3

@dataclass
class RiskDecision:
    approved: bool
    reason: str
    risk_amount: float
    quantity: Optional[float]

def validate_signal(signal: dict, context: RiskContext, limits: RiskLimits) -> RiskDecision:
    if signal.get("signal") not in ("BUY", "SELL"):
        return RiskDecision(False, "Signal is not executable", 0, None)

    if context.balance <= 0 or context.equity <= 0:
        return RiskDecision(False, "Invalid account equity", 0, None)

    if limits.risk_per_trade_percent <= 0:
        return RiskDecision(False, "Risk per trade must be greater than zero", 0, None)

    if limits.risk_per_trade_percent > limits.daily_loss_limit_percent:
        return RiskDecision(False, "Risk per trade cannot exceed the daily loss limit", 0, None)

    if context.today_pnl_percent <= -limits.daily_loss_limit_percent:
        return RiskDecision(False, "Daily loss limit reached", 0, None)

    if context.drawdown_percent >= limits.max_drawdown_percent:
        return RiskDecision(False, "Maximum drawdown reached", 0, None)

    if context.open_trades >= limits.max_open_trades:
        return RiskDecision(False, "Maximum open trades reached", 0, None)

    if context.consecutive_losses >= limits.max_consecutive_losses:
        return RiskDecision(False, "Maximum consecutive losses reached", 0, None)

    entry = signal.get("entry")
    stop = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    if not entry or not stop or entry == stop:
        return RiskDecision(False, "Missing valid stop-loss", 0, None)
    if not take_profit or take_profit == entry:
        return RiskDecision(False, "Missing valid take-profit", 0, None)
    side = signal.get("signal")
    if side == "BUY" and not (stop < entry < take_profit):
        return RiskDecision(False, "Invalid BUY protection levels", 0, None)
    if side == "SELL" and not (take_profit < entry < stop):
        return RiskDecision(False, "Invalid SELL protection levels", 0, None)

    risk_amount = context.balance * (limits.risk_per_trade_percent / 100)
    stop_distance = abs(entry - stop)
    quantity = risk_amount / stop_distance

    if quantity <= 0:
        return RiskDecision(False, "Invalid position size", 0, None)

    return RiskDecision(
        True,
        "Risk checks passed",
        round(risk_amount, 2),
        round(quantity, 8),
    )
