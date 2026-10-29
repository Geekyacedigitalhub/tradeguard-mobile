import unittest
from types import SimpleNamespace

from app.ctrader_money import decode_money_value, decode_ctrader_equity_snapshot, validate_money_digits


class CTraderMoneyTests(unittest.TestCase):
    def test_decodes_money_using_broker_precision(self):
        self.assertEqual(decode_money_value(12345, 2), 123.45)
        self.assertEqual(decode_money_value(-25, 0), -25.0)

    def test_uses_explicit_fallback_when_precision_is_missing(self):
        self.assertEqual(validate_money_digits(None, fallback=3), 3)
        self.assertEqual(decode_money_value(1250, 3), 1.25)

    def test_rejects_invalid_precision(self):
        for digits in (None, True, False, -1, 13, 2.5, "2"):
            with self.subTest(digits=digits):
                with self.assertRaisesRegex(ValueError, "moneyDigits"):
                    validate_money_digits(digits)

    def test_rejects_malformed_or_non_finite_money(self):
        for value in (True, 123.45, float("nan"), float("inf"), -float("inf"), "bad", "123.45", object()):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "monetary value"):
                    decode_money_value(value, 2)


    def test_pnl_decode_error_includes_received_shape_for_diagnostics(self):
        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        # A response object without the repeated positions field (malformed
        # broker payload) must fail closed AND reveal what was received, so
        # /diag/status can show the shape instead of a generic "invalid".
        bad = SimpleNamespace(moneyDigits=2, ctidTraderAccountId=42)
        with self.assertRaisesRegex(ValueError, "pnl_response type=SimpleNamespace"):
            decode_ctrader_equity_snapshot(trader, bad)

    def test_rejects_integer_amounts_outside_exact_float_range(self):
        for value in ((1 << 53) + 1, -((1 << 53) + 1)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "monetary value"):
                    decode_money_value(value, 2)

    def test_decodes_cloud_equity_from_valid_broker_metrics(self):
        trader = SimpleNamespace(moneyDigits=2, balance=125050)
        pnl = SimpleNamespace(
            moneyDigits=2,
            positionUnrealizedPnL=[
                SimpleNamespace(netUnrealizedPnL=1250),
                SimpleNamespace(netUnrealizedPnL=-300),
            ],
        )
        self.assertEqual(decode_ctrader_equity_snapshot(trader, pnl), (1250.5, 1260.0))

    def test_rejects_missing_balance_instead_of_assuming_zero(self):
        trader = SimpleNamespace(moneyDigits=2)
        pnl = SimpleNamespace(moneyDigits=2, positionUnrealizedPnL=[])
        with self.assertRaisesRegex(ValueError, "balance"):
            decode_ctrader_equity_snapshot(trader, pnl)

    def test_rejects_missing_or_malformed_unrealized_positions(self):
        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        for positions in (None, [SimpleNamespace()], [None]):
            with self.subTest(positions=positions):
                pnl = SimpleNamespace(moneyDigits=2, positionUnrealizedPnL=positions)
                with self.assertRaises(ValueError):
                    decode_ctrader_equity_snapshot(trader, pnl)

    def test_decodes_real_protobuf_pnl_response(self):
        # Regression: cTrader protobuf repeated fields are MutableSequence
        # containers, NOT list subclasses. The decoder must accept the real
        # SDK response type — plain-list doubles in earlier tests hid the bug.
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAGetPositionUnrealizedPnLRes,
        )

        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        pnl = ProtoOAGetPositionUnrealizedPnLRes()
        pnl.ctidTraderAccountId = 49093168
        pnl.moneyDigits = 2
        row = pnl.positionUnrealizedPnL.add()
        row.positionId = 7
        row.netUnrealizedPnL = 12345
        self.assertEqual(decode_ctrader_equity_snapshot(trader, pnl), (1000.0, 1123.45))

    def test_decodes_real_protobuf_pnl_response_with_no_positions(self):
        # An account with zero open positions is a valid, healthy broker
        # response: empty repeated field -> equity equals balance.
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAGetPositionUnrealizedPnLRes,
        )

        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        pnl = ProtoOAGetPositionUnrealizedPnLRes()
        pnl.ParseFromString(b"")
        self.assertEqual(decode_ctrader_equity_snapshot(trader, pnl), (1000.0, 1000.0))

    def test_rejects_non_finite_unrealized_pnl_and_equity(self):
        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        for value in (float("inf"), float("nan"), True):
            with self.subTest(value=value):
                pnl = SimpleNamespace(
                    moneyDigits=2,
                    positionUnrealizedPnL=[SimpleNamespace(netUnrealizedPnL=value)],
                )
                with self.assertRaises(ValueError):
                    decode_ctrader_equity_snapshot(trader, pnl)


if __name__ == "__main__":
    unittest.main()
