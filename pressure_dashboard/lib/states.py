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
PRESSURE_MAX_BALLS_LEFT = 30
PRESSURE_MIN_WICKETS_LOST = 3

BOWLING_PRESSURE_MIN_CURRENT_RPO = 11.0
BOWLING_PRESSURE_MIN_RRR = 9.0
BOWLING_PRESSURE_MAX_BALLS_LEFT = 30
BOWLING_PRESSURE_WICKETS_LOST = 2


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


def credited_wicket(is_wicket: bool, dismissal_type: str | None) -> int:
    if not is_wicket:
        return 0
    return int((dismissal_type or "").strip().casefold() in BOWLER_CREDITED_DISMISSALS)


def pressure_state(
    rrr: float | None,
    balls_remaining: int | None,
    wickets_lost: int,
    state_known: bool,
) -> int:
    """Pre-ball severe-pressure flag; unknown states are never classified."""
    return int(
        state_known
        and rrr is not None
        and balls_remaining is not None
        and rrr >= PRESSURE_MIN_RRR
        and balls_remaining <= PRESSURE_MAX_BALLS_LEFT
        and wickets_lost >= PRESSURE_MIN_WICKETS_LOST
    )


def bowling_pressure_state(
    current_rpo: float | None,
    required_rpo: float | None,
    balls_remaining: int | None,
    wickets_lost: int,
    state_known: bool,
) -> int:
    """Flag the late chase state where the bowling side must contain and take wickets."""
    if not state_known or wickets_lost != BOWLING_PRESSURE_WICKETS_LOST:
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
