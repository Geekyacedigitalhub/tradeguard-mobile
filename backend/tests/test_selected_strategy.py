import unittest

from app.strategy import Candle, analyze_selected_strategy


def declining_candles(count=40):
    candles = []
    price = 100.0
    for i in range(count):
        close = price - 0.5
        candles.append(Candle(open=price, high=price + 0.2, low=close - 0.2, close=close, time=i))
        price = close
    return candles


class SelectedStrategyTests(unittest.TestCase):
    def test_breakout_strategy_only_emits_after_close_breaks_resistance(self):
        candles = [
            Candle(open=100.0, high=101.0, low=99.0, close=100.0, time=i)
            for i in range(40)
        ]
        candles[-1] = Candle(open=100.0, high=103.5, low=99.8, close=103.0, time=40)
        result = analyze_selected_strategy(candles, candles, candles, "breakout")
        self.assertEqual(result["signal"], "BUY")
        self.assertEqual(result["strategy"], "breakout")
        self.assertLess(result["stop_loss"], result["entry"])
        self.assertLess(result["entry"], result["take_profit"])

    def test_reversal_strategy_requires_extreme_rsi_and_confirming_candle(self):
        candles = declining_candles()
        candles[-1] = Candle(open=80.0, high=80.2, low=74.0, close=81.0, time=41)
        result = analyze_selected_strategy(candles, candles, candles, "reversal")
        self.assertEqual(result["signal"], "BUY")
        self.assertEqual(result["strategy"], "reversal")
        self.assertLess(result["stop_loss"], result["entry"])
        self.assertLess(result["entry"], result["take_profit"])

    def test_unknown_strategy_fails_closed(self):
        candles = declining_candles()
        result = analyze_selected_strategy(candles, candles, candles, "not-a-strategy")
        self.assertEqual(result["signal"], "NO TRADE")
        self.assertIn("Unknown strategy", result["reason"])

    def test_short_history_does_not_generate_selected_strategy_entry(self):
        candles = declining_candles(10)
        result = analyze_selected_strategy(candles, candles, candles, "breakout")
        self.assertEqual(result["signal"], "NO TRADE")


if __name__ == "__main__":
    unittest.main()
