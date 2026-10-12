import math
import pytest

from app.ctrader_protection_validation import validate_protection_request


@pytest.mark.parametrize("position_id", [0, -1, True, False, 1.5, "12", None])
def test_rejects_invalid_position_id(position_id):
    with pytest.raises(ValueError):
        validate_protection_request(position_id, stop_loss=1.2)


@pytest.mark.parametrize("value", [0, -1, True, False, float("nan"), float("inf"), -float("inf"), "1.2", object()])
def test_rejects_invalid_stop_loss(value):
    with pytest.raises(ValueError):
        validate_protection_request(12, stop_loss=value)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), "1.2"])
def test_rejects_invalid_take_profit(value):
    with pytest.raises(ValueError):
        validate_protection_request(12, take_profit=value)


def test_requires_at_least_one_protection_price():
    with pytest.raises(ValueError):
        validate_protection_request(12)


def test_accepts_stop_loss_only():
    assert validate_protection_request(12, stop_loss=1.234) == (12, 1.234, None)


def test_accepts_take_profit_only():
    assert validate_protection_request(12, take_profit=2) == (12, None, 2.0)


def test_accepts_both_prices():
    assert validate_protection_request(12, stop_loss=1.1, take_profit=1.3) == (12, 1.1, 1.3)
