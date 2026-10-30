import unittest

from app.profit_engine import (
    ProfitConfig,
    adaptive_risk_multiplier,
    evaluate_opportunity,
    rank_opportunities,
)


class AdaptiveRiskMultiplierX100Tests(unittest.TestCase):
    def test_strong_setup_reaches_x100_ceiling(self):
        # x100 profile: the best setups must actually reach 100x.
        multiplier = adaptive_risk_multiplier(
            edge_score=100.0,
            expectancy_r=0.5,
            drawdown_percent=0.0,
            consecutive_losses=0,
        )
        self.assertEqual(multiplier, 100.0)

    def test_weak_setup_sits_at_scaled_floor(self):
        # Weakest setup under maximum drawdown and a 3-loss streak lands on
        # the scaled floor (0.25 * 100 / 1.25 = 20x), never below it.
        multiplier = adaptive_risk_multiplier(
            edge_score=0.0,
            expectancy_r=-1.0,
            drawdown_percent=5.0,
            consecutive_losses=3,
        )
        self.assertEqual(multiplier, 20.0)

    def test_drawdown_and_streaks_only_reduce_risk(self):
        base = adaptive_risk_multiplier(
            edge_score=95.0, expectancy_r=0.4, drawdown_percent=0.0, consecutive_losses=0
        )
        for drawdown, streak in ((4.0, 0), (0.0, 3), (4.0, 3), (2.5, 1), (1.5, 2)):
            with self.subTest(drawdown=drawdown, streak=streak):
                reduced = adaptive_risk_multiplier(
                    edge_score=95.0,
                    expectancy_r=0.4,
                    drawdown_percent=drawdown,
                    consecutive_losses=streak,
                )
                self.assertLess(reduced, base)

    def test_stronger_setup_never_risks_less(self):
        for expectancy in (-0.05, 0.1, 0.25, 0.4):
            with self.subTest(expectancy=expectancy):
                weaker = adaptive_risk_multiplier(
                    edge_score=75.0,
                    expectancy_r=expectancy,
                    drawdown_percent=0.0,
                    consecutive_losses=0,
                )
                stronger = adaptive_risk_multiplier(
                    edge_score=95.0,
                    expectancy_r=expectancy,
                    drawdown_percent=0.0,
                    consecutive_losses=0,
                )
                self.assertGreaterEqual(stronger, weaker)

    def test_multiplier_stays_inside_configured_band(self):
        for edge_score in (0.0, 40.0, 70.0, 85.0, 100.0):
            for expectancy in (-1.0, -0.1, 0.0, 0.2, 0.6):
                for drawdown in (0.0, 1.5, 2.5, 4.0, 8.0):
                    for streak in (0, 1, 2, 3, 5):
                        with self.subTest(
                            edge_score=edge_score,
                            expectancy=expectancy,
                            drawdown=drawdown,
                            streak=streak,
                        ):
                            multiplier = adaptive_risk_multiplier(
                                edge_score=edge_score,
                                expectancy_r=expectancy,
                                drawdown_percent=drawdown,
                                consecutive_losses=streak,
                            )
                            self.assertGreaterEqual(multiplier, 20.0)
                            self.assertLessEqual(multiplier, 100.0)

    def test_legacy_125_profile_behavior_preserved(self):
        # Explicitly configured 1.25x profiles keep the old conservative band.
        for edge_score in (0.0, 70.0, 100.0):
            with self.subTest(edge_score=edge_score):
                multiplier = adaptive_risk_multiplier(
                    edge_score=edge_score,
                    expectancy_r=0.0,
                    drawdown_percent=0.0,
                    consecutive_losses=0,
                    min_multiplier=0.25,
                    max_multiplier=1.25,
                )
                self.assertGreaterEqual(multiplier, 0.25)
                self.assertLessEqual(multiplier, 1.25)


class EvaluateOpportunityX100Tests(unittest.TestCase):
    def _strong_signal(self):
        return {
            "symbol": "EURUSD",
            "signal": "BUY",
            "score": 95,
            "entry": 1.0,
            "stop_loss": 0.99,
            "take_profit": 1.025,
            "deep_analysis": {"confluence": 95, "decision": "TRADE CANDIDATE"},
        }

    def _strong_history(self):
        return {"trades": 50, "expectancy_r": 0.3, "profit_factor": 2.0, "win_rate": 60.0}

    def test_executable_setup_reports_multiplier_inside_x100_band(self):
        result = evaluate_opportunity(
            self._strong_signal(),
            historical=self._strong_history(),
            drawdown_percent=0.0,
            consecutive_losses=0,
        )
        self.assertEqual(result["decision"], "EXECUTE")
        self.assertIn(result["tier"], ("A+", "A"))
        self.assertGreaterEqual(result["risk_multiplier"], 20.0)
        self.assertLessEqual(result["risk_multiplier"], 100.0)

    def test_weak_setup_stays_rejected_and_multiplier_is_bounded(self):
        signal = self._strong_signal()
        signal["deep_analysis"]["confluence"] = 40
        result = evaluate_opportunity(signal, historical=self._strong_history())
        self.assertEqual(result["decision"], "WAIT")
        self.assertEqual(result["tier"], "REJECT")
        self.assertGreaterEqual(result["risk_multiplier"], 20.0)
        self.assertLessEqual(result["risk_multiplier"], 100.0)

    def test_explicit_legacy_config_keeps_conservative_multiplier(self):
        legacy = ProfitConfig(max_risk_multiplier=1.25, min_risk_multiplier=0.25)
        result = evaluate_opportunity(
            self._strong_signal(),
            historical=self._strong_history(),
            config=legacy,
        )
        self.assertGreaterEqual(result["risk_multiplier"], 0.25)
        self.assertLessEqual(result["risk_multiplier"], 1.25)


class RankOpportunitiesTests(unittest.TestCase):
    def test_executable_opportunities_rank_first(self):
        weak = {"profit_engine": {"decision": "WAIT", "edge_score": 99.0, "expectancy_r": 10.0}}
        strong = {"profit_engine": {"decision": "EXECUTE", "edge_score": 80.0, "expectancy_r": 0.1}}
        self.assertEqual(rank_opportunities([weak, strong]), [strong, weak])


if __name__ == "__main__":
    unittest.main()
