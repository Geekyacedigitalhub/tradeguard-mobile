import unittest

from app.ctrader_service import CTraderManager, trade_side_value
from app.risk_api import scale_risk_envelope_for_multiplier

try:
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
    SDK_AVAILABLE = True
except Exception:
    SDK_AVAILABLE = False


class NewMarketOrderRequestTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self):
        manager = CTraderManager()
        captured = {}

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            captured["request"] = request
            captured["environment"] = environment
            return "ok"

        manager._send = fake_send
        return manager, captured

    @unittest.skipUnless(SDK_AVAILABLE, "SDK required")
    async def test_market_order_carries_protection_and_client_id(self):
        manager, captured = self._manager()
        await manager.new_market_order(
            123, 42, "BUY", 100000, "demo",
            stop_loss=1.09, take_profit=1.12, client_order_id="TG0000000001E",
        )
        req = captured["request"]
        self.assertEqual(req.ctidTraderAccountId, 123)
        self.assertEqual(req.symbolId, 42)
        self.assertEqual(req.orderType, int(ProtoOAOrderType.MARKET))
        self.assertEqual(req.tradeSide, int(ProtoOATradeSide.BUY))
        self.assertEqual(req.volume, 100000)
        self.assertAlmostEqual(req.stopLoss, 1.09)
        self.assertAlmostEqual(req.takeProfit, 1.12)
        self.assertEqual(req.clientOrderId, "TG0000000001E")

    @unittest.skipUnless(SDK_AVAILABLE, "SDK required")
    async def test_sell_side_mapping(self):
        manager, captured = self._manager()
        await manager.new_market_order(123, 42, "SELL", 500, "demo", stop_loss=1.11)
        req = captured["request"]
        self.assertEqual(req.tradeSide, int(ProtoOATradeSide.SELL))
        self.assertAlmostEqual(req.stopLoss, 1.11)
        self.assertEqual(req.takeProfit, 0)

    async def test_rejects_invalid_protection_prices(self):
        manager, _ = self._manager()
        for bad in (0, -1, float("inf"), float("nan"), True, "1.09"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await manager.new_market_order(123, 42, "BUY", 100, "demo", stop_loss=bad)

    async def test_rejects_invalid_client_order_id(self):
        manager, _ = self._manager()
        for bad in ("", "  ", "x" * 37, "TG\u00e9", 123):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await manager.new_market_order(123, 42, "BUY", 100, "demo", client_order_id=bad)

    @unittest.skipUnless(SDK_AVAILABLE, "SDK required")
    async def test_rejects_invalid_side(self):
        manager, _ = self._manager()
        with self.assertRaises(ValueError):
            await manager.new_market_order(123, 42, "HOLD", 100, "demo")


class TradeSideValueTests(unittest.TestCase):
    @unittest.skipUnless(SDK_AVAILABLE, "SDK required")
    def test_maps_known_sides(self):
        self.assertEqual(trade_side_value("BUY"), int(ProtoOATradeSide.BUY))
        self.assertEqual(trade_side_value("sell"), int(ProtoOATradeSide.SELL))

    def test_unknown_sides_are_none(self):
        self.assertIsNone(trade_side_value("HOLD"))
        self.assertIsNone(trade_side_value(None))
        self.assertIsNone(trade_side_value(7))


class RiskEnvelopeScalingTests(unittest.TestCase):
    def test_x100_profile_scales_the_whole_envelope(self):
        risk, daily, drawdown = scale_risk_envelope_for_multiplier(0.5, 2.0, 5.0, 100.0)
        self.assertEqual(risk, 50.0)
        self.assertEqual(daily, 100.0)  # 2% x 100 capped at 100%
        self.assertEqual(drawdown, 100.0)
        self.assertLessEqual(risk, daily)

    def test_conservative_multiplier_preserves_proportions(self):
        risk, daily, drawdown = scale_risk_envelope_for_multiplier(0.5, 2.0, 5.0, 1.0)
        self.assertEqual((risk, daily, drawdown), (0.5, 2.0, 5.0))

    def test_caps_never_exceed_account_value(self):
        risk, daily, drawdown = scale_risk_envelope_for_multiplier(5.0, 20.0, 50.0, 3.0)
        self.assertLessEqual(daily, 100.0)
        self.assertLessEqual(drawdown, 100.0)

    def test_scaled_risk_above_daily_budget_fails_closed(self):
        # 5% x 100 = 500% risk vs 2% x 100 = 100% budget: refuse, never re-size.
        with self.assertRaises(ValueError):
            scale_risk_envelope_for_multiplier(5.0, 2.0, 5.0, 100.0)

    def test_invalid_multipliers_are_rejected(self):
        for bad in (0, -1, float("inf"), float("nan"), True, "100", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    scale_risk_envelope_for_multiplier(0.5, 2.0, 5.0, bad)


if __name__ == "__main__":
    unittest.main()
