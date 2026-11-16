"""Scorecard views reconstructed from the processed raw delivery records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .metrics import economy_rate, strike_rate
from .player_names import player_display_name


def build_innings_scorecard(
    events: list[dict[str, Any]], summary: dict[str, Any]
) -> dict[str, Any]:
    player_order: list[int] = []
    names: dict[int, str] = {}
    batting: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "balls": 0, "fours": 0, "sixes": 0}
    )
    dismissals: dict[int, dict[str, Any]] = {}
    uncertain_out_ids: set[int] = set()
    bowling: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"legal_balls": 0, "runs_proxy": 0, "credited_wickets": 0, "dot_balls": 0}
    )
    fall_of_wickets: list[dict[str, Any]] = []
    wicket_number = 0
    missing_dismissed_ids = 0
    total_runs_proxy = 0

    def remember_player(player_id: Any, name: Any) -> int:
        try:
            identifier = int(player_id)
        except (TypeError, ValueError):
            identifier = -1
        if identifier not in names:
            names[identifier] = str(name or "").strip()
            player_order.append(identifier)
        return identifier

    for event in events:
        if int(event.get("innings") or 0) not in (1, 2):
            continue
        striker_id = remember_player(event.get("striker_id"), event.get("striker_name"))
        non_striker_id = remember_player(
            event.get("non_striker_id"), event.get("non_striker_name")
        )
        runs = int(event.get("runs") or 0)
        faced = int(event.get("faced_ball") or 0)
        batting[striker_id]["runs"] += runs
        batting[striker_id]["balls"] += faced
        batting[striker_id]["fours"] += int(event.get("is_four") or 0)
        batting[striker_id]["sixes"] += int(event.get("is_six") or 0)
        team_runs = int(event.get("total_runs_proxy") or 0)
        total_runs_proxy += team_runs

        bowler_id = remember_player(event.get("bowler_id"), event.get("bowler_name"))
        bowling[bowler_id]["legal_balls"] += int(event.get("legal") or 0)
        bowling[bowler_id]["runs_proxy"] += int(
            event.get("bowler_runs_proxy") if event.get("bowler_runs_proxy") is not None else team_runs
        )
        bowling[bowler_id]["credited_wickets"] += int(event.get("credited_wicket") or 0)
        bowling[bowler_id]["dot_balls"] += int(event.get("team_dot") or 0)

        if not int(event.get("is_wicket") or 0):
            continue
        try:
            dismissed_id = int(event.get("dismissed_player_id"))
        except (TypeError, ValueError):
            dismissed_id = -1
        if dismissed_id < 0:
            missing_dismissed_ids += 1
            uncertain_out_ids.update(
                identifier for identifier in (striker_id, non_striker_id) if identifier >= 0
            )
            dismissed_id = -1
            dismissed_name = "Dismissed player ID unavailable"
        elif dismissed_id == striker_id:
            dismissed_name = names.get(striker_id, "")
        elif dismissed_id == non_striker_id:
            dismissed_name = names.get(non_striker_id, "")
        else:
            dismissed_name = ""
        if dismissed_id not in names and dismissed_id >= 0:
            names[dismissed_id] = dismissed_name
            player_order.append(dismissed_id)
        if dismissed_id >= 0:
            batting.setdefault(dismissed_id, {"runs": 0, "balls": 0, "fours": 0, "sixes": 0})
        dismissal_type = str(event.get("dismissal_type") or "Unknown dismissal")
        bowler_name = player_display_name(event.get("bowler_id"), event.get("bowler_name"))
        if dismissed_id >= 0:
            dismissals[dismissed_id] = {
                "type": dismissal_type,
                "bowler": bowler_name if int(event.get("credited_wicket") or 0) else "No bowler credit",
            }
        wicket_number += 1
        fall_of_wickets.append(
            {
                "wicket": wicket_number,
                "score_proxy": int(event.get("score_before") or 0) + team_runs,
                "over_ball": f"{event.get('over_no') or 0}.{event.get('over_ball_num') or 0}",
                "batter": (
                    player_display_name(dismissed_id, dismissed_name)
                    if dismissed_id >= 0
                    else dismissed_name
                ),
                "dismissal": dismissal_type,
                "bowler_credit": (
                    bowler_name if int(event.get("credited_wicket") or 0) else "No bowler credit"
                ),
            }
        )

    batting_rows = []
    for player_id in player_order:
        if player_id not in batting:
            continue
        values = batting[player_id]
        name = player_display_name(player_id, names.get(player_id))
        dismissal = dismissals.get(player_id)
        batting_rows.append(
            {
                "batter": name,
                "source_name": names.get(player_id) or name,
                "runs": values["runs"],
                "balls": values["balls"],
                "fours": values["fours"],
                "sixes": values["sixes"],
                "strike_rate": strike_rate(values["runs"], values["balls"]),
                "dismissal": (
                    dismissal["type"]
                    if dismissal
                    else "Unconfirmed · missing source ID"
                    if player_id in uncertain_out_ids
                    else "Not out"
                ),
            }
        )

    bowling_rows = []
    for player_id in player_order:
        if player_id not in bowling:
            continue
        values = bowling[player_id]
        bowling_rows.append(
            {
                "bowler": player_display_name(player_id, names.get(player_id)),
                "source_name": names.get(player_id),
                "overs": f"{values['legal_balls'] // 6}.{values['legal_balls'] % 6}",
                "legal_balls": values["legal_balls"],
                "runs_charged_proxy": values["runs_proxy"],
                "credited_wickets": values["credited_wickets"],
                "economy_proxy": economy_rate(values["runs_proxy"], values["legal_balls"]),
                "dot_balls": values["dot_balls"],
            }
        )

    total_wickets = int(summary.get("wicket_events") or len(fall_of_wickets))
    legal_balls = int(summary.get("known_legal_balls") or 0)
    return {
        "batting": batting_rows,
        "bowling": bowling_rows,
        "fall_of_wickets": fall_of_wickets,
        "runs_proxy": int(summary.get("total_runs_proxy") or total_runs_proxy),
        "wickets": total_wickets,
        "legal_balls": legal_balls,
        "overs": f"{legal_balls // 6}.{legal_balls % 6}",
        "missing_dismissed_ids": missing_dismissed_ids,
    }
