"""Shared formulas used across the dashboard."""


def safe_div(numerator: float, denominator: float, default: float | None = None) -> float | None:
    return numerator / denominator if denominator else default


def strike_rate(runs: float, balls_faced: float) -> float | None:
    value = safe_div(runs * 100.0, balls_faced)
    return round(value, 2) if value is not None else None


def batting_average(runs: float, dismissals: float) -> float | None:
    value = safe_div(runs, dismissals)
    return round(value, 2) if value is not None else None


def economy_rate(raw_runs_proxy: float, legal_balls: float) -> float | None:
    value = safe_div(raw_runs_proxy * 6.0, legal_balls)
    return round(value, 2) if value is not None else None


def wicket_rate(credited_wickets: float, legal_balls: float) -> float | None:
    value = safe_div(credited_wickets * 100.0, legal_balls)
    return round(value, 2) if value is not None else None


def share(count: float, opportunities: float) -> float | None:
    value = safe_div(count * 100.0, opportunities)
    return round(value, 2) if value is not None else None


def shrink_to_baseline(
    value: float | None,
    sample: float,
    baseline: float | None,
    prior_sample: float,
) -> float | None:
    """Empirical blend of a player rate and cohort baseline."""
    if value is None:
        return baseline
    if baseline is None:
        return value
    weight = sample / (sample + prior_sample) if sample + prior_sample else 0.0
    return round(weight * value + (1.0 - weight) * baseline, 2)


def fmt(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}%"
