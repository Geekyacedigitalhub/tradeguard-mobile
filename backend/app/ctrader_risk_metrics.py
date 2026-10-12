def calculate_equity_drawdowns(*, peak_equity, current_equity, day_start_equity):
    """Calculate peak and daily drawdown percentages; return None for invalid baselines."""
    def percentage_drop(baseline, current):
        if baseline is None or current is None:
            return None
        baseline=float(baseline)
        current=float(current)
        if not (baseline > 0 and baseline < float("inf") and current >= 0 and current < float("inf")):
            return None
        return max(0.0,(baseline-current)/baseline*100.0)
    return {
        "drawdown":percentage_drop(peak_equity,current_equity),
        "daily_drawdown":percentage_drop(day_start_equity,current_equity),
    }
