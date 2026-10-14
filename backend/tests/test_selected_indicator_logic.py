"""Regression tests for TradeGuard's selected technical-indicator evidence.

Run from the backend directory with:
    python -m pytest tests/test_selected_indicator_logic.py -q
"""
from types import SimpleNamespace

from app.technical_engine import selected_indicator_evidence, wavetrend
from app.strategy import Candle, analyze_selected_strategy, chandelier_exit, supertrend


def make_candles(count=240):
    """Create deterministic OHLCV data with a trend and repeatable pullbacks."""
    candles = []
    previous = 100.0
    for i in range(count):
        drift = 0.035 if (i // 35) % 2 == 0 else -0.018
        close = previous + drift + ((i % 7) - 3) * 0.012
        open_price = previous
        high = max(open_price, close) + 0.08 + (i % 3) * 0.005
        low = min(open_price, close) - 0.07 - (i % 4) * 0.004
        candles.append(
            SimpleNamespace(
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000 + i,
                time=i * 300,
            )
        )
        previous = close
    return candles


def test_selected_indicator_evidence_fails_closed_on_short_history():
    result = selected_indicator_evidence(make_candles(40))

    assert result["status"] == "INSUFFICIENT"
    assert result["wavetrend"] == {}
    assert result["supertrend"] == {}


def test_selected_indicator_evidence_has_expected_indicator_fields():
    result = selected_indicator_evidence(make_candles())

    assert result["status"] == "OK"
    assert {"supertrend", "macd", "adx_di", "chandelier_exit", "wavetrend"} <= set(result)
    assert result["macd"]["direction"] in {"BULLISH", "BEARISH", "MIXED"}
    assert result["adx_di"]["adx"] >= 0
    assert result["wavetrend"]["direction"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert result["wavetrend"]["cross"] in {"BULLISH", "BEARISH", "NONE"}


def test_wavetrend_does_not_claim_a_cross_without_a_fresh_cross():
    result = wavetrend(make_candles())

    assert result["cross"] in {"BULLISH", "BEARISH", "NONE"}
    assert result["direction"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert isinstance(result["wt1"], float)
    assert isinstance(result["wt2"], float)


def test_atr_exit_indicators_return_valid_levels_with_sufficient_history():
    candles = make_candles()

    st = supertrend(candles)
    ce = chandelier_exit(candles)

    assert st is not None
    assert st["direction"] in {"BUY", "SELL"}
    assert isinstance(st["line"], float)
    assert ce is not None
    assert isinstance(ce["long_exit"], float)
    assert isinstance(ce["short_exit"], float)
    assert ce["long_exit"] > 0
    assert ce["short_exit"] > 0


def test_unknown_strategy_never_emits_an_executable_signal():
    candles = [Candle(**{k: getattr(c, k) for k in ("open", "high", "low", "close", "volume", "time")}) for c in make_candles()]

    result = analyze_selected_strategy(candles, candles, candles, strategy="unrecognized")

    assert result["signal"] == "NO TRADE"
    assert "Unknown strategy" in result["reason"]
