from app.risk_api import approve_trade


def test_risk_approval_never_claims_broker_volume_is_verified():
    result = approve_trade(
        {"signal": "BUY", "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0},
        balance=1000.0,
        equity=1000.0,
    )

    assert result["approved"] is True
    assert result["risk_amount"] == 5.0
    assert result["broker_volume_verified"] is False
    assert result["broker_volume"] is None
    assert result["execution_ready"] is False


def test_rejected_risk_decision_is_not_execution_ready():
    result = approve_trade(
        {"signal": "BUY", "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0},
        balance=1000.0,
        equity=1000.0,
        today_pnl_percent=-2.0,
    )

    assert result["approved"] is False
    assert result["risk_amount"] == 0
    assert result["broker_volume_verified"] is False
    assert result["broker_volume"] is None
    assert result["execution_ready"] is False
