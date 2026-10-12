import math


def calculate_equity_drawdowns(*, peak_equity, current_equity, day_start_equity):
    """Calculate peak and daily drawdown percentages; return None for invalid values."""
    def percentage_drop(baseline, current):
        if baseline is None or current is None:
            return None
        if isinstance(baseline, bool) or isinstance(current, bool):
            return None
        try:
            baseline = float(baseline)
            current = float(current)
        except (TypeError, ValueError, OverflowError):
            return None
        if not (math.isfinite(baseline) and math.isfinite(current)):
            return None
        if baseline <= 0 or current < 0:
            return None
        return max(0.0, (baseline - current) / baseline * 100.0)

    return {
        "drawdown": percentage_drop(peak_equity, current_equity),
        "daily_drawdown": percentage_drop(day_start_equity, current_equity),
    }
