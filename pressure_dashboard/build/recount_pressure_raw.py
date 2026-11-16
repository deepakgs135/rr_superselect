"""Independent pressure-state recount using only the three source CSV files.

Run from any directory with:
    python build/recount_pressure_raw.py

This script does not import the dashboard, processed database, or build-state
functions. It writes a raw delivery-state ledger and ID-keyed player totals to
data/pressure_report for reconciliation.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"

LEGAL_TYPES = {"none", "byes", "legbyes"}
ILLEGAL_TYPES = {"wide", "overstep"}
EXTRA_RUN_TYPES = {"wide", "overstep", "byes", "legbyes"}
DISMISSAL_EXCLUSIONS = {
    "retire out",
    "retired out",
    "retire hurt",
    "retired hurt",
    "obstracting the field",
    "obstructing the field",
}
UNKNOWN_PLAYER_NAMES = {"unknown", "unknown player", "unknown batter", "unknown bowler"}


def text(value: Any) -> str:
    return str(value or "").strip()


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(text(value))) if text(value) else default
    except (TypeError, ValueError):
        return default


def normalized(value: Any) -> str:
    return text(value).casefold()


def truth(value: Any) -> bool:
    return normalized(value) in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def team_runs(row: dict[str, Any]) -> int:
    kind = normalized(row.get("extras_type"))
    return integer(row.get("runs")) + int(kind in EXTRA_RUN_TYPES)


def is_batter_dismissal(row: dict[str, Any]) -> bool:
    return truth(row.get("is_wicket")) and normalized(row.get("dismissal_type")) not in DISMISSAL_EXCLUSIONS


def is_known_legal(kind: str) -> bool:
    return kind in LEGAL_TYPES


def state_name(role: str, pressure: bool) -> str:
    if role == "Batter":
        return "Batting pressure" if pressure else "Ordinary batting chase"
    return "Bowling pressure" if pressure else "Ordinary bowling chase"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def recount() -> dict[str, Any]:
    competitions = {
        integer(row.get("comp_id"), -1): row
        for row in read_csv(RAW_DIR / "competitions.csv")
    }
    matches: dict[int, dict[str, Any]] = {}
    for row in read_csv(RAW_DIR / "matches.csv"):
        match_id = integer(row.get("match_id"), -1)
        competition = competitions.get(integer(row.get("comp_id"), -1), {})
        matches[match_id] = {
            **row,
            "match_format": text(competition.get("match_format")).upper(),
        }

    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    names_by_id: dict[int, set[str]] = defaultdict(set)
    raw_totals = {"delivery_rows": 0, "runs_column_sum": 0, "known_legal_balls": 0, "unknown_legality_rows": 0}
    for source_order, row in enumerate(read_csv(RAW_DIR / "ball_by_ball.csv")):
        row["_source_order"] = source_order
        raw_totals["delivery_rows"] += 1
        raw_totals["runs_column_sum"] += integer(row.get("runs"))
        kind = normalized(row.get("extras_type"))
        legal = is_known_legal(kind)
        unknown = kind not in LEGAL_TYPES | ILLEGAL_TYPES
        raw_totals["known_legal_balls"] += int(legal)
        raw_totals["unknown_legality_rows"] += int(unknown)
        groups[(integer(row.get("match_id"), -1), integer(row.get("innings"), -1))].append(row)
        for id_field, name_field in (
            ("striker_id", "striker_name"),
            ("non_striker_id", "non_striker_name"),
            ("bowler_id", "bowler_name"),
        ):
            player_id = integer(row.get(id_field), -1)
            if player_id > 0:
                names_by_id[player_id].add(text(row.get(name_field)))

    for rows in groups.values():
        rows.sort(
            key=lambda row: (
                integer(row.get("overid"), -1),
                integer(row.get("innings_ball_num"), -1),
                integer(row.get("over_ball_num"), -1),
                integer(row.get("_source_order"), -1),
            )
        )

    excluded_ids = {
        player_id
        for player_id, variants in names_by_id.items()
        if len(variants) != 1
        or any(not name or name.casefold() in UNKNOWN_PLAYER_NAMES for name in variants)
    }
    valid_ids = set(names_by_id) - excluded_ids
    display_names = {player_id: next(iter(names_by_id[player_id])) for player_id in valid_ids}

    first_totals = {
        match_id: sum(team_runs(row) for row in rows)
        for (match_id, innings_no), rows in groups.items()
        if innings_no == 1 and matches.get(match_id, {}).get("match_format") == "T20"
    }
    state_names = (
        "Batting pressure",
        "Ordinary batting chase",
        "Bowling pressure",
        "Ordinary bowling chase",
    )
    state_acc: dict[str, dict[str, Any]] = {
        name: {"delivery_rows": 0, "legal_balls": 0, "matches": set(), "decided_chases": set(), "players": set()}
        for name in state_names
    }
    batters: dict[tuple[int, str], dict[str, Any]] = {}
    bowlers: dict[tuple[int, str], dict[str, Any]] = {}
    ledger: list[dict[str, Any]] = []
    flag_totals = {"batting_pressure": 0, "bowling_pressure": 0, "both_pressure_flags": 0}
    state_rows_checked = 0
    known_chase_rows = 0
    t20_matches = sum(meta.get("match_format") == "T20" for meta in matches.values())
    t20_second_innings = 0

    def player_row(bucket: dict[tuple[int, str], dict[str, Any]], player_id: int, state: str, role: str) -> dict[str, Any]:
        key = (player_id, state)
        if key not in bucket:
            bucket[key] = {
                "player_id": player_id,
                "player": display_names[player_id],
                "source_player": display_names[player_id],
                "role": role,
                "state": state,
                "deliveries": 0,
                "runs": 0,
                "balls": 0,
                "dismissals": 0,
                "fours": 0,
                "sixes": 0,
                "dots": 0,
                "legal_balls": 0,
                "credited_wickets": 0,
                "boundaries_conceded": 0,
                "matches": set(),
                "innings": set(),
            }
        return bucket[key]

    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        rows = groups.get((match_id, 2), [])
        if rows:
            t20_second_innings += 1
        innings_one_exists = (match_id, 1) in groups
        revised = text(meta.get("revised_target"))
        target = integer(revised, -1) if revised else first_totals.get(match_id, 0) + 1 if innings_one_exists else None
        if target is not None and target < 0:
            target = None

        winner = integer(meta.get("win_team_id"), 0)
        result = normalized(meta.get("result"))
        decided = winner > 0 and not any(token in result for token in ("tie", "no result", "abandoned", "cancelled"))
        score = legal_balls_bowled = wickets_down = seq = 0
        state_certain = target is not None

        for row in rows:
            seq += 1
            kind = normalized(row.get("extras_type"))
            legal = is_known_legal(kind)
            unknown = kind not in LEGAL_TYPES | ILLEGAL_TYPES
            if unknown:
                state_certain = False

            balls_remaining = 120 - legal_balls_bowled if state_certain else None
            runs_needed = int(target) - score if state_certain and target is not None else None
            state_known = bool(state_certain and balls_remaining is not None and balls_remaining > 0)
            if not state_known:
                balls_remaining = None
                runs_needed = None
            required_rate = (
                runs_needed * 6.0 / balls_remaining
                if state_known and balls_remaining is not None and runs_needed is not None
                else None
            )
            current_rate = (
                score * 6.0 / legal_balls_bowled
                if state_known and legal_balls_bowled > 0
                else None
            )
            active_chase = bool(state_known and runs_needed is not None and runs_needed > 0)
            batting_pressure = bool(
                active_chase
                and balls_remaining is not None
                and 1 <= balls_remaining <= 30
                and wickets_down >= 3
                and required_rate is not None
                and required_rate >= 15
            )
            bowling_pressure = bool(
                active_chase
                and balls_remaining is not None
                and 1 <= balls_remaining <= 30
                and wickets_down <= 2
                and required_rate is not None
                and required_rate >= 9
                and current_rate is not None
                and current_rate >= 11
            )
            state_rows_checked += 1
            flag_totals["batting_pressure"] += int(batting_pressure)
            flag_totals["bowling_pressure"] += int(bowling_pressure)
            flag_totals["both_pressure_flags"] += int(batting_pressure) + int(bowling_pressure)
            ledger.append(
                {
                    "match_id": match_id,
                    "innings": 2,
                    "seq": seq,
                    "source_order": row.get("_source_order"),
                    "striker_id": integer(row.get("striker_id"), -1),
                    "striker_name": text(row.get("striker_name")),
                    "dismissed_player_id": integer(row.get("dismissed_player_id"), -1),
                    "state_known": int(state_known),
                    "legal": int(legal),
                    "unknown_legality": int(unknown),
                    "score_before": score,
                    "target": target,
                    "balls_remaining": balls_remaining,
                    "wickets_down": wickets_down,
                    "runs_needed": runs_needed,
                    "current_rate": round(current_rate, 8) if current_rate is not None else None,
                    "required_rate": round(required_rate, 8) if required_rate is not None else None,
                    "batting_pressure": int(batting_pressure),
                    "bowling_pressure": int(bowling_pressure),
                    "active_chase": int(active_chase),
                }
            )

            if active_chase:
                bat_state = state_name("Batter", batting_pressure)
                bowl_state = state_name("Bowler", bowling_pressure)
                for state in (bat_state, bowl_state):
                    acc = state_acc[state]
                    acc["delivery_rows"] += 1
                    acc["legal_balls"] += int(legal)
                    acc["matches"].add(match_id)
                    if decided:
                        acc["decided_chases"].add(match_id)

                batter_id = integer(row.get("striker_id"), -1)
                if batter_id in valid_ids:
                    agg = player_row(batters, batter_id, bat_state, "Batter")
                    batter_runs = integer(row.get("runs"))
                    faced = int(kind != "wide")
                    agg["deliveries"] += 1
                    agg["runs"] += batter_runs
                    agg["balls"] += faced
                    agg["fours"] += int(truth(row.get("is_four")))
                    agg["sixes"] += int(truth(row.get("is_six")))
                    agg["dots"] += int(faced and batter_runs == 0)
                    agg["matches"].add(match_id)
                    agg["innings"].add((match_id, 2))
                    state_acc[bat_state]["players"].add(batter_id)

                dismissed_id = integer(row.get("dismissed_player_id"), -1)
                if is_batter_dismissal(row) and dismissed_id in valid_ids:
                    agg = player_row(batters, dismissed_id, bat_state, "Batter")
                    agg["dismissals"] += 1
                    agg["matches"].add(match_id)
                    agg["innings"].add((match_id, 2))
                    state_acc[bat_state]["players"].add(dismissed_id)

                bowler_id = integer(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    agg = player_row(bowlers, bowler_id, bowl_state, "Bowler")
                    charged_runs = integer(row.get("runs")) + int(kind in {"wide", "overstep"})
                    credited_wicket = truth(row.get("is_wicket")) and normalized(row.get("dismissal_type")) in {
                        "caught", "bowled", "lbw", "stump", "hit wicket"
                    }
                    agg["deliveries"] += 1
                    agg["runs"] += charged_runs
                    agg["legal_balls"] += int(legal)
                    agg["credited_wickets"] += int(credited_wicket)
                    agg["dots"] += int(legal and charged_runs == 0)
                    agg["boundaries_conceded"] += int(truth(row.get("is_four"))) + int(truth(row.get("is_six")))
                    agg["matches"].add(match_id)
                    agg["innings"].add((match_id, 2))
                    state_acc[bowl_state]["players"].add(bowler_id)

                known_chase_rows += 1

            score += team_runs(row)
            legal_balls_bowled += int(legal)
            wickets_down += int(is_batter_dismissal(row))
            if unknown:
                state_certain = False

    for rows in (batters, bowlers):
        for item in rows.values():
            item["matches"] = len(item["matches"])
            item["innings"] = len(item["innings"])

    state_table = [
        {
            "state": state,
            "delivery_rows": values["delivery_rows"],
            "matches": len(values["matches"]),
            "decided_chases": len(values["decided_chases"]),
            "legal_balls": values["legal_balls"],
            "players": len(values["players"]),
        }
        for state, values in state_acc.items()
    ]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Raw CSV only; standard library only; no imports from dashboard/build state code or processed database.",
        "sources": {name: str(RAW_DIR / name) for name in ("ball_by_ball.csv", "matches.csv", "competitions.csv")},
        "rules": {
            "scope": "T20 second innings only; first two innings only; 120 scheduled balls.",
            "batting_pressure": "1-30 legal balls remaining; at least 3 wickets down before the ball; required rate >= 15; positive runs needed.",
            "bowling_pressure": "1-30 legal balls remaining; 2 or fewer wickets down before the ball; required rate >= 9; current rate >= 11; positive runs needed.",
            "legality": "none/byes/legbyes legal; wide/Overstep illegal; other/Penalty/blank/unrecognized unknown; unknown row and all later states excluded.",
            "target": "matches.revised_target when nonblank; otherwise first innings runs plus one per wide, Overstep, bye, and leg-bye, then plus one.",
            "imputation": "One team run per wide, Overstep, bye, and leg-bye row; raw runs column is retained for batter runs.",
            "wickets": "Pre-delivery count of is_wicket rows, excluding retire-outs, retired hurt, and obstruction labels.",
            "batter_dismissals": "is_wicket rows assigned to dismissed_player_id; the same exclusions apply.",
            "player_key": "Unique source player_id; IDs with unknown/blank names or multiple source names are excluded from player figures.",
        },
        "raw_totals": raw_totals,
        "cohort": {
            "t20_matches": t20_matches,
            "t20_second_innings": t20_second_innings,
            "delivery_state_rows_checked": state_rows_checked,
            "known_positive_runs_needed_chase_rows": known_chase_rows,
        },
        "pressure_flags": flag_totals,
        "state_table": state_table,
        "player_id_audit": {
            "distinct_source_player_ids": len(names_by_id),
            "excluded_unknown_or_multi_name_ids": len(excluded_ids),
            "eligible_source_player_ids": len(valid_ids),
            "excluded_ids": sorted(excluded_ids),
        },
        "batter_rows": list(batters.values()),
        "bowler_rows": list(bowlers.values()),
        "delivery_state_ledger": ledger,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "pressure_raw_recount.json").write_text(
        json.dumps({key: value for key, value in summary.items() if key not in {"batter_rows", "bowler_rows", "delivery_state_ledger"}}, indent=2),
        encoding="utf-8",
    )
    state_fields = list(ledger[0]) if ledger else ["match_id", "innings", "seq"]
    write_csv(OUTPUT_DIR / "pressure_raw_delivery_states.csv", ledger, state_fields)
    write_csv(
        OUTPUT_DIR / "pressure_raw_batter_figures.csv",
        list(batters.values()),
        ["player_id", "player", "source_player", "role", "state", "matches", "innings", "deliveries", "runs", "balls", "dismissals", "fours", "sixes", "dots"],
    )
    write_csv(
        OUTPUT_DIR / "pressure_raw_bowler_figures.csv",
        list(bowlers.values()),
        ["player_id", "player", "source_player", "role", "state", "matches", "innings", "deliveries", "runs", "legal_balls", "credited_wickets", "dots", "boundaries_conceded"],
    )
    return summary


def main() -> None:
    summary = recount()
    print(json.dumps({
        "raw_totals": summary["raw_totals"],
        "cohort": summary["cohort"],
        "pressure_flags": summary["pressure_flags"],
        "state_table": summary["state_table"],
        "player_id_audit": summary["player_id_audit"],
        "outputs": [
            str(OUTPUT_DIR / "pressure_raw_recount.json"),
            str(OUTPUT_DIR / "pressure_raw_delivery_states.csv"),
            str(OUTPUT_DIR / "pressure_raw_batter_figures.csv"),
            str(OUTPUT_DIR / "pressure_raw_bowler_figures.csv"),
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
