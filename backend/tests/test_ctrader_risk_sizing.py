import unittest

from app.ctrader_risk_sizing import estimate_fx_stop_loss, size_fx_volume_for_risk


NOW = 1_800_000_000_000


class CTraderFxRiskSizingTests(unittest.TestCase):
    def test_estimates_stop_loss_directly_in_account_currency(self):
        result = estimate_fx_stop_loss(
            volume_raw=100_000,
            entry_price=1.10,
            stop_price=1.09,
            trade_side="BUY",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
        )
        self.assertAlmostEqual(result["estimated_loss_quote_currency"], 10.0)
        self.assertAlmostEqual(result["estimated_loss_account_currency"], 10.0)
        self.assertFalse(result["risk_sizing_verified"])

    def test_converts_quote_currency_loss_to_account_currency(self):
        symbols = [{
            "symbol_id": 7, "symbol_name": "EURUSD",
            "base_asset_id": 1, "quote_asset_id": 2,
        }]
        result = estimate_fx_stop_loss(
            volume_raw=100_000,
            entry_price=1.10,
            stop_price=1.09,
            trade_side="BUY",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=1,
            conversion_symbols=symbols,
            quotes_by_symbol_id={7: {"bid": 1.09, "ask": 1.10, "timestamp_ms": NOW}},
            now_timestamp_ms=NOW,
        )
        self.assertAlmostEqual(result["estimated_loss_quote_currency"], 10.0)
        self.assertAlmostEqual(result["estimated_loss_account_currency"], 10.0 / 1.10)
        self.assertTrue(result["conversion_verified"])

    def test_sizes_down_to_broker_step_without_exceeding_risk(self):
        result = size_fx_volume_for_risk(
            risk_budget_account_currency=10.0,
            entry_price=1.10,
            stop_price=1.09,
            trade_side="BUY",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
            min_volume=100,
            max_volume=1_000_000,
            step_volume=100,
        )
        self.assertEqual(result["volume_raw"], 100_000)
        self.assertLessEqual(result["estimated_loss_account_currency"], 10.0)
        self.assertFalse(result["risk_sizing_verified"])

    def test_aligns_volume_steps_from_nonzero_broker_minimum(self):
        result = size_fx_volume_for_risk(
            risk_budget_account_currency=0.024,
            entry_price=1.10,
            stop_price=1.09,
            trade_side="BUY",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
            min_volume=150,
            max_volume=1_000_000,
            step_volume=100,
        )
        self.assertEqual(result["volume_raw"], 150)
        self.assertLessEqual(result["estimated_loss_account_currency"], 0.024)

    def test_caps_volume_at_maximum_and_keeps_it_step_aligned(self):
        result = size_fx_volume_for_risk(
            risk_budget_account_currency=1000.0,
            entry_price=1.10,
            stop_price=1.09,
            trade_side="BUY",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
            min_volume=150,
            max_volume=550,
            step_volume=100,
        )
        self.assertEqual(result["volume_raw"], 550)
        self.assertEqual((result["volume_raw"] - 150) % 100, 0)

    def test_rejects_out_of_range_asset_identifiers_even_for_same_currency(self):
        with self.assertRaisesRegex(ValueError, "base_asset_id must be a valid positive protocol identifier"):
            estimate_fx_stop_loss(
                volume_raw=100, entry_price=1.10, stop_price=1.09,
                trade_side="BUY", base_asset_id=(1 << 63),
                quote_asset_id=2, account_asset_id=2,
                conversion_symbols=[], quotes_by_symbol_id={}, now_timestamp_ms=NOW,
            )
        with self.assertRaisesRegex(ValueError, "account_asset_id must be a valid positive protocol identifier"):
            estimate_fx_stop_loss(
                volume_raw=100, entry_price=1.10, stop_price=1.09,
                trade_side="BUY", base_asset_id=1,
                quote_asset_id=2, account_asset_id=(1 << 63),
                conversion_symbols=[], quotes_by_symbol_id={}, now_timestamp_ms=NOW,
            )

    def test_rejects_invalid_stop_price_and_volume_metadata(self):
        with self.assertRaisesRegex(ValueError, "stop price must differ"):
            estimate_fx_stop_loss(
                volume_raw=100, entry_price=1.10, stop_price=1.10, trade_side="BUY",
                base_asset_id=1, quote_asset_id=2, account_asset_id=2,
                conversion_symbols=[], quotes_by_symbol_id={}, now_timestamp_ms=NOW,
            )
        with self.assertRaisesRegex(ValueError, "maximum volume cannot be below minimum"):
            size_fx_volume_for_risk(
                risk_budget_account_currency=10.0,
                entry_price=1.10, stop_price=1.09,
                trade_side="BUY",
                base_asset_id=1, quote_asset_id=2, account_asset_id=2,
                conversion_symbols=[], quotes_by_symbol_id={}, now_timestamp_ms=NOW,
                min_volume=500, max_volume=100, step_volume=100,
            )

    def test_rejects_budget_below_minimum_volume(self):
        with self.assertRaisesRegex(ValueError, "too small"):
            size_fx_volume_for_risk(
                risk_budget_account_currency=0.001,
                entry_price=1.10,
                stop_price=1.09,
                trade_side="BUY",
                base_asset_id=1,
                quote_asset_id=2,
                account_asset_id=2,
                conversion_symbols=[],
                quotes_by_symbol_id={},
                now_timestamp_ms=NOW,
                min_volume=100,
                max_volume=1_000_000,
                step_volume=100,
            )

    def test_rejects_missing_or_stale_conversion_quote(self):
        symbols = [{
            "symbol_id": 7, "symbol_name": "EURUSD",
            "base_asset_id": 1, "quote_asset_id": 2,
        }]
        with self.assertRaisesRegex(ValueError, "no fully quoted"):
            estimate_fx_stop_loss(
                volume_raw=100_000, entry_price=1.10, stop_price=1.09,
                trade_side="BUY",
                base_asset_id=1, quote_asset_id=2, account_asset_id=1,
                conversion_symbols=symbols, quotes_by_symbol_id={},
                now_timestamp_ms=NOW,
            )


    def test_rejects_stop_loss_on_wrong_side_for_trade_direction(self):
        common = dict(
            volume_raw=100,
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
        )
        with self.assertRaisesRegex(ValueError, "BUY stop-loss must be below"):
            estimate_fx_stop_loss(
                **common, entry_price=1.10, stop_price=1.11, trade_side="BUY"
            )
        with self.assertRaisesRegex(ValueError, "SELL stop-loss must be above"):
            estimate_fx_stop_loss(
                **common, entry_price=1.10, stop_price=1.09, trade_side="SELL"
            )

    def test_accepts_sell_stop_loss_above_entry(self):
        result = estimate_fx_stop_loss(
            volume_raw=100,
            entry_price=1.10,
            stop_price=1.11,
            trade_side="SELL",
            base_asset_id=1,
            quote_asset_id=2,
            account_asset_id=2,
            conversion_symbols=[],
            quotes_by_symbol_id={},
            now_timestamp_ms=NOW,
        )
        self.assertEqual(result["trade_side"], "SELL")
        self.assertAlmostEqual(result["estimated_loss_account_currency"], 0.01)

    def test_rejects_oversized_protocol_volume_without_overflowing(self):
        with self.assertRaisesRegex(ValueError, "numeric range"):
            estimate_fx_stop_loss(
                volume_raw=10 ** 10000,
                entry_price=1.10,
                stop_price=1.09,
                trade_side="BUY",
                base_asset_id=1,
                quote_asset_id=2,
                account_asset_id=2,
                conversion_symbols=[],
                quotes_by_symbol_id={},
                now_timestamp_ms=NOW,
            )

    def test_rejects_oversized_risk_budget_without_overflowing(self):
        with self.assertRaisesRegex(ValueError, "risk budget must be positive and finite"):
            size_fx_volume_for_risk(
                risk_budget_account_currency=10 ** 10000,
                entry_price=1.10,
                stop_price=1.09,
                trade_side="BUY",
                base_asset_id=1,
                quote_asset_id=2,
                account_asset_id=2,
                conversion_symbols=[],
                quotes_by_symbol_id={},
                now_timestamp_ms=NOW,
                min_volume=100,
                max_volume=1_000_000,
                step_volume=100,
            )


if __name__ == "__main__":
    unittest.main()
