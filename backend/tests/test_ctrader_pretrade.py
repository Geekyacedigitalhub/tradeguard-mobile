import unittest
from app.ctrader_pretrade import evaluate_pretrade_readiness


class PretradeTests(unittest.TestCase):
    def test_unknown_contract_is_blocked(self):
        result = evaluate_pretrade_readiness(
            account_id=10, environment="demo", deposit_asset_id=2,
            symbol={"symbol_id": 1, "symbol_name": "EURUSD",
                    "base_asset_id": 1, "quote_asset_id": 2,
                    "volume_constraints_valid": True,
                    "instrument_type": None, "contract_model": None},
            trade_side="BUY", entry_price=1.1, stop_price=1.09)
        self.assertFalse(result["ready"])
        self.assertFalse(result["automated_execution_allowed"])
        self.assertFalse(result["orders_submitted"])

    def test_wrong_stop_direction_is_blocked(self):
        result = evaluate_pretrade_readiness(
            account_id=10, environment="demo", deposit_asset_id=2,
            symbol={"symbol_id": 1, "symbol_name": "EURUSD",
                    "base_asset_id": 1, "quote_asset_id": 2,
                    "volume_constraints_valid": True,
                    "instrument_type": "FX", "contract_model": "linear_fx_base_units"},
            trade_side="BUY", entry_price=1.1, stop_price=1.11)
        self.assertFalse(result["ready"])
        self.assertTrue(any("BUY stop-loss" in item for item in result["blockers"]))

    def test_oversized_prices_are_blocked_without_raising(self):
        symbol = {
            "symbol_id": 1, "symbol_name": "EURUSD",
            "base_asset_id": 1, "quote_asset_id": 2,
            "volume_constraints_valid": True,
            "instrument_type": "FX", "contract_model": "linear_fx_base_units",
        }
        for entry_price, stop_price in ((10 ** 10000, 1.09), (1.1, 10 ** 10000)):
            with self.subTest(entry_price_type=type(entry_price).__name__, stop_price_type=type(stop_price).__name__):
                result = evaluate_pretrade_readiness(
                    account_id=10, environment="demo", deposit_asset_id=2,
                    symbol=symbol, trade_side="BUY",
                    entry_price=entry_price, stop_price=stop_price,
                )
                self.assertFalse(result["ready"])
                self.assertTrue(any("positive finite numbers" in item for item in result["blockers"]))
                self.assertFalse(result["automated_execution_allowed"])
                self.assertFalse(result["orders_submitted"])

    def test_out_of_range_protocol_identifiers_are_blocked(self):
        max_id = (1 << 63) - 1
        invalid = max_id + 1
        base_symbol = {
            "symbol_id": 1, "symbol_name": "EURUSD",
            "base_asset_id": 1, "quote_asset_id": 2,
            "volume_constraints_valid": True,
            "instrument_type": "FX", "contract_model": "linear_fx_base_units",
        }
        cases = (
            ("account", {"account_id": invalid}, "Selected account identity is invalid"),
            ("symbol", {"symbol": {**base_symbol, "symbol_id": invalid}}, "Broker symbol ID is invalid"),
            ("deposit_asset", {"deposit_asset_id": invalid}, "deposit-currency asset ID is unavailable"),
            ("base_asset", {"symbol": {**base_symbol, "base_asset_id": invalid}}, "base-asset ID is unavailable"),
            ("quote_asset", {"symbol": {**base_symbol, "quote_asset_id": invalid}}, "quote-asset ID is unavailable"),
        )
        for label, overrides, expected_blocker in cases:
            with self.subTest(identity=label):
                args = {
                    "account_id": 10, "environment": "demo", "deposit_asset_id": 2,
                    "symbol": base_symbol, "trade_side": "BUY",
                    "entry_price": 1.1, "stop_price": 1.09,
                }
                args.update(overrides)
                result = evaluate_pretrade_readiness(**args)
                self.assertFalse(result["ready"])
                self.assertTrue(any(expected_blocker in item for item in result["blockers"]))
                self.assertFalse(result["automated_execution_allowed"])

    def test_live_account_is_blocked(self):
        result = evaluate_pretrade_readiness(
            account_id=10, environment="live", deposit_asset_id=2,
            symbol={"symbol_id": 1, "symbol_name": "EURUSD",
                    "base_asset_id": 1, "quote_asset_id": 2,
                    "volume_constraints_valid": True,
                    "instrument_type": "FX", "contract_model": "linear_fx_base_units"},
            trade_side="BUY", entry_price=1.1, stop_price=1.09)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Live accounts" in item for item in result["blockers"]))

    def test_readiness_is_never_execution_authorization(self):
        result = evaluate_pretrade_readiness(
            account_id=10, environment="demo", deposit_asset_id=2,
            symbol={"symbol_id": 1, "symbol_name": "EURUSD",
                    "base_asset_id": 1, "quote_asset_id": 2,
                    "volume_constraints_valid": True,
                    "instrument_type": "FX", "contract_model": "linear_fx_base_units"},
            trade_side="BUY", entry_price=1.1, stop_price=1.09)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("account-currency risk sizing has not been verified" in item for item in result["blockers"]))
        self.assertFalse(result["automated_execution_allowed"])
        self.assertFalse(result["risk_sizing_verified"])
        self.assertFalse(result["orders_submitted"])


if __name__ == "__main__":
    unittest.main()
