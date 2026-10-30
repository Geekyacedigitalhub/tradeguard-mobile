"""Profit-seeking decision layer for TradeGuard.

This module does not promise profits. It converts technical evidence and
historical performance into an expected-value style gate, ranks opportunities,
and scales risk conservatively when the account is under pressure.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ProfitConfig:
    min_score: float = 75.0
    min_reward_risk: float = 1.8
    min_expectancy_r: float = 0.05
    min_profit_factor: float = 1.05
    max_cost_r: float = 0.15
    # x100 profile: per-trade risk is scaled by up to 100x the configured
    # base risk (risk_per_trade %), down to the scaled floor.
    max_risk_multiplier: float = 100.0
    min_risk_multiplier: float = 0.25


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def reward_risk(entry: float | None, stop: float | None, target: float | None) -> float:
    if entry is None or stop is None or target is None:
        return 0.0
    risk = abs(float(entry) - float(stop))
    reward = abs(float(target) - float(entry))
    return reward / risk if risk > 0 else 0.0


def estimated_expectancy(win_rate: float, reward_risk_ratio: float, cost_r: float = 0.0) -> float:
    """Expected R after fixed round-trip trading costs."""
    p = _clamp(float(win_rate) / 100.0, 0.0, 1.0)
    rr = max(float(reward_risk_ratio), 0.0)
    return p * rr - (1.0 - p) - max(float(cost_r), 0.0)


def adaptive_risk_multiplier(
    *,
    edge_score: float,
    expectancy_r: float,
    drawdown_percent: float,
    consecutive_losses: int,
    min_multiplier: float = 0.25,
    max_multiplier: float = 100.0,
) -> float:
    """Scale configured risk without ever increasing risk because of losses.

    Setup quality places the multiplier inside the configured band: the
    strongest setups reach ``max_multiplier`` (the x100 ceiling) and weaker
    setups sit at the scaled floor. Drawdown and losing-streak penalties
    only ever push risk downward.
    """
    score_factor = _clamp((float(edge_score) - 70.0) / 30.0, 0.0, 1.0)
    edge_factor = _clamp((float(expectancy_r) + 0.10) / 0.50, 0.0, 1.0)
    quality = 0.55 * score_factor + 0.45 * edge_factor
    # Base band spans half the ceiling up to the full ceiling so the
    # configured maximum is actually reachable by A+ setups.
    multiplier = (0.50 + 0.50 * quality) * float(max_multiplier)

    # Drawdown and losing streaks always reduce risk.
    if drawdown_percent >= 4.0:
        multiplier *= 0.50
    elif drawdown_percent >= 2.5:
        multiplier *= 0.70
    elif drawdown_percent >= 1.5:
        multiplier *= 0.85

    if consecutive_losses >= 3:
        multiplier *= 0.50
    elif consecutive_losses == 2:
        multiplier *= 0.70
    elif consecutive_losses == 1:
        multiplier *= 0.85

    # The floor scales with the ceiling so conservative setups stay
    # conservative relative to the profile (0.25 * 100/1.25 = 20x at the
    # x100 profile), never below the configured minimum either way.
    floor = max(float(min_multiplier) * (float(max_multiplier) / 1.25), float(min_multiplier))
    return _clamp(multiplier, floor, float(max_multiplier))


def evaluate_opportunity(
    signal: dict,
    *,
    historical: dict | None = None,
    spread_r: float = 0.0,
    slippage_r: float = 0.0,
    drawdown_percent: float = 0.0,
    consecutive_losses: int = 0,
    config: ProfitConfig | None = None,
) -> dict:
    """Turn a technical candidate into a profit-oriented decision.

    Historical evidence is preferred. If it is unavailable, the engine stays
    conservative and refuses automatic promotion.
    """
    cfg = config or ProfitConfig()
    deep = signal.get("deep_analysis") or {}
    technical_score = float(deep.get("confluence", signal.get("score") or 0) or 0)
    rr = reward_risk(signal.get("entry"), signal.get("stop_loss"), signal.get("take_profit"))

    historical = historical or {}
    trades = int(historical.get("trades") or 0)
    historical_expectancy = historical.get("expectancy_r")
    profit_factor = historical.get("profit_factor")
    win_rate = historical.get("win_rate")

    if historical_expectancy is not None:
        expectancy = float(historical_expectancy) - max(spread_r, 0.0) - max(slippage_r, 0.0)
    elif win_rate is not None:
        expectancy = estimated_expectancy(float(win_rate), rr, spread_r + slippage_r)
    else:
        expectancy = -1.0

    evidence_ok = (
        trades >= 30
        and expectancy >= cfg.min_expectancy_r
        and (profit_factor is None or float(profit_factor) >= cfg.min_profit_factor)
    )
    technical_ok = technical_score >= cfg.min_score
    rr_ok = rr >= cfg.min_reward_risk
    cost_r = max(spread_r, 0.0) + max(slippage_r, 0.0)
    cost_ok = cost_r <= cfg.max_cost_r

    # Edge score rewards technical quality and measured expectancy, but never
    # lets a weak historical sample masquerade as a strong setup.
    expectancy_component = _clamp((expectancy + 0.10) / 0.60, 0.0, 1.0) * 25.0
    rr_component = _clamp(rr / 3.0, 0.0, 1.0) * 15.0
    technical_component = _clamp(technical_score / 100.0, 0.0, 1.0) * 60.0
    edge_score = round(technical_component + expectancy_component + rr_component, 2)

    multiplier = adaptive_risk_multiplier(
        edge_score=edge_score,
        expectancy_r=expectancy,
        drawdown_percent=drawdown_percent,
        consecutive_losses=consecutive_losses,
        min_multiplier=cfg.min_risk_multiplier,
        max_multiplier=cfg.max_risk_multiplier,
    )

    vetoes = []
    if not technical_ok:
        vetoes.append("Technical confluence is below the execution threshold.")
    if not rr_ok:
        vetoes.append(f"Reward/risk is only {rr:.2f}R; minimum is {cfg.min_reward_risk:.2f}R.")
    if not evidence_ok:
        vetoes.append("Historical edge is not strong enough for automatic execution.")
    if not cost_ok:
        vetoes.append("Estimated spread/slippage cost is too high for this setup.")
    if deep.get("decision") != "TRADE CANDIDATE":
        vetoes.append("Deep research gate has not approved this setup.")

    # Automatic execution requires every gate. A high technical score cannot
    # override poor expectancy, costs, or drawdown conditions.
    executable = not vetoes and isfinite(expectancy)
    tier = "A+" if executable and edge_score >= 90 else "A" if executable and edge_score >= 82 else "B" if executable else "REJECT"

    return {
        "decision": "EXECUTE" if executable else "WAIT",
        "tier": tier,
        "edge_score": edge_score,
        "technical_score": round(technical_score, 2),
        "expectancy_r": round(expectancy, 4),
        "reward_risk": round(rr, 3),
        "historical_trades": trades,
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "estimated_cost_r": round(cost_r, 4),
        "risk_multiplier": round(multiplier, 3),
        "vetoes": vetoes[:8],
        "ranking_key": edge_score if executable else edge_score * 0.5,
    }


def rank_opportunities(opportunities: list[dict]) -> list[dict]:
    """Return strongest opportunities first without changing their contents."""
    return sorted(
        opportunities,
        key=lambda item: (
            item.get("profit_engine", {}).get("decision") == "EXECUTE",
            float(item.get("profit_engine", {}).get("edge_score") or 0),
            float(item.get("profit_engine", {}).get("expectancy_r") or -999),
        ),
        reverse=True,
    )
