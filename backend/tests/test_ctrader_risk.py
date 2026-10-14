import unittest

from app.ctrader_risk import calculate_verified_volume


class CTraderRiskSizingTests(unittest.TestCase):
    def valid_inputs(self):
        return {
            "risk_amount": 100.0,
            "stop_distance": 2.0,
            "account_currency_loss_per_price_unit_per_lot": 10.0,
            "lot_size": 100000,
            "min_volume": 100,
            "max_volume": 100000000,
            "step_volume": 100,
        }

    def test_calculates_volume_rounding_down_to_broker_step(self):
        result = calculate_verified_volume(**self.valid_inputs())
        self.assertEqual(result["broker_volume"] % 100, 0)
        self.assertLessEqual(result["estimated_loss_at_stop"], 100.0)
        self.assertTrue(result["broker_volume_verified"])

    def test_rejects_missing_or_nonpositive_risk_inputs(self):
        for field in ("risk_amount", "stop_distance", "account_currency_loss_per_price_unit_per_lot"):
            inputs = self.valid_inputs()
            inputs[field] = 0
            with self.subTest(field=field), self.assertRaises(ValueError):
                calculate_verified_volume(**inputs)

    def test_rejects_invalid_broker_metadata(self):
        inputs = self.valid_inputs()
        inputs["step_volume"] = 0
        with self.assertRaises(ValueError):
            calculate_verified_volume(**inputs)

    def test_rejects_when_risk_is_below_minimum_volume(self):
        inputs = self.valid_inputs()
        inputs["risk_amount"] = 0.00001
        with self.assertRaises(ValueError):
            calculate_verified_volume(**inputs)


    def test_volume_respects_minimum_offset_step(self):
        inputs = self.valid_inputs()
        inputs.update(
            risk_amount=0.0005,
            min_volume=150,
            max_volume=1000,
            step_volume=100,
        )
        result = calculate_verified_volume(**inputs)
        self.assertEqual(result["broker_volume"], 250)
        self.assertEqual((result["broker_volume"] - inputs["min_volume"]) % inputs["step_volume"], 0)

    def test_rejects_non_finite_risk_inputs(self):
        for value in (float("inf"), float("nan"), float("-inf")):
            inputs = self.valid_inputs()
            inputs["account_currency_loss_per_price_unit_per_lot"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate_verified_volume(**inputs)


    def test_conversion_rate_uses_bid_forward_and_ask_in_reverse(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        symbols = [
            {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 11, "base_asset_id": 3, "quote_asset_id": 2},
        ]
        quotes = {
            10: {"bid": 2.0, "ask": 2.1, "timestamp": 1000},
            11: {"bid": 1.4, "ask": 1.5, "timestamp": 1000},
        }
        rate = calculate_fresh_conversion_rate(
            first_asset_id=1,
            last_asset_id=3,
            conversion_symbols=symbols,
            quotes_by_symbol_id=quotes,
            now_epoch_seconds=1005,
        )
        self.assertAlmostEqual(rate, 2.0 / 1.5)


    def test_conversion_rate_accepts_cTrader_millisecond_timestamps(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        rate = calculate_fresh_conversion_rate(
            first_asset_id=1,
            last_asset_id=2,
            conversion_symbols=[
                {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2}
            ],
            quotes_by_symbol_id={
                10: {"bid": 2.0, "ask": 2.1, "timestamp": 1_700_000_000_000}
            },
            now_epoch_seconds=1_700_000_000,
        )
        self.assertAlmostEqual(rate, 2.0)

    def test_conversion_rate_rejects_stale_quotes(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        with self.assertRaisesRegex(ValueError, "stale or from the future"):
            calculate_fresh_conversion_rate(
                first_asset_id=1,
                last_asset_id=2,
                conversion_symbols=[
                    {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2}
                ],
                quotes_by_symbol_id={
                    10: {"bid": 2.0, "ask": 2.1, "timestamp": 900}
                },
                now_epoch_seconds=1000,
                max_quote_age_seconds=15,
            )

    def test_conversion_rate_rejects_missing_or_ambiguous_chain(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        args = {
            "first_asset_id": 1,
            "last_asset_id": 3,
            "conversion_symbols": [
                {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2},
                {"symbol_id": 11, "base_asset_id": 1, "quote_asset_id": 4},
            ],
            "quotes_by_symbol_id": {
                10: {"bid": 2.0, "ask": 2.1, "timestamp": 1000},
                11: {"bid": 3.0, "ask": 3.1, "timestamp": 1000},
            },
            "now_epoch_seconds": 1000,
        }
        with self.assertRaisesRegex(ValueError, "disconnected or ambiguous"):
            calculate_fresh_conversion_rate(**args)

    def test_conversion_rate_rejects_invalid_bid_ask(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        with self.assertRaisesRegex(ValueError, "crossed bid/ask"):
            calculate_fresh_conversion_rate(
                first_asset_id=1,
                last_asset_id=2,
                conversion_symbols=[
                    {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2}
                ],
                quotes_by_symbol_id={
                    10: {"bid": 2.1, "ask": 2.0, "timestamp": 1000}
                },
                now_epoch_seconds=1000,
            )

    def test_never_rounds_up_above_risk_cap(self):
        inputs = self.valid_inputs()
        inputs["risk_amount"] = 101.0
        result = calculate_verified_volume(**inputs)
        self.assertLessEqual(result["estimated_loss_at_stop"], inputs["risk_amount"])



    def test_caps_volume_to_highest_valid_step_below_broker_maximum(self):
        inputs = self.valid_inputs()
        inputs.update(
            risk_amount=100000.0,
            min_volume=150,
            max_volume=1580,
            step_volume=100,
        )
        result = calculate_verified_volume(**inputs)
        self.assertEqual(result["broker_volume"], 1550)
        self.assertLessEqual(result["broker_volume"], inputs["max_volume"])
        self.assertEqual(
            (result["broker_volume"] - inputs["min_volume"]) % inputs["step_volume"],
            0,
        )
        self.assertLessEqual(result["estimated_loss_at_stop"], inputs["risk_amount"])


    def test_conversion_rate_rejects_future_quote_outside_tolerance(self):
        from app.ctrader_risk import calculate_fresh_conversion_rate

        with self.assertRaisesRegex(ValueError, "stale or from the future"):
            calculate_fresh_conversion_rate(
                first_asset_id=1,
                last_asset_id=2,
                conversion_symbols=[
                    {"symbol_id": 10, "base_asset_id": 1, "quote_asset_id": 2}
                ],
                quotes_by_symbol_id={
                    10: {"bid": 2.0, "ask": 2.1, "timestamp": 1006}
                },
                now_epoch_seconds=1000,
                max_quote_age_seconds=15,
            )


if __name__ == "__main__":
    unittest.main()
