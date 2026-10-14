"""Regression tests for TradeGuard's selected indicator calculations.

These tests validate deterministic calculation contracts only; they do not
claim profitability or authorize live execution.
"""
import math

from app.strategy import Candle
from app.technical_engine import (
    adx,
    chandelier_exit,
    selected_indicator_evidence,
    supertrend,
    wavetrend,
)


def candles(count=100, slope=0.25):
    result = []
    previous = 100.0
    for i in range(count):
        close = 100.0 + slope * i + math.sin(i / 3.0) * 0.4
        open_price = previous
        result.append(
            Candle(
                open=open_price,
                high=max(open_price, close) + 0.35,
                low=min(open_price, close) - 0.35,
                close=close,
                volume=1000.0,
                time=i,
            )
        )
        previous = close
    return result


def test_supertrend_returns_valid_direction_and_band():
    result = supertrend(candles())
    assert result["direction"] in {"BULLISH", "BEARISH"}
    assert isinstance(result["value"], float)
    assert result["upper"] >= result["lower"]


def test_supertrend_fails_closed_when_history_is_short():
    result = supertrend(candles(5))
    assert result["direction"] == "UNKNOWN"
    assert result["value"] is None


def test_chandelier_exit_returns_finite_levels():
    result = chandelier_exit(candles())
    assert result["long"] is not None
    assert result["short"] is not None
    assert math.isfinite(result["long"])
    assert math.isfinite(result["short"])
    assert result["atr"] > 0


def test_wavetrend_returns_oscillator_and_cross_contract():
    result = wavetrend(candles())
    assert isinstance(result["wt1"], float)
    assert isinstance(result["wt2"], float)
    assert result["direction"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert result["cross"] in {"BULLISH", "BEARISH", "NONE"}


def test_wavetrend_marks_short_history_unknown():
    result = wavetrend(candles(10))
    assert result["direction"] == "UNKNOWN"
    assert result["wt1"] is None


def test_selected_evidence_includes_all_five_indicators():
    result = selected_indicator_evidence(candles())
    assert result["status"] == "OK"
    assert set(result) == {
        "status", "supertrend", "macd", "adx_di",
        "chandelier_exit", "wavetrend",
    }
    assert result["macd"]["direction"] in {"BULLISH", "BEARISH", "MIXED"}
    assert result["adx_di"]["regime"] in {
        "TRENDING", "RANGING_OR_WEAK", "TRANSITION"
    }


def test_selected_evidence_marks_insufficient_history():
    result = selected_indicator_evidence(candles(30))
    assert result["status"] == "INSUFFICIENT"
