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
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["automated_execution_allowed"])
        self.assertFalse(result["risk_sizing_verified"])
        self.assertFalse(result["orders_submitted"])


if __name__ == "__main__":
    unittest.main()
