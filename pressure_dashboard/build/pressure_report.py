"""Build pressure-state player tables directly from the supplied raw CSV files."""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(APP_DIR))
from lib.player_names import player_display_name

MIN_STATE_BALLS = 30
MIN_DECIDED_CHASEES = 20
MIN_ELIGIBLE_PLAYERS = 10
MIN_DISMISSALS_FOR_AVERAGE = 3
MIN_WICKETS_FOR_WICKET_RATE_RANK = 3
PRIOR_BATTING_BALLS = 60
PRIOR_BATTING_DISMISSALS = 3
PRIOR_BOWLING_BALLS = 60
RECENT_INNINGS = 10
ACTIVE_SEASON = "2026"
BATTER_WEIGHTS = {"adjusted_strike_rate": 0.50, "adjusted_average": 0.30, "boundary_share": 0.20}
BOWLER_WEIGHTS = {"adjusted_economy": 0.40, "adjusted_wicket_rate_per_6": 0.40, "dot_share": 0.20}

UNKNOWN_TYPES = {"other", "penalty", ""}
ILLEGAL_TYPES = {"wide", "overstep"}
KNOWN_LEGAL_TYPES = {"none", "byes", "legbyes"}
EXTRA_RUN_TYPES = {"wide", "overstep", "byes", "legbyes"}
BOWLER_WICKET_TYPES = {"caught", "bowled", "lbw", "stump", "hit wicket"}
AVERAGE_EXCLUDED_TYPES = {
    "retire out",
    "retired out",
    "retire hurt",
    "retired hurt",
    "obstracting the field",
    "obstructing the field",
}


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return default


def normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def truth(value: Any) -> bool:
    return normalized(value) in {"true", "1", "yes"}


def legal_and_unknown(extra_type: Any) -> tuple[bool, bool]:
    kind = normalized(extra_type)
    if kind in KNOWN_LEGAL_TYPES:
        return True, False
    if kind in ILLEGAL_TYPES:
        return False, False
    return False, True


def team_run_value(row: dict[str, Any]) -> int:
    """Requested count-based score: batter runs plus one per listed extra event."""
    return integer(row.get("runs")) + int(normalized(row.get("extras_type")) in EXTRA_RUN_TYPES)


def bowler_run_value(row: dict[str, Any]) -> int:
    """Requested bowler charge: batter runs plus one for a wide or no-ball."""
    return integer(row.get("runs")) + int(normalized(row.get("extras_type")) in {"wide", "overstep"})


def batter_out(row: dict[str, Any]) -> bool:
    return truth(row.get("is_wicket")) and normalized(row.get("dismissal_type")) not in AVERAGE_EXCLUDED_TYPES


def credited_wicket(row: dict[str, Any]) -> bool:
    return truth(row.get("is_wicket")) and normalized(row.get("dismissal_type")) in BOWLER_WICKET_TYPES


def numeric_rate(numerator: int | float, denominator: int | float, scale: float = 1.0) -> float | None:
    return round(float(numerator) * scale / float(denominator), 4) if denominator else None


def shrink(raw: float | None, sample: int, baseline: float | None, prior: int) -> float | None:
    if baseline is None:
        return raw
    if raw is None:
        raw = baseline
    return round((raw * sample + baseline * prior) / (sample + prior), 4) if sample + prior else baseline


def assign_percentiles(rows: list[dict[str, Any]], field: str, higher_is_better: bool) -> None:
    ordered = sorted(rows, key=lambda row: ((-row[field]) if higher_is_better else row[field], row["player"]))
    start = 0
    while start < len(ordered):
        value = ordered[start][field]
        end = start + 1
        while end < len(ordered) and ordered[end][field] == value:
            end += 1
        avg_rank = ((start + 1) + end) / 2
        percentile = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - avg_rank) / (len(ordered) - 1)
        for row in ordered[start:end]:
            row[f"{field}_percentile"] = round(percentile, 4)
        start = end


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_inputs() -> tuple[dict[int, dict[str, Any]], dict[tuple[int, int], list[dict[str, Any]]], dict[int, set[str]], dict[str, int]]:
    competition_path = RAW_DIR / "competitions.csv"
    match_path = RAW_DIR / "matches.csv"
    delivery_path = RAW_DIR / "ball_by_ball.csv"
    with competition_path.open("r", encoding="utf-8-sig", newline="") as file:
        competitions = {integer(row.get("comp_id")): row for row in csv.DictReader(file)}

    matches: dict[int, dict[str, Any]] = {}
    with match_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            match_id = integer(row.get("match_id"), -1)
            comp_id = integer(row.get("comp_id"), -1)
            comp = competitions.get(comp_id, {})
            winner = integer(row.get("win_team_id"), 0)
            result = str(row.get("result") or "")
            result_key = result.casefold()
            decided = winner > 0 and not any(token in result_key for token in ("tie", "no result", "abandoned", "cancelled"))
            revised = str(row.get("revised_target") or "").strip()
            matches[match_id] = {
                **row,
                "comp_id": comp_id,
                "match_format": str(comp.get("match_format") or "").strip(),
                "season": str(comp.get("season") or "").strip(),
                "revised_target_value": integer(revised, -1) if revised else None,
                "decided": decided,
            }

    innings: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    player_names: dict[int, set[str]] = defaultdict(set)
    raw_totals = {"delivery_rows": 0, "raw_batter_runs": 0, "known_legal_balls": 0, "unknown_legality_rows": 0}
    with delivery_path.open("r", encoding="utf-8-sig", newline="") as file:
        for source_order, row in enumerate(csv.DictReader(file)):
            raw_totals["delivery_rows"] += 1
            raw_totals["raw_batter_runs"] += integer(row.get("runs"))
            legal, unknown = legal_and_unknown(row.get("extras_type"))
            raw_totals["known_legal_balls"] += int(legal)
            raw_totals["unknown_legality_rows"] += int(unknown)
            row["_source_order"] = source_order
            match_id = integer(row.get("match_id"), -1)
            innings_no = integer(row.get("innings"), -1)
            innings[(match_id, innings_no)].append(row)
            for id_field, name_field in (
                ("striker_id", "striker_name"),
                ("non_striker_id", "non_striker_name"),
                ("bowler_id", "bowler_name"),
            ):
                player_id = integer(row.get(id_field), -1)
                name = str(row.get(name_field) or "").strip()
                if player_id > 0:
                    player_names[player_id].add(name)

    for items in innings.values():
        items.sort(
            key=lambda row: (
                integer(row.get("overid"), -1),
                integer(row.get("innings_ball_num"), -1),
                integer(row.get("over_ball_num"), -1),
                integer(row.get("_source_order"), -1),
            )
        )
    return matches, innings, player_names, raw_totals


def calculate_report() -> dict[str, Any]:
    matches, innings, player_names, raw_totals = read_inputs()
    bad_name_ids = {
        player_id
        for player_id, names in player_names.items()
        if len(names) != 1 or any(
            not name.strip()
            or name.casefold() in {"unknown", "unknown player", "unknown batter", "unknown bowler"}
            for name in names
        )
    }
    canonical_names = {
        player_id: next(iter(names))
        for player_id, names in player_names.items()
        if player_id not in bad_name_ids and names
    }

    first_innings_totals: dict[int, int] = defaultdict(int)
    for (match_id, innings_no), rows in innings.items():
        meta = matches.get(match_id, {})
        if meta.get("match_format") == "T20" and innings_no == 1:
            first_innings_totals[match_id] = sum(team_run_value(row) for row in rows)

    state_counts: dict[str, dict[str, Any]] = {
        name: {"state": name, "deliveries": 0, "matches": set(), "decided_chases": set(), "legal_balls": 0, "batters": set(), "bowlers": set()}
        for name in ("Batting pressure", "Ordinary batting chase", "Bowling pressure", "Ordinary bowling chase")
    }
    batter_stats: dict[tuple[int, str], dict[str, Any]] = {}
    bowler_stats: dict[tuple[int, str], dict[str, Any]] = {}
    recent_batter_innings: dict[tuple[int, int], dict[str, Any]] = {}
    recent_bowler_innings: dict[tuple[int, int], dict[str, Any]] = {}
    active_batter_ids: set[int] = set()
    active_bowler_ids: set[int] = set()
    reconstructed_deliveries: dict[tuple[int, int, int], dict[str, Any]] = {}
    total_t20_batter_runs = 0
    total_t20_legal = 0
    total_state_known = 0
    total_t20_batter_dismissals = 0
    role_rows_excluded_unknown_name = {"batter": 0, "bowler": 0}

    def ensure(bucket: dict[tuple[int, str], dict[str, Any]], player_id: int, state: str, player: str) -> dict[str, Any]:
        return bucket.setdefault(
            (player_id, state),
            {
                "player_id": player_id,
                "player": player_display_name(player_id, player),
                "source_player": player,
                "state": state,
                "deliveries": 0,
                "runs": 0,
                "balls": 0,
                "dismissals": 0,
                "fours": 0,
                "sixes": 0,
                "dots": 0,
                "boundaries_conceded": 0,
                "legal_balls": 0,
                "credited_wickets": 0,
                "matches": set(),
                "innings": set(),
            },
        )

    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        innings1 = innings.get((match_id, 1), [])
        innings2 = innings.get((match_id, 2), [])
        revised_target = meta.get("revised_target_value")
        target = revised_target if revised_target is not None else (first_innings_totals.get(match_id, 0) + 1 if innings1 else None)
        if meta.get("season") == ACTIVE_SEASON:
            for row in innings1 + innings2:
                striker_id = integer(row.get("striker_id"), -1)
                non_striker_id = integer(row.get("non_striker_id"), -1)
                bowler_id = integer(row.get("bowler_id"), -1)
                if striker_id in canonical_names:
                    active_batter_ids.add(striker_id)
                if non_striker_id in canonical_names:
                    active_batter_ids.add(non_striker_id)
                if bowler_id in canonical_names:
                    active_bowler_ids.add(bowler_id)

        score = 0
        legal_bowled = 0
        wickets_down = 0
        state_certain = target is not None
        seq = 0
        for row in innings2:
            seq += 1
            kind = normalized(row.get("extras_type"))
            legal, unknown = legal_and_unknown(kind)
            if unknown:
                state_certain = False
            remaining = 120 - legal_bowled if state_certain else None
            runs_needed = int(target) - score if state_certain and target is not None else None
            known_state = bool(state_certain and remaining is not None and remaining > 0)
            rrr = (runs_needed * 6.0 / remaining) if known_state and runs_needed is not None else None
            current_rpo = (score * 6.0 / legal_bowled) if known_state and legal_bowled > 0 else None
            chase_eligible = bool(known_state and runs_needed is not None and runs_needed > 0)
            batting_pressure = bool(
                chase_eligible and remaining is not None and remaining <= 30 and wickets_down >= 3 and rrr is not None and rrr >= 15
            )
            bowling_pressure = bool(
                chase_eligible and remaining is not None and remaining <= 30 and wickets_down <= 2
                and rrr is not None and rrr >= 9 and current_rpo is not None and current_rpo >= 11
            )
            key = (match_id, 2, seq)
            reconstructed_deliveries[key] = {
                "match_id": match_id,
                "innings": 2,
                "seq": seq,
                "known": int(known_state),
                "legal": int(legal),
                "unknown": int(unknown),
                "score_before": score,
                "target": target,
                "balls_remaining": remaining,
                "wickets_lost": wickets_down,
                "runs_needed": runs_needed,
                "rrr": rrr,
                "current_rpo": current_rpo,
                "pressure": int(batting_pressure),
                "bowling_pressure": int(bowling_pressure),
                "chase_eligible": chase_eligible,
            }
            if known_state:
                total_state_known += 1
                total_t20_legal += int(legal)
                total_t20_batter_runs += integer(row.get("runs"))

            batter_state = None
            if chase_eligible:
                batter_state = "Batting pressure" if batting_pressure else "Ordinary batting chase"
                count = state_counts[batter_state]
                count["deliveries"] += 1
                count["matches"].add(match_id)
                if meta.get("decided"):
                    count["decided_chases"].add(match_id)
                count["legal_balls"] += int(legal)

                bowler_state = "Bowling pressure" if bowling_pressure else "Ordinary bowling chase"
                count_bowl = state_counts[bowler_state]
                count_bowl["deliveries"] += 1
                count_bowl["matches"].add(match_id)
                if meta.get("decided"):
                    count_bowl["decided_chases"].add(match_id)
                count_bowl["legal_balls"] += int(legal)

                batter_id = integer(row.get("striker_id"), -1)
                if batter_id in canonical_names:
                    count["batters"].add(batter_id)
                    item = ensure(batter_stats, batter_id, batter_state, canonical_names[batter_id])
                    batter_runs = integer(row.get("runs"))
                    faced = int(kind != "wide" and kind not in UNKNOWN_TYPES)
                    out = batter_out(row) and integer(row.get("dismissed_player_id"), -1) == batter_id
                    item["deliveries"] += 1
                    item["runs"] += batter_runs
                    item["balls"] += faced
                    item["dismissals"] += int(out)
                    item["fours"] += int(truth(row.get("is_four")))
                    item["sixes"] += int(truth(row.get("is_six")))
                    item["dots"] += int(faced and batter_runs == 0)
                    item["matches"].add(match_id)
                    item["innings"].add((match_id, 2))
                else:
                    role_rows_excluded_unknown_name["batter"] += 1

                dismissed_id = integer(row.get("dismissed_player_id"), -1)
                if batter_out(row):
                    total_t20_batter_dismissals += 1
                    if dismissed_id > 0 and dismissed_id != batter_id:
                        if dismissed_id in canonical_names:
                            count["batters"].add(dismissed_id)
                            dismissed_item = ensure(
                                batter_stats, dismissed_id, batter_state, canonical_names[dismissed_id]
                            )
                            dismissed_item["dismissals"] += 1
                            dismissed_item["matches"].add(match_id)
                            dismissed_item["innings"].add((match_id, 2))
                        elif dismissed_id in bad_name_ids:
                            role_rows_excluded_unknown_name["batter"] += 1

                bowler_id = integer(row.get("bowler_id"), -1)
                if bowler_id in canonical_names:
                    count_bowl["bowlers"].add(bowler_id)
                    item = ensure(bowler_stats, bowler_id, bowler_state, canonical_names[bowler_id])
                    charged = bowler_run_value(row)
                    item["deliveries"] += 1
                    item["runs"] += charged
                    item["legal_balls"] += int(legal)
                    item["credited_wickets"] += int(credited_wicket(row))
                    item["dots"] += int(legal and charged == 0)
                    item["boundaries_conceded"] += int(truth(row.get("is_four"))) + int(truth(row.get("is_six")))
                    item["matches"].add(match_id)
                    item["innings"].add((match_id, 2))
                else:
                    role_rows_excluded_unknown_name["bowler"] += 1

            if known_state:
                _add_recent_rows(row, match_id, meta, canonical_names, recent_batter_innings, recent_bowler_innings)

            score += team_run_value(row)
            legal_bowled += int(legal)
            wickets_down += int(batter_out(row))
            if unknown:
                state_certain = False

    # Add recent-form metrics after compiling all T20 second-innings observations.
    recent_batter = _recent_summary(recent_batter_innings)
    recent_bowler = _recent_summary(recent_bowler_innings)
    state_rows: list[dict[str, Any]] = []
    for name, values in state_counts.items():
        decided_count = len(values["decided_chases"])
        state_rows.append(
            {
                "state": name,
                "delivery_rows": values["deliveries"],
                "matches": len(values["matches"]),
                "decided_chases": decided_count,
                "legal_balls": values["legal_balls"],
                "players": len(values["batters"] if "batting" in name.lower() else values["bowlers"]),
                "reporting_status": "Full cohort available" if decided_count >= MIN_DECIDED_CHASEES else f"Count only; {MIN_DECIDED_CHASEES} decided chases required",
            }
        )

    batter_rows = _enrich_player_rows(batter_stats, recent_batter, role="batter", active_ids=active_batter_ids)
    bowler_rows = _enrich_player_rows(bowler_stats, recent_bowler, role="bowler", active_ids=active_bowler_ids)
    decided_by_state = {row["state"]: int(row.get("decided_chases") or 0) for row in state_rows}
    _score_state_rows(batter_rows, role="batter", active_ids=active_batter_ids, decided_by_state=decided_by_state)
    _score_state_rows(bowler_rows, role="bowler", active_ids=active_bowler_ids, decided_by_state=decided_by_state)
    comparisons = _build_comparisons(batter_rows, bowler_rows, state_rows)

    decided_t20_chases = sum(
        1 for (match_id, innings_no), rows in innings.items()
        if innings_no == 2 and matches.get(match_id, {}).get("match_format") == "T20" and matches.get(match_id, {}).get("decided") and rows
    )
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_files": {name: str(RAW_DIR / name) for name in ("ball_by_ball.csv", "matches.csv", "competitions.csv")},
        "cohort": "All venues; T20 competition rows only; second innings only; 120-ball state model; extra innings excluded.",
        "confirmed_choices": {
            "retire_out": "Excluded from batter dismissals and averages.",
            "bowling_wickets": "Two or fewer wickets down.",
            "bowling_required_rate": "Required rate >= 9 RPO.",
            "bowling_current_rate": "Current rate >= 11 RPO included.",
            "activity": "At least one role appearance in T20 season 2026 at any venue.",
            "recent_form": "Latest 10 known T20 second-innings (chase-cohort) player innings across all venues; fewer than 10 is a review sample and does not qualify for ranking.",
            "weights": {"batters": BATTER_WEIGHTS, "bowlers": BOWLER_WEIGHTS},
        },
        "definitions": {
            "batting_pressure": "Second innings; 1-30 balls remaining; at least 3 wickets down; required rate >= 15; runs needed > 0.",
            "bowling_pressure": "Second innings; 1-30 balls remaining; 2 or fewer wickets down; current rate >= 11; required rate >= 9; runs needed > 0.",
            "state_timing": "State is pre-delivery. A wide/no-ball row can belong to a state but does not advance legal balls. Unknown-legality rows and all later states are excluded.",
            "score_and_target": "Per requested formula, delivery team score is runs plus one for wide, Overstep/no-ball, bye, or leg-bye; target is revised_target when present, otherwise first-innings total plus one.",
            "imputation": "Byes and leg-byes are imputed as one team run per row because their exported run amount is zero. Wides and no-balls are also counted one each for team score and bowler charges. extras_2_runs is not added by this requested formula.",
            "batter_dismissals": "is_wicket excluding retire out, retired out, retire hurt/retired hurt, and obstruction-of-field labels.",
            "ordinary_states": "Known, positive-runs-needed second-innings chase deliveries not in the corresponding batting- or bowling-pressure state.",
            "ranking_score": "Percentile composite. Batters: 50% adjusted strike-rate percentile + 30% adjusted-average percentile + 20% raw boundary-share percentile. Bowlers: 40% adjusted economy percentile (lower is better) + 40% adjusted wickets/6 percentile + 20% raw dot-share percentile.",
            "shrinkage": "Composite-only: SR uses 60 prior balls; average uses 3 prior dismissals; economy and wickets/6 use 60 prior legal balls. Raw values and adjusted values are both retained in output.",
        },
        "raw_totals": raw_totals,
        "excluded_player_ids": {
            "multiple_source_names": sorted(player_id for player_id, names in player_names.items() if len(names) > 1),
            "unknown_or_blank_name": sorted(bad_name_ids - {player_id for player_id, names in player_names.items() if len(names) > 1}),
            "excluded_role_rows_in_pressure_or_ordinary_states": role_rows_excluded_unknown_name,
        },
        "cohort_counts": {
            "t20_matches": sum(1 for row in matches.values() if row.get("match_format") == "T20"),
            "t20_second_innings": sum(1 for (match_id, innings_no), rows in innings.items() if innings_no == 2 and matches.get(match_id, {}).get("match_format") == "T20" and rows),
            "decided_t20_chases": decided_t20_chases,
            "known_t20_chase_states": total_state_known,
            "t20_chase_batter_runs_from_known_rows": total_t20_batter_runs,
            "t20_chase_batter_dismissals": total_t20_batter_dismissals,
            "t20_known_legal_balls_in_chases": total_t20_legal,
        },
        "state_table": state_rows,
        "batter_table": batter_rows,
        "bowler_table": bowler_rows,
        "comparison_table": comparisons,
        "ranking_status": {
            state: _ranking_note(rows, state, decided_by_state.get(state, 0))
            for state, rows in _group_by_state(batter_rows + bowler_rows).items()
        },
        "validation": {},
    }
    return report


def _add_recent_rows(
    row: dict[str, Any],
    match_id: int,
    meta: dict[str, Any],
    names: dict[int, str],
    batters: dict[tuple[int, int], dict[str, Any]],
    bowlers: dict[tuple[int, int], dict[str, Any]],
) -> None:
    batter_id = integer(row.get("striker_id"), -1)
    if batter_id in names:
        item = batters.setdefault((batter_id, match_id), _recent_item(batter_id, names[batter_id], match_id, meta))
        item["runs"] += integer(row.get("runs"))
        kind = normalized(row.get("extras_type"))
        item["balls"] += int(kind not in ({"wide"} | UNKNOWN_TYPES))
        item["dismissals"] += int(batter_out(row) and integer(row.get("dismissed_player_id"), -1) == batter_id)
        item["fours"] += int(truth(row.get("is_four")))
        item["sixes"] += int(truth(row.get("is_six")))
    dismissed_id = integer(row.get("dismissed_player_id"), -1)
    if batter_out(row) and dismissed_id > 0 and dismissed_id != batter_id and dismissed_id in names:
        item = batters.setdefault((dismissed_id, match_id), _recent_item(dismissed_id, names[dismissed_id], match_id, meta))
        item["dismissals"] += 1
    bowler_id = integer(row.get("bowler_id"), -1)
    if bowler_id in names:
        item = bowlers.setdefault((bowler_id, match_id), _recent_item(bowler_id, names[bowler_id], match_id, meta))
        legal, _ = legal_and_unknown(row.get("extras_type"))
        item["runs"] += bowler_run_value(row)
        item["balls"] += int(legal)
        item["wickets"] += int(credited_wicket(row))
        item["dots"] += int(legal and bowler_run_value(row) == 0)


def _recent_item(player_id: int, name: str, match_id: int, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "player": player_display_name(player_id, name),
        "match_id": match_id,
        "date": meta.get("match_date") or "",
        "season": meta.get("season") or "",
        "runs": 0,
        "balls": 0,
        "dismissals": 0,
        "wickets": 0,
        "dots": 0,
        "fours": 0,
        "sixes": 0,
    }


def _recent_summary(innings_rows: dict[tuple[int, int], dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in innings_rows.values():
        by_player[int(row["player_id"])].append(row)
    result = {}
    for player_id, rows in by_player.items():
        recent = sorted(rows, key=lambda row: (row["date"], row["match_id"]), reverse=True)[:RECENT_INNINGS]
        runs = sum(int(row["runs"]) for row in recent)
        balls = sum(int(row["balls"]) for row in recent)
        dismissals = sum(int(row["dismissals"]) for row in recent)
        wickets = sum(int(row["wickets"]) for row in recent)
        result[player_id] = {
            "recent_innings": len(recent),
            "recent_runs": runs,
            "recent_balls": balls,
            "recent_dismissals": dismissals,
            "recent_wickets": wickets,
            "recent_sr": numeric_rate(runs, balls, 100),
            "recent_average": round(runs / dismissals, 2) if dismissals >= MIN_DISMISSALS_FOR_AVERAGE else "Not reported",
            "recent_economy": numeric_rate(runs * 6, balls) if balls else None,
            "recent_wicket_rate_per_6": numeric_rate(wickets * 6, balls) if balls else None,
            "recent_latest_date": recent[0]["date"] if recent else "",
        }
    return result


def _enrich_player_rows(
    source: dict[tuple[int, str], dict[str, Any]],
    recent: dict[int, dict[str, Any]],
    *,
    role: str,
    active_ids: set[int],
) -> list[dict[str, Any]]:
    result = []
    state_names = {"batter": ("Batting pressure", "Ordinary batting chase"), "bowler": ("Bowling pressure", "Ordinary bowling chase")}[role]
    for (player_id, state), item in source.items():
        balls = int(item["balls"] if role == "batter" else item["legal_balls"])
        dismissals = int(item["dismissals"] if role == "batter" else 0)
        wickets = int(item["credited_wickets"] if role == "bowler" else 0)
        raw_average = round(item["runs"] / dismissals, 4) if role == "batter" and dismissals >= MIN_DISMISSALS_FOR_AVERAGE else "Not reported"
        row = {
            **{key: value for key, value in item.items() if key not in {"matches", "innings"}},
            "matches": len(item["matches"]),
            "innings": len(item["innings"]),
            "sample_balls": balls,
            "sample_status": "Eligible sample" if balls >= MIN_STATE_BALLS else "Review sample",
            "active_2026_all_venues": player_id in active_ids,
        }
        # Activity and recent form are attached by calculate_report after the role sets are known.
        if role == "batter":
            row.update(
                {
                    "dismissals": dismissals,
                    "average": raw_average,
                    "strike_rate": numeric_rate(item["runs"], balls, 100),
                    "boundary_events": int(item["fours"] + item["sixes"]),
                    "boundary_share": numeric_rate(item["fours"] + item["sixes"], balls, 100),
                    "dot_share": numeric_rate(item["dots"], balls, 100),
                }
            )
        else:
            row.update(
                {
                    "economy": numeric_rate(item["runs"] * 6, balls),
                    "credited_wickets": wickets,
                    "balls_per_wicket": round(balls / wickets, 4) if wickets else "Not defined",
                    "wicket_rate_per_6": numeric_rate(wickets * 6, balls),
                    "dot_share": numeric_rate(item["dots"], balls, 100),
                    "boundaries_conceded": item["boundaries_conceded"],
                }
            )
        row["recent_form"] = recent.get(player_id, {})
        row["_role"] = role
        row["_state_names"] = state_names
        result.append(row)
    return result


def _score_state_rows(
    rows: list[dict[str, Any]],
    *,
    role: str,
    active_ids: set[int],
    decided_by_state: dict[str, int],
) -> None:
    for state in sorted({row["state"] for row in rows}):
        cohort = [row for row in rows if row["state"] == state]
        if role == "batter":
            total_runs = sum(int(row["runs"]) for row in cohort)
            total_balls = sum(int(row["sample_balls"]) for row in cohort)
            total_dismissals = sum(int(row["dismissals"]) for row in cohort)
            baseline_sr = numeric_rate(total_runs, total_balls, 100)
            baseline_average = round(total_runs / total_dismissals, 4) if total_dismissals else None
            for row in cohort:
                row["adjusted_strike_rate"] = shrink(row["strike_rate"], row["sample_balls"], baseline_sr, PRIOR_BATTING_BALLS)
                adjusted_average = shrink(
                    round(row["runs"] / row["dismissals"], 4) if row["dismissals"] else None,
                    row["dismissals"],
                    baseline_average,
                    PRIOR_BATTING_DISMISSALS,
                )
                row["_adjusted_average_for_composite"] = adjusted_average
                row["adjusted_average"] = (
                    adjusted_average if row["dismissals"] >= MIN_DISMISSALS_FOR_AVERAGE else "Not reported"
                )
                recent = row.get("recent_form", {})
                row["active_2026_all_venues"] = bool(row["player_id"] in active_ids)
                row["recent_innings"] = int(recent.get("recent_innings") or 0)
                row["recent_runs"] = int(recent.get("recent_runs") or 0)
                row["recent_balls"] = int(recent.get("recent_balls") or 0)
                row["recent_dismissals"] = int(recent.get("recent_dismissals") or 0)
                row["recent_strike_rate"] = recent.get("recent_sr")
                row["recent_average"] = recent.get("recent_average", "Not reported")
                row["recent_latest_date"] = recent.get("recent_latest_date", "")
                reasons = []
                if row["sample_balls"] < MIN_STATE_BALLS:
                    reasons.append(f"{row['sample_balls']} state balls; {MIN_STATE_BALLS} required")
                if not row["active_2026_all_venues"]:
                    reasons.append(f"no T20 appearance in {ACTIVE_SEASON} across all venues")
                if row["recent_innings"] < RECENT_INNINGS:
                    reasons.append(f"{row['recent_innings']} recent chase innings; {RECENT_INNINGS} required")
                row["ranking_eligible"] = not reasons
                row["ranking_reasons"] = "; ".join(reasons)
                row["recent_form_status"] = "Eligible form" if row["recent_innings"] >= RECENT_INNINGS else "Review sample"
            _assign_composite(
                cohort,
                role="batter",
                state_decided_chases=decided_by_state.get(state, 0),
            )
        else:
            total_runs = sum(int(row["runs"]) for row in cohort)
            total_balls = sum(int(row["sample_balls"]) for row in cohort)
            total_wickets = sum(int(row["credited_wickets"]) for row in cohort)
            baseline_economy = numeric_rate(total_runs * 6, total_balls)
            baseline_wicket_rate = numeric_rate(total_wickets * 6, total_balls)
            for row in cohort:
                row["adjusted_economy"] = shrink(row["economy"], row["sample_balls"], baseline_economy, PRIOR_BOWLING_BALLS)
                row["adjusted_wicket_rate_per_6"] = shrink(
                    row["wicket_rate_per_6"], row["sample_balls"], baseline_wicket_rate, PRIOR_BOWLING_BALLS
                )
                recent = row.get("recent_form", {})
                row["active_2026_all_venues"] = bool(row["player_id"] in active_ids)
                row["recent_innings"] = int(recent.get("recent_innings") or 0)
                row["recent_runs"] = int(recent.get("recent_runs") or 0)
                row["recent_balls"] = int(recent.get("recent_balls") or 0)
                row["recent_wickets"] = int(recent.get("recent_wickets") or 0)
                row["recent_economy"] = recent.get("recent_economy")
                row["recent_wicket_rate_per_6"] = recent.get("recent_wicket_rate_per_6")
                row["recent_latest_date"] = recent.get("recent_latest_date", "")
                reasons = []
                if row["sample_balls"] < MIN_STATE_BALLS:
                    reasons.append(f"{row['sample_balls']} legal balls; {MIN_STATE_BALLS} required")
                if row["credited_wickets"] < MIN_WICKETS_FOR_WICKET_RATE_RANK:
                    reasons.append(f"{row['credited_wickets']} credited wickets; {MIN_WICKETS_FOR_WICKET_RATE_RANK} required for wicket-rate ranking")
                if not row["active_2026_all_venues"]:
                    reasons.append(f"no T20 appearance in {ACTIVE_SEASON} across all venues")
                if row["recent_innings"] < RECENT_INNINGS:
                    reasons.append(f"{row['recent_innings']} recent chase innings; {RECENT_INNINGS} required")
                row["ranking_eligible"] = not reasons
                row["ranking_reasons"] = "; ".join(reasons)
                row["wicket_rate_status"] = (
                    "Eligible for ranking" if row["credited_wickets"] >= MIN_WICKETS_FOR_WICKET_RATE_RANK else "Review sample"
                )
                row["recent_form_status"] = "Eligible form" if row["recent_innings"] >= RECENT_INNINGS else "Review sample"
            _assign_composite(
                cohort,
                role="bowler",
                state_decided_chases=decided_by_state.get(state, 0),
            )


def _assign_composite(rows: list[dict[str, Any]], *, role: str, state_decided_chases: int) -> None:
    for row in rows:
        row["rank"] = None
        row["composite_score"] = None
        row["ranking_status"] = "Review sample" if not row.get("ranking_eligible") else "Unranked"
    candidates = [row for row in rows if row.get("ranking_eligible")]
    if state_decided_chases < MIN_DECIDED_CHASEES:
        note = f"Count only; {state_decided_chases} decided chases ({MIN_DECIDED_CHASEES} required for state reporting)."
        for row in rows:
            row["ranking_status"] = note if row.get("ranking_eligible") else "Review sample"
            row.pop("_adjusted_average_for_composite", None)
            row.pop("_adjusted_average_for_composite_percentile", None)
        return
    if len(candidates) < MIN_ELIGIBLE_PLAYERS:
        note = f"Unranked list; only {len(candidates)} eligible players (10 required)."
        for row in candidates:
            row["ranking_status"] = note
        for row in rows:
            row.pop("_adjusted_average_for_composite", None)
            row.pop("_adjusted_average_for_composite_percentile", None)
        return
    if role == "batter":
        assign_percentiles(candidates, "adjusted_strike_rate", True)
        assign_percentiles(candidates, "_adjusted_average_for_composite", True)
        assign_percentiles(candidates, "boundary_share", True)
        for row in candidates:
            row["adjusted_average_percentile"] = row["_adjusted_average_for_composite_percentile"]
            row["composite_score"] = round(
                0.50 * row["adjusted_strike_rate_percentile"]
                + 0.30 * row["_adjusted_average_for_composite_percentile"]
                + 0.20 * row["boundary_share_percentile"],
                4,
            )
    else:
        assign_percentiles(candidates, "adjusted_economy", False)
        assign_percentiles(candidates, "adjusted_wicket_rate_per_6", True)
        assign_percentiles(candidates, "dot_share", True)
        for row in candidates:
            row["composite_score"] = round(
                0.40 * row["adjusted_economy_percentile"]
                + 0.40 * row["adjusted_wicket_rate_per_6_percentile"]
                + 0.20 * row["dot_share_percentile"],
                4,
            )
    ranked = sorted(candidates, key=lambda row: (-float(row["composite_score"]), -int(row["sample_balls"]), row["player"]))
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank
        row["ranking_status"] = "Ranked"
    for row in rows:
        row.pop("_adjusted_average_for_composite", None)
        row.pop("_adjusted_average_for_composite_percentile", None)


def _build_comparisons(
    batters: list[dict[str, Any]],
    bowlers: list[dict[str, Any]],
    state_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    cohort_counts = {row["state"]: int(row.get("decided_chases") or 0) for row in state_rows}
    for role, rows, pressure_state, ordinary_state in (
        ("Batter", batters, "Batting pressure", "Ordinary batting chase"),
        ("Bowler", bowlers, "Bowling pressure", "Ordinary bowling chase"),
    ):
        by_id: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in rows:
            by_id[int(row["player_id"])][row["state"]] = row
        for player_id, states in by_id.items():
            pressure = states.get(pressure_state)
            ordinary = states.get(ordinary_state)
            if not pressure or not ordinary:
                continue
            both_30 = int(pressure["sample_balls"]) >= MIN_STATE_BALLS and int(ordinary["sample_balls"]) >= MIN_STATE_BALLS
            recent_innings = int(pressure.get("recent_innings") or 0)
            active_2026 = bool(pressure.get("active_2026_all_venues"))
            activity_form_ready = active_2026 and recent_innings >= RECENT_INNINGS
            comparison_ready = both_30 and activity_form_ready
            comparison_reasons = []
            if int(pressure["sample_balls"]) < MIN_STATE_BALLS:
                comparison_reasons.append(f"pressure sample below {MIN_STATE_BALLS} balls")
            if int(ordinary["sample_balls"]) < MIN_STATE_BALLS:
                comparison_reasons.append(f"ordinary sample below {MIN_STATE_BALLS} balls")
            if not active_2026:
                comparison_reasons.append(f"no T20 appearance in {ACTIVE_SEASON} across all venues")
            if recent_innings < RECENT_INNINGS:
                comparison_reasons.append(f"{recent_innings} recent chase innings; {RECENT_INNINGS} required")
            common = {
                "role": role,
                "player_id": player_id,
                "player": pressure["player"],
                "pressure_balls": pressure["sample_balls"],
                "ordinary_balls": ordinary["sample_balls"],
                "pressure_matches": pressure["matches"],
                "ordinary_matches": ordinary["matches"],
                "comparison_status": "Eligible comparison" if comparison_ready else "Review sample",
                "comparison_reasons": "; ".join(comparison_reasons),
            }
            cohort_has_minimum = (
                cohort_counts.get(pressure_state, 0) >= MIN_DECIDED_CHASEES
                and cohort_counts.get(ordinary_state, 0) >= MIN_DECIDED_CHASEES
            )
            if not cohort_has_minimum:
                common["comparison_status"] = "Count only"
                common["cohort_note"] = (
                    f"Fewer than {MIN_DECIDED_CHASEES} decided chases in at least one state; player rates are not compared."
                )
                comparisons.append(common)
                continue
            if role == "Batter":
                common.update(
                    {
                        "pressure_runs": pressure["runs"],
                        "ordinary_runs": ordinary["runs"],
                        "pressure_sr": pressure["strike_rate"],
                        "ordinary_sr": ordinary["strike_rate"],
                        "pressure_adjusted_sr": pressure["adjusted_strike_rate"],
                        "ordinary_adjusted_sr": ordinary["adjusted_strike_rate"],
                        "sr_uplift": round(pressure["strike_rate"] - ordinary["strike_rate"], 4) if comparison_ready and pressure["strike_rate"] is not None and ordinary["strike_rate"] is not None else "Not compared",
                        "boundary_share_change": round(pressure["boundary_share"] - ordinary["boundary_share"], 4) if comparison_ready and pressure["boundary_share"] is not None and ordinary["boundary_share"] is not None else "Not compared",
                        "pressure_average": pressure["average"] if pressure["dismissals"] >= MIN_DISMISSALS_FOR_AVERAGE else "Not reported",
                        "ordinary_average": ordinary["average"] if ordinary["dismissals"] >= MIN_DISMISSALS_FOR_AVERAGE else "Not reported",
                        "average_change": round(pressure["average"] - ordinary["average"], 4) if comparison_ready and isinstance(pressure["average"], (int, float)) and isinstance(ordinary["average"], (int, float)) else "Not reported",
                        "pressure_composite": pressure["composite_score"],
                        "ordinary_composite": ordinary["composite_score"],
                    }
                )
            else:
                wickets_qualified = int(pressure["credited_wickets"]) >= MIN_WICKETS_FOR_WICKET_RATE_RANK and int(ordinary["credited_wickets"]) >= MIN_WICKETS_FOR_WICKET_RATE_RANK
                common.update(
                    {
                        "pressure_runs_conceded": pressure["runs"],
                        "ordinary_runs_conceded": ordinary["runs"],
                        "pressure_wickets": pressure["credited_wickets"],
                        "ordinary_wickets": ordinary["credited_wickets"],
                        "pressure_economy": pressure["economy"],
                        "ordinary_economy": ordinary["economy"],
                        "economy_change": round(pressure["economy"] - ordinary["economy"], 4) if comparison_ready and pressure["economy"] is not None and ordinary["economy"] is not None else "Not compared",
                        "pressure_adjusted_economy": pressure["adjusted_economy"],
                        "ordinary_adjusted_economy": ordinary["adjusted_economy"],
                        "pressure_wicket_rate_per_6": pressure["wicket_rate_per_6"] if pressure["credited_wickets"] >= MIN_WICKETS_FOR_WICKET_RATE_RANK else "Not reported",
                        "ordinary_wicket_rate_per_6": ordinary["wicket_rate_per_6"] if ordinary["credited_wickets"] >= MIN_WICKETS_FOR_WICKET_RATE_RANK else "Not reported",
                        "wicket_rate_change_per_6": round(pressure["wicket_rate_per_6"] - ordinary["wicket_rate_per_6"], 4) if comparison_ready and wickets_qualified and pressure["wicket_rate_per_6"] is not None and ordinary["wicket_rate_per_6"] is not None else "Not reported",
                        "dot_share_change": round(pressure["dot_share"] - ordinary["dot_share"], 4) if comparison_ready and pressure["dot_share"] is not None and ordinary["dot_share"] is not None else "Not compared",
                    }
                )
            comparisons.append(common)
    return comparisons


def _group_by_state(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["state"]].append(row)
    return grouped


def _ranking_note(rows: list[dict[str, Any]], state: str, decided_chases: int) -> str:
    if decided_chases < MIN_DECIDED_CHASEES:
        return f"{state}: count only; {decided_chases} decided chases, {MIN_DECIDED_CHASEES} required."
    eligible = sum(bool(row.get("ranking_eligible")) for row in rows)
    if eligible < MIN_ELIGIBLE_PLAYERS:
        return f"{state}: list without ranking; {eligible} eligible players, {MIN_ELIGIBLE_PLAYERS} required."
    return f"{state}: ranked {eligible} eligible players using the stated weighted composite."


def save_report(report: dict[str, Any]) -> None:
    json_path = OUTPUT_DIR / "pressure_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    state_columns = ["state", "delivery_rows", "matches", "decided_chases", "legal_balls", "players", "reporting_status"]
    batter_columns = [
        "rank", "player", "player_id", "source_player", "state", "matches", "innings", "deliveries", "runs", "sample_balls", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "fours", "sixes", "boundary_events", "boundary_share", "dots", "dot_share", "recent_innings", "recent_runs", "recent_balls", "recent_strike_rate", "recent_dismissals", "recent_average", "recent_latest_date", "active_2026_all_venues", "sample_status", "recent_form_status", "ranking_eligible", "ranking_reasons", "composite_score", "ranking_status"
    ]
    bowler_columns = [
        "rank", "player", "player_id", "source_player", "state", "matches", "innings", "deliveries", "runs", "sample_balls", "economy", "adjusted_economy", "credited_wickets", "balls_per_wicket", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dots", "dot_share", "boundaries_conceded", "recent_innings", "recent_runs", "recent_balls", "recent_economy", "recent_wickets", "recent_wicket_rate_per_6", "recent_latest_date", "active_2026_all_venues", "sample_status", "wicket_rate_status", "recent_form_status", "ranking_eligible", "ranking_reasons", "composite_score", "ranking_status"
    ]
    comparison_columns = sorted({key for row in report["comparison_table"] for key in row}) if report["comparison_table"] else ["role", "player_id", "player", "comparison_status"]
    write_csv(OUTPUT_DIR / "pressure_states.csv", report["state_table"], state_columns)
    write_csv(OUTPUT_DIR / "batter_pressure_figures.csv", report["batter_table"], batter_columns)
    write_csv(OUTPUT_DIR / "bowler_pressure_figures.csv", report["bowler_table"], bowler_columns)
    write_csv(OUTPUT_DIR / "pressure_comparisons.csv", report["comparison_table"], comparison_columns)


def main() -> None:
    report = calculate_report()
    save_report(report)
    print(json.dumps({
        "state_table": report["state_table"],
        "batter_rows": len(report["batter_table"]),
        "bowler_rows": len(report["bowler_table"]),
        "comparison_rows": len(report["comparison_table"]),
        "paths": [str(OUTPUT_DIR / name) for name in ("pressure_report.json", "pressure_states.csv", "batter_pressure_figures.csv", "bowler_pressure_figures.csv", "pressure_comparisons.csv")],
    }, indent=2))


if __name__ == "__main__":
    main()
