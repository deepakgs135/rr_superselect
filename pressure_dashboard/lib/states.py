"""Shared state definitions and source-field conventions."""

KNOWN_LEGAL_EXTRAS = {"none", "byes", "legbyes"}
KNOWN_ILLEGAL_EXTRAS = {"wide", "overstep"}
UNKNOWN_EXTRAS = {"other", "penalty", ""}

# Dismissals commonly credited to the bowler in cricket scorecards.
BOWLER_CREDITED_DISMISSALS = {
    "caught",
    "bowled",
    "lbw",
    "stump",
    "hit wicket",
}

PRESSURE_MIN_RRR = 15.0
PRESSURE_MIN_WICKETS_LOST = 3
PRESSURE_MAX_BALLS_REMAINING = 30
PRESSURE_FORMAT = "T20"

BOWLING_PRESSURE_MIN_CURRENT_RPO = 11.0
BOWLING_PRESSURE_MIN_RRR = 9.0
BOWLING_PRESSURE_MAX_BALLS_LEFT = 30
BOWLING_PRESSURE_MAX_WICKETS_LOST = 2

BATTER_AVERAGE_EXCLUDED_DISMISSALS = {
    "retire out",
    "retired out",
    "retire hurt",
    "retired hurt",
    "obstracting the field",
    "obstructing the field",
}


def normalized_extra(value: str | None) -> str:
    return (value or "").strip().casefold()


def legality(value: str | None) -> tuple[int, int]:
    """Return (is_known_legal, is_unknown_legality)."""
    kind = normalized_extra(value)
    if kind in KNOWN_LEGAL_EXTRAS:
        return 1, 0
    if kind in KNOWN_ILLEGAL_EXTRAS:
        return 0, 0
    if kind in UNKNOWN_EXTRAS:
        return 0, 1
    return 0, 1


def faced_ball(value: str | None) -> int:
    """A faced ball excludes wides and rows with unknown legality."""
    kind = normalized_extra(value)
    return int(kind not in {"wide"} | UNKNOWN_EXTRAS)


def batter_dismissal(is_wicket: bool, dismissal_type: str | None) -> int:
    """Count batter dismissals while excluding retire-outs and obstruction cases."""
    kind = (dismissal_type or "").strip().casefold()
    return int(bool(is_wicket) and kind not in BATTER_AVERAGE_EXCLUDED_DISMISSALS)


def credited_wicket(is_wicket: bool, dismissal_type: str | None) -> int:
    if not is_wicket:
        return 0
    return int((dismissal_type or "").strip().casefold() in BOWLER_CREDITED_DISMISSALS)


def pressure_state(
    rrr: float | None,
    balls_remaining: int | None,
    wickets_lost: int,
    state_known: bool,
    runs_needed: int | None,
) -> int:
    """Batting pressure: final 30 balls, RRR >= 15, and at least 3 down."""
    return int(
        state_known
        and rrr is not None
        and rrr >= PRESSURE_MIN_RRR
        and balls_remaining is not None
        and 0 < balls_remaining <= PRESSURE_MAX_BALLS_REMAINING
        and runs_needed is not None
        and runs_needed > 0
        and wickets_lost >= PRESSURE_MIN_WICKETS_LOST
    )


def bowling_pressure_state(
    current_rpo: float | None,
    required_rpo: float | None,
    balls_remaining: int | None,
    wickets_lost: int,
    state_known: bool,
    runs_needed: int | None,
) -> int:
    """Flag a live late chase where the bowling side must contain and take wickets."""
    if (
        not state_known
        or wickets_lost > BOWLING_PRESSURE_MAX_WICKETS_LOST
        or runs_needed is None
        or runs_needed <= 0
    ):
        return 0

    death_containment = (
        current_rpo is not None
        and current_rpo >= BOWLING_PRESSURE_MIN_CURRENT_RPO
        and balls_remaining is not None
        and required_rpo is not None
        and 0 < balls_remaining <= BOWLING_PRESSURE_MAX_BALLS_LEFT
        and required_rpo >= BOWLING_PRESSURE_MIN_RRR
    )
    return int(death_containment)


def bowler_runs_charged(
    batter_runs: int | None,
    extra_runs: int | None,
    extras_type: str | None,
) -> int:
    """Apply the requested raw-data convention: batter runs plus one wide/no-ball run.

    ``extra_runs`` is accepted for compatibility with earlier calls. The user-defined
    pressure study does not add that column to bowler runs conceded.
    """
    runs = int(batter_runs or 0)
    kind = normalized_extra(extras_type)
    return runs + int(kind in {"wide", "overstep"})


def team_runs_proxy(
    batter_runs: int | None,
    extra_runs: int | None,
    extras_type: str | None,
) -> int:
    """Use one run per recorded wide, no-ball, bye, and leg-bye event.

    This follows the requested count-based imputation for the raw export, which
    stores no run value for these extra types.
    """
    kind = normalized_extra(extras_type)
    _ = extra_runs  # retained for compatibility; not part of the specified formula
    run_total = int(batter_runs or 0)
    if kind in {"wide", "overstep", "byes", "legbyes"}:
        return run_total + 1
    return run_total


def rrr_band(rrr: float | None) -> str:
    if rrr is None:
        return "Unknown"
    if rrr < 8:
        return "Low"
    if rrr <= 12:
        return "Medium"
    if rrr <= 15:
        return "High"
    return "Extreme"


def balls_band(remaining: int | None) -> str:
    if remaining is None:
        return "Unknown"
    if remaining <= 6:
        return "1–6"
    if remaining <= 12:
        return "7–12"
    if remaining <= 18:
        return "13–18"
    if remaining <= 30:
        return "19–30"
    if remaining <= 60:
        return "31–60"
    return "61+"
