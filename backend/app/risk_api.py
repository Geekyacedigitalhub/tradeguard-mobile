from .risk import RiskContext, RiskLimits, validate_signal

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
