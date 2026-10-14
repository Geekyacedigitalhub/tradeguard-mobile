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

    # Passing strategy/risk checks is not the same as being safe to execute.
    # Broker volume stays explicitly unverified until cTrader symbol constraints
    # and stop-loss risk in the account's deposit currency have been calculated.
    return {
        "approved": bool(decision.approved),
        "reason": decision.reason,
        "risk_amount": round(float(decision.risk_amount), 2) if decision.approved else 0,
        "quantity": decision.quantity if decision.approved else None,
        "broker_volume_verified": False,
        "broker_volume": None,
        "execution_ready": False,
    }
