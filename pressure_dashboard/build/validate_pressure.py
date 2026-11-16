"""Independently recount pressure states and sample player rows from the raw CSVs."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
DB_PATH = APP_DIR / "data" / "processed" / "analytics.sqlite3"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
REPORT_PATH = OUTPUT_DIR / "pressure_report.json"
VALIDATION_PATH = OUTPUT_DIR / "pressure_validation.json"
VALIDATION_CSV = OUTPUT_DIR / "pressure_validation_log.csv"
EXCEPTIONS_CSV = OUTPUT_DIR / "pressure_reproduction_exceptions.csv"
SAMPLE_SEED = 20261115


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return default


def norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def yes(value: Any) -> bool:
    return norm(value) in {"1", "true", "yes"}


def is_legal(kind: Any) -> bool:
    return norm(kind) in {"none", "byes", "legbyes"}


def is_unknown(kind: Any) -> bool:
    return norm(kind) not in {"none", "byes", "legbyes", "wide", "overstep"}


def team_run(row: dict[str, Any]) -> int:
    return as_int(row.get("runs")) + int(norm(row.get("extras_type")) in {"wide", "overstep", "byes", "legbyes"})


def bowler_run(row: dict[str, Any]) -> int:
    return as_int(row.get("runs")) + int(norm(row.get("extras_type")) in {"wide", "overstep"})


def batter_dismissal(row: dict[str, Any]) -> bool:
    excluded = {"retire out", "retired out", "retire hurt", "retired hurt", "obstracting the field", "obstructing the field"}
    return yes(row.get("is_wicket")) and norm(row.get("dismissal_type")) not in excluded


def credited(row: dict[str, Any]) -> bool:
    return yes(row.get("is_wicket")) and norm(row.get("dismissal_type")) in {"caught", "bowled", "lbw", "stump", "hit wicket"}


def load_raw() -> tuple[dict[int, dict[str, Any]], dict[tuple[int, int], list[dict[str, Any]]], dict[int, set[str]], dict[str, int]]:
    with (RAW_DIR / "competitions.csv").open(encoding="utf-8-sig", newline="") as file:
        competitions = {as_int(row.get("comp_id")): row for row in csv.DictReader(file)}
    matches = {}
    with (RAW_DIR / "matches.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            comp = competitions.get(as_int(row.get("comp_id")), {})
            matches[as_int(row.get("match_id"), -1)] = {
                **row,
                "match_format": str(comp.get("match_format") or "").strip(),
                "season": str(comp.get("season") or "").strip(),
            }
    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    names: dict[int, set[str]] = defaultdict(set)
    totals = {"delivery_rows": 0, "runs": 0, "legal_balls": 0, "unknown_legality_rows": 0}
    with (RAW_DIR / "ball_by_ball.csv").open(encoding="utf-8-sig", newline="") as file:
        for order, row in enumerate(csv.DictReader(file)):
            totals["delivery_rows"] += 1
            totals["runs"] += as_int(row.get("runs"))
            totals["legal_balls"] += int(is_legal(row.get("extras_type")))
            totals["unknown_legality_rows"] += int(is_unknown(row.get("extras_type")))
            row["_source_order"] = order
            groups[(as_int(row.get("match_id"), -1), as_int(row.get("innings"), -1))].append(row)
            for id_field, name_field in (("striker_id", "striker_name"), ("non_striker_id", "non_striker_name"), ("bowler_id", "bowler_name")):
                player_id = as_int(row.get(id_field), -1)
                name = str(row.get(name_field) or "").strip()
                if player_id > 0:
                    names[player_id].add(name)
    for rows in groups.values():
        rows.sort(key=lambda row: (as_int(row.get("overid"), -1), as_int(row.get("innings_ball_num"), -1), as_int(row.get("over_ball_num"), -1), as_int(row.get("_source_order"), -1)))
    return matches, groups, names, totals


def player_aggregates_from_raw(
    matches: dict[int, dict[str, Any]],
    groups: dict[tuple[int, int], list[dict[str, Any]]],
    valid_ids: set[int],
) -> tuple[dict[tuple[int, str, str], dict[str, int]], dict[tuple[int, int, int], dict[str, Any]], list[dict[str, Any]]]:
    first_totals = {
        match_id: sum(team_run(row) for row in rows)
        for (match_id, innings_no), rows in groups.items()
        if innings_no == 1 and matches.get(match_id, {}).get("match_format") == "T20"
    }
    aggregates: dict[tuple[int, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    expected_states: dict[tuple[int, int, int], dict[str, Any]] = {}
    state_row_counts: dict[str, dict[str, Any]] = {
        name: {"delivery_rows": 0, "matches": set(), "decided_chases": set(), "legal_balls": 0}
        for name in ("Batting pressure", "Ordinary batting chase", "Bowling pressure", "Ordinary bowling chase")
    }
    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        rows = groups.get((match_id, 2), [])
        revised = str(meta.get("revised_target") or "").strip()
        target = as_int(revised) if revised else first_totals.get(match_id, 0) + 1 if (match_id, 1) in groups else None
        score = legal_balls = wickets = seq = 0
        known = target is not None
        for row in rows:
            seq += 1
            kind = norm(row.get("extras_type"))
            unknown = is_unknown(kind)
            legal = is_legal(kind)
            if unknown:
                known = False
            remaining = 120 - legal_balls if known else None
            needed = int(target) - score if known and target is not None else None
            row_known = bool(known and remaining is not None and remaining > 0)
            rrr = needed * 6.0 / remaining if row_known and needed is not None else None
            crr = score * 6.0 / legal_balls if row_known and legal_balls > 0 else None
            active_chase = bool(row_known and needed is not None and needed > 0)
            bat_pressure = bool(active_chase and remaining is not None and remaining <= 30 and wickets >= 3 and rrr is not None and rrr >= 15)
            bowl_pressure = bool(active_chase and remaining is not None and remaining <= 30 and wickets <= 2 and rrr is not None and rrr >= 9 and crr is not None and crr >= 11)
            key = (match_id, 2, seq)
            row_state = (
                "Unknown"
                if not row_known
                else "Batting pressure"
                if bat_pressure
                else "Bowling pressure"
                if bowl_pressure
                else "Ordinary chase"
                if needed is not None and needed > 0
                else "Target reached"
            )
            expected_states[key] = {
                "state": row_state,
                "state_known": int(row_known),
                "pressure": int(bat_pressure),
                "bowling_pressure": int(bowl_pressure),
                "balls_remaining": remaining if row_known else None,
                "wickets_down": wickets if row_known else None,
                "target": target if row_known else None,
                "score_before": score if row_known else None,
                "runs_needed": needed if row_known else None,
            }
            if active_chase:
                bat_state = "Batting pressure" if bat_pressure else "Ordinary batting chase"
                bowl_state = "Bowling pressure" if bowl_pressure else "Ordinary bowling chase"
                decided = as_int(meta.get("win_team_id"), 0) > 0 and not any(
                    token in norm(meta.get("result"))
                    for token in ("tie", "no result", "abandoned", "cancelled")
                )
                for state_name in (bat_state, bowl_state):
                    state_count = state_row_counts[state_name]
                    state_count["delivery_rows"] += 1
                    state_count["matches"].add(match_id)
                    if decided:
                        state_count["decided_chases"].add(match_id)
                    state_count["legal_balls"] += int(legal)
                batter_id = as_int(row.get("striker_id"), -1)
                if batter_id in valid_ids:
                    agg = aggregates[(batter_id, "Batter", bat_state)]
                    agg["deliveries"] += 1
                    agg["runs"] += as_int(row.get("runs"))
                    agg["balls"] += int(kind != "wide" and not unknown)
                    agg["dismissals"] += int(batter_dismissal(row) and as_int(row.get("dismissed_player_id"), -1) == batter_id)
                    agg["fours"] += int(yes(row.get("is_four")))
                    agg["sixes"] += int(yes(row.get("is_six")))
                    agg["dots"] += int(kind != "wide" and not unknown and as_int(row.get("runs")) == 0)
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
                dismissed_id = as_int(row.get("dismissed_player_id"), -1)
                if batter_dismissal(row) and dismissed_id > 0 and dismissed_id != batter_id and dismissed_id in valid_ids:
                    agg = aggregates[(dismissed_id, "Batter", bat_state)]
                    agg["dismissals"] += 1
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    agg = aggregates[(bowler_id, "Bowler", bowl_state)]
                    charge = bowler_run(row)
                    agg["deliveries"] += 1
                    agg["runs"] += charge
                    agg["legal_balls"] += int(legal)
                    agg["credited_wickets"] += int(credited(row))
                    agg["dots"] += int(legal and charge == 0)
                    agg["boundaries"] += int(yes(row.get("is_four"))) + int(yes(row.get("is_six")))
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
            score += team_run(row)
            legal_balls += int(legal)
            wickets += int(batter_dismissal(row))
            if unknown:
                known = False
    for values in aggregates.values():
        values["matches"] = sum(value for key, value in values.items() if key.startswith("match:"))
        values["innings"] = sum(value for key, value in values.items() if key.startswith("innings:"))
    finalized_state_counts = []
    for name, values in state_row_counts.items():
        role = "Batter" if "batting" in name.casefold() else "Bowler"
        finalized_state_counts.append(
            {
                "state": name,
                "delivery_rows": values["delivery_rows"],
                "matches": len(values["matches"]),
                "decided_chases": len(values["decided_chases"]),
                "legal_balls": values["legal_balls"],
                "players": len({key[0] for key in aggregates if key[1] == role and key[2] == name}),
            }
        )
    return aggregates, expected_states, finalized_state_counts


def recent_form_from_raw(
    matches: dict[int, dict[str, Any]],
    groups: dict[tuple[int, int], list[dict[str, Any]]],
    valid_ids: set[int],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, set[int]]]:
    """Recompute 2026 activity and each player's latest ten known T20 chase innings."""
    first_totals = {
        match_id: sum(team_run(row) for row in rows)
        for (match_id, innings_no), rows in groups.items()
        if innings_no == 1 and matches.get(match_id, {}).get("match_format") == "T20"
    }
    active = {"Batter": set(), "Bowler": set()}
    raw_innings: dict[tuple[str, int, int], dict[str, Any]] = {}

    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        rows1 = groups.get((match_id, 1), [])
        rows2 = groups.get((match_id, 2), [])
        if meta.get("season") == "2026":
            for row in rows1 + rows2:
                for field in ("striker_id", "non_striker_id"):
                    player_id = as_int(row.get(field), -1)
                    if player_id in valid_ids:
                        active["Batter"].add(player_id)
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    active["Bowler"].add(bowler_id)

        revised = str(meta.get("revised_target") or "").strip()
        target = as_int(revised) if revised else first_totals.get(match_id, 0) + 1 if (match_id, 1) in groups else None
        if target is None:
            continue
        score = legal_balls = 0
        state_known = True
        for row in rows2:
            kind = norm(row.get("extras_type"))
            if is_unknown(kind):
                state_known = False
            remaining = 120 - legal_balls if state_known else None
            known_state = bool(state_known and remaining is not None and remaining > 0)
            if known_state:
                batter_id = as_int(row.get("striker_id"), -1)
                if batter_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Batter", batter_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["runs"] += as_int(row.get("runs"))
                    item["balls"] += int(kind != "wide" and not is_unknown(kind))
                    item["dismissals"] += int(
                        batter_dismissal(row) and as_int(row.get("dismissed_player_id"), -1) == batter_id
                    )
                dismissed_id = as_int(row.get("dismissed_player_id"), -1)
                striker_id = as_int(row.get("striker_id"), -1)
                if batter_dismissal(row) and dismissed_id > 0 and dismissed_id != striker_id and dismissed_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Batter", dismissed_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["dismissals"] += 1
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Bowler", bowler_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["runs"] += bowler_run(row)
                    item["balls"] += int(is_legal(kind))
                    item["wickets"] += int(credited(row))
            score += team_run(row)
            legal_balls += int(is_legal(kind))
            if is_unknown(kind):
                state_known = False

    by_player: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for (role, player_id, _match_id), item in raw_innings.items():
        by_player[(role, player_id)].append(item)
    summary: dict[tuple[str, int], dict[str, Any]] = {}
    for key, innings_rows in by_player.items():
        recent = sorted(innings_rows, key=lambda row: (row["date"], row.get("match_id", 0)), reverse=True)[:10]
        runs = sum(int(row["runs"]) for row in recent)
        balls = sum(int(row["balls"]) for row in recent)
        dismissals = sum(int(row["dismissals"]) for row in recent)
        wickets = sum(int(row["wickets"]) for row in recent)
        summary[key] = {
            "recent_innings": len(recent),
            "recent_runs": runs,
            "recent_balls": balls,
            "recent_dismissals": dismissals,
            "recent_wickets": wickets,
            "recent_sr": round(100 * runs / balls, 4) if balls else None,
            "recent_average": round(runs / dismissals, 2) if dismissals >= 3 else "Not reported",
            "recent_economy": round(6 * runs / balls, 4) if balls else None,
            "recent_wicket_rate_per_6": round(6 * wickets / balls, 4) if balls else None,
            "recent_latest_date": recent[0]["date"] if recent else "",
        }
    return summary, active


def db_aggregates(conn: sqlite3.Connection) -> dict[tuple[int, str, str], dict[str, int]]:
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT player_id, role, state, SUM(deliveries) AS deliveries, SUM(runs) AS runs,
           SUM(balls) AS balls, SUM(dismissals) AS dismissals, SUM(fours) AS fours,
           SUM(sixes) AS sixes, SUM(dots) AS dots, SUM(legal_balls) AS legal_balls,
           SUM(credited_wickets) AS credited_wickets, SUM(boundaries) AS boundaries,
           COUNT(DISTINCT match_id) AS matches, COUNT(DISTINCT match_id || ':' || innings) AS innings
    FROM (
      SELECT d.striker_id AS player_id, 'Batter' AS role,
             CASE WHEN d.pressure=1 THEN 'Batting pressure' ELSE 'Ordinary batting chase' END AS state,
             1 AS deliveries, d.runs AS runs, d.faced_ball AS balls,
             CASE WHEN d.is_wicket=1 AND d.dismissed_player_id=d.striker_id
                       AND lower(trim(coalesce(d.dismissal_type,''))) NOT IN
                           ('retire out','retired out','retire hurt','retired hurt','obstracting the field','obstructing the field')
                  THEN 1 ELSE 0 END AS dismissals,
             d.is_four AS fours, d.is_six AS sixes, d.batter_dot AS dots,
             0 AS legal_balls, 0 AS credited_wickets, 0 AS boundaries,
             d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0 AND d.striker_id>0
      UNION ALL
      SELECT d.dismissed_player_id AS player_id, 'Batter' AS role,
             CASE WHEN d.pressure=1 THEN 'Batting pressure' ELSE 'Ordinary batting chase' END AS state,
             0 AS deliveries, 0 AS runs, 0 AS balls, 1 AS dismissals,
             0 AS fours, 0 AS sixes, 0 AS dots,
             0 AS legal_balls, 0 AS credited_wickets, 0 AS boundaries,
             d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0
        AND d.is_wicket=1 AND d.dismissed_player_id>0 AND d.dismissed_player_id<>d.striker_id
        AND lower(trim(coalesce(d.dismissal_type,''))) NOT IN
            ('retire out','retired out','retire hurt','retired hurt','obstracting the field','obstructing the field')
      UNION ALL
      SELECT d.bowler_id AS player_id, 'Bowler' AS role,
             CASE WHEN d.bowling_pressure=1 THEN 'Bowling pressure' ELSE 'Ordinary bowling chase' END AS state,
             1 AS deliveries, d.bowler_runs_proxy AS runs, 0 AS balls,
             0 AS dismissals, 0 AS fours, 0 AS sixes,
             CASE WHEN d.legal=1 AND d.bowler_runs_proxy=0 THEN 1 ELSE 0 END AS dots,
             d.legal AS legal_balls, d.credited_wicket AS credited_wickets,
             d.is_four+d.is_six AS boundaries, d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0 AND d.bowler_id>0
    ) events
    GROUP BY player_id, role, state
    """
    result = {}
    for row in conn.execute(sql):
        values = dict(row)
        key = (int(values["player_id"]), str(values["role"]), str(values["state"]))
        result[key] = {field: int(values.get(field) or 0) for field in (
            "deliveries", "runs", "balls", "dismissals", "fours", "sixes", "dots", "legal_balls", "credited_wickets", "boundaries", "matches", "innings"
        )}
    return result


def close(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str):
        return actual == expected
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return bool(actual) is expected
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=0.0051)
    except (TypeError, ValueError):
        return False


def shrink(raw: float | None, sample: int, baseline: float | None, prior: int) -> float | None:
    if baseline is None:
        return round(raw, 4) if raw is not None else None
    value = baseline if raw is None else raw
    return round((value * sample + baseline * prior) / (sample + prior), 4) if sample + prior else round(baseline, 4)


def percentile_map(keys: list[tuple[int, str, str]], values: dict[tuple[int, str, str], float], higher: bool, names: dict[tuple[int, str, str], str]) -> dict[tuple[int, str, str], float]:
    ordered = sorted(keys, key=lambda key: ((-values[key]) if higher else values[key], names.get(key, "")))
    result: dict[tuple[int, str, str], float] = {}
    start = 0
    while start < len(ordered):
        value = values[ordered[start]]
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == value:
            end += 1
        average_rank = ((start + 1) + end) / 2
        score = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - average_rank) / (len(ordered) - 1)
        for key in ordered[start:end]:
            result[key] = round(score, 4)
        start = end
    return result


def compare_sample(
    raw: dict[tuple[int, str, str], dict[str, int]],
    db: dict[tuple[int, str, str], dict[str, int]],
    report: dict[str, Any],
    recent: dict[tuple[str, int], dict[str, Any]],
    active: dict[str, set[int]],
    state_counts: list[dict[str, Any]],
    *,
    sample_size: int | None = 10,
) -> list[dict[str, Any]]:
    randomizer = random.Random(SAMPLE_SEED)
    report_rows: dict[tuple[int, str, str], dict[str, Any]] = {}
    for role, table_name in (("Batter", "batter_table"), ("Bowler", "bowler_table")):
        for row in report.get(table_name, []):
            key = (int(row["player_id"]), role, str(row["state"]))
            report_rows[key] = row
    output_keys = sorted(report_rows)
    if sample_size is None:
        sampled = output_keys
    else:
        sampled = randomizer.sample(output_keys, min(sample_size, len(output_keys)))

    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for key, item in raw.items():
        role, state = key[1], key[2]
        totals[(role, state)]["runs"] += int(item.get("runs", 0))
        totals[(role, state)]["balls"] += int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        totals[(role, state)]["dismissals"] += int(item.get("dismissals", 0))
        totals[(role, state)]["wickets"] += int(item.get("credited_wickets", 0))

    expected_metrics: dict[tuple[int, str, str], dict[str, Any]] = {}
    for key, item in raw.items():
        role, state = key[1], key[2]
        base = totals[(role, state)]
        balls = int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        runs = int(item.get("runs", 0))
        if role == "Batter":
            sr = round(100 * runs / balls, 4) if balls else None
            avg = round(runs / int(item["dismissals"]), 4) if int(item["dismissals"]) >= 3 else "Not reported"
            baseline_sr = 100 * base["runs"] / base["balls"] if base["balls"] else None
            baseline_avg = base["runs"] / base["dismissals"] if base["dismissals"] else None
            adjusted_sr = shrink(sr, balls, baseline_sr, 60)
            internal_avg = round(runs / int(item["dismissals"]), 4) if int(item["dismissals"]) else None
            adjusted_avg_internal = shrink(internal_avg, int(item["dismissals"]), baseline_avg, 3)
            adjusted_avg = adjusted_avg_internal if int(item["dismissals"]) >= 3 else "Not reported"
            boundary_share = round(100 * (int(item["fours"]) + int(item["sixes"])) / balls, 4) if balls else None
            dot_share = round(100 * int(item["dots"]) / balls, 4) if balls else None
            values = {
                "strike_rate": sr,
                "adjusted_strike_rate": adjusted_sr,
                "average": avg,
                "adjusted_average": adjusted_avg,
                "_adjusted_average_for_composite": adjusted_avg_internal,
                "boundary_events": int(item["fours"]) + int(item["sixes"]),
                "boundary_share": boundary_share,
                "dot_share": dot_share,
            }
        else:
            economy = round(6 * runs / balls, 4) if balls else None
            wicket_rate = round(6 * int(item["credited_wickets"]) / balls, 4) if balls else None
            baseline_economy = 6 * base["runs"] / base["balls"] if base["balls"] else None
            baseline_wicket_rate = 6 * base["wickets"] / base["balls"] if base["balls"] else None
            values = {
                "economy": economy,
                "adjusted_economy": shrink(economy, balls, baseline_economy, 60),
                "credited_wickets": int(item["credited_wickets"]),
                "balls_per_wicket": round(balls / int(item["credited_wickets"]), 4) if int(item["credited_wickets"]) else "Not defined",
                "wicket_rate_per_6": wicket_rate,
                "adjusted_wicket_rate_per_6": shrink(wicket_rate, balls, baseline_wicket_rate, 60),
                "dot_share": round(100 * int(item["dots"]) / balls, 4) if balls else None,
                "boundaries_conceded": int(item["boundaries"]),
            }
        expected_metrics[key] = values

    expected_eligible: set[tuple[int, str, str]] = set()
    recent_counts: dict[tuple[int, str, str], int] = {}
    for key, item in raw.items():
        role = key[1]
        sample_balls = int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        form = recent.get((role, key[0]), {})
        recent_counts[key] = int(form.get("recent_innings", 0))
        eligible = sample_balls >= 30 and key[0] in active.get(role, set()) and recent_counts[key] >= 10
        if role == "Bowler":
            eligible = eligible and int(item.get("credited_wickets", 0)) >= 3
        if eligible:
            expected_eligible.add(key)

    composite_scores: dict[tuple[int, str, str], float] = {}
    expected_ranks: dict[tuple[int, str, str], int | None] = {}
    decided_by_state = {str(row["state"]): int(row.get("decided_chases") or 0) for row in state_counts}
    for role in ("Batter", "Bowler"):
        states = {key[2] for key in raw if key[1] == role}
        for state in states:
            keys = [key for key in expected_eligible if key[1] == role and key[2] == state]
            names = {key: str(report_rows.get(key, {}).get("player") or key[0]) for key in keys}
            if len(keys) < 10 or decided_by_state.get(state, 0) < 20:
                expected_ranks.update({key: None for key in keys})
                continue
            if role == "Batter":
                p_sr = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_strike_rate"]) for key in keys}, True, names)
                p_avg = percentile_map(keys, {key: float(expected_metrics[key]["_adjusted_average_for_composite"]) for key in keys}, True, names)
                p_bound = percentile_map(keys, {key: float(expected_metrics[key]["boundary_share"]) for key in keys}, True, names)
                for key in keys:
                    composite_scores[key] = round(0.5 * p_sr[key] + 0.3 * p_avg[key] + 0.2 * p_bound[key], 4)
            else:
                p_econ = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_economy"]) for key in keys}, False, names)
                p_wickets = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_wicket_rate_per_6"]) for key in keys}, True, names)
                p_dots = percentile_map(keys, {key: float(expected_metrics[key]["dot_share"]) for key in keys}, True, names)
                for key in keys:
                    composite_scores[key] = round(0.4 * p_econ[key] + 0.4 * p_wickets[key] + 0.2 * p_dots[key], 4)
            sample_field = "balls" if role == "Batter" else "legal_balls"
            ordered = sorted(keys, key=lambda key: (-composite_scores[key], -int(raw[key].get(sample_field, 0)), names[key]))
            expected_ranks.update({key: index for index, key in enumerate(ordered, 1)})

    checks = []
    db_fields = ("deliveries", "runs", "balls", "dismissals", "fours", "sixes", "dots", "legal_balls", "credited_wickets", "boundaries", "matches", "innings")
    for key in sampled:
        role, player_id, state = key[1], key[0], key[2]
        if key not in raw:
            checks.append({
                "player_id": player_id,
                "role": role,
                "state": state,
                "status": "FAIL",
                "mismatches": {"raw_row": {"raw_recomputed": "missing", "report": "present"}},
            })
            continue
        raw_row = raw[key]
        db_row = db.get(key, {})
        report_row = report_rows.get(key)
        mismatches: dict[str, Any] = {}
        for field in db_fields:
            expected = int(raw_row.get(field, 0))
            actual = int(db_row.get(field, 0))
            if expected != actual:
                mismatches[f"database.{field}"] = {"raw": expected, "database": actual}
        if report_row is None:
            mismatches["report_row"] = {"raw": "present", "report": "missing"}
        else:
            report_core = {
                "deliveries": int(raw_row.get("deliveries", 0)),
                "runs": int(raw_row.get("runs", 0)),
                "sample_balls": int(raw_row.get("balls" if role == "Batter" else "legal_balls", 0)),
                "dismissals": int(raw_row.get("dismissals", 0)),
                "fours": int(raw_row.get("fours", 0)),
                "sixes": int(raw_row.get("sixes", 0)),
                "dots": int(raw_row.get("dots", 0)),
                "matches": int(raw_row.get("matches", 0)),
                "innings": int(raw_row.get("innings", 0)),
            }
            if role == "Bowler":
                report_core.update({"credited_wickets": int(raw_row.get("credited_wickets", 0)), "boundaries_conceded": int(raw_row.get("boundaries", 0))})
            for field, expected in report_core.items():
                if not close(report_row.get(field), expected):
                    mismatches[f"report.{field}"] = {"raw": expected, "report": report_row.get(field)}
            for field, expected in expected_metrics[key].items():
                if field.startswith("_"):
                    continue
                if not close(report_row.get(field), expected):
                    mismatches[f"report.{field}"] = {"raw_recomputed": expected, "report": report_row.get(field)}
            form = recent.get((role, player_id), {})
            for field in (
                "recent_innings", "recent_runs", "recent_balls", "recent_dismissals", "recent_wickets",
                "recent_sr", "recent_average", "recent_economy", "recent_wicket_rate_per_6", "recent_latest_date",
            ):
                report_field = {
                    "recent_sr": "recent_strike_rate",
                }.get(field, field)
                if role == "Batter" and field in {"recent_wickets", "recent_economy", "recent_wicket_rate_per_6"}:
                    continue
                if role == "Bowler" and field in {"recent_dismissals", "recent_sr", "recent_average"}:
                    continue
                expected = form.get(field)
                if not close(report_row.get(report_field), expected):
                    mismatches[f"report.{report_field}"] = {"raw_recomputed": expected, "report": report_row.get(report_field)}
            expected_active = player_id in active.get(role, set())
            expected_recent_status = "Eligible form" if int(form.get("recent_innings", 0)) >= 10 else "Review sample"
            expected_sample_status = "Eligible sample" if int(report_core["sample_balls"]) >= 30 else "Review sample"
            expected_wicket_status = "Eligible for ranking" if int(raw_row.get("credited_wickets", 0)) >= 3 else "Review sample"
            if not close(report_row.get("active_2026_all_venues"), expected_active):
                mismatches["report.active_2026_all_venues"] = {"raw_recomputed": expected_active, "report": report_row.get("active_2026_all_venues")}
            if not close(report_row.get("recent_form_status"), expected_recent_status):
                mismatches["report.recent_form_status"] = {"raw_recomputed": expected_recent_status, "report": report_row.get("recent_form_status")}
            if not close(report_row.get("sample_status"), expected_sample_status):
                mismatches["report.sample_status"] = {"raw_recomputed": expected_sample_status, "report": report_row.get("sample_status")}
            if role == "Bowler" and not close(report_row.get("wicket_rate_status"), expected_wicket_status):
                mismatches["report.wicket_rate_status"] = {"raw_recomputed": expected_wicket_status, "report": report_row.get("wicket_rate_status")}
            expected_is_eligible = key in expected_eligible
            if not close(report_row.get("ranking_eligible"), expected_is_eligible):
                mismatches["report.ranking_eligible"] = {"raw_recomputed": expected_is_eligible, "report": report_row.get("ranking_eligible")}
            expected_score = composite_scores.get(key)
            expected_rank = expected_ranks.get(key)
            if not close(report_row.get("composite_score"), expected_score):
                mismatches["report.composite_score"] = {"raw_recomputed": expected_score, "report": report_row.get("composite_score")}
            if not close(report_row.get("rank"), expected_rank):
                mismatches["report.rank"] = {"raw_recomputed": expected_rank, "report": report_row.get("rank")}
        checks.append({"player_id": player_id, "role": role, "state": state, "status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches})
    return checks


def delivery_state_difference(expected: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, Any] | None:
    if actual is None:
        return {"fields_differing": ["state"], "raw_recount": expected, "processed": None}

    differences: list[str] = []
    actual_state = (
        "Unknown"
        if not actual["state_known"]
        else "Batting pressure"
        if actual["pressure"]
        else "Bowling pressure"
        if actual["bowling_pressure"]
        else "Ordinary chase"
        if actual["runs_needed"] is not None and actual["runs_needed"] > 0
        else "Target reached"
    )
    if (
        actual_state != expected["state"]
        or actual["state_known"] != expected["state_known"]
        or actual["pressure"] != expected["pressure"]
        or actual["bowling_pressure"] != expected["bowling_pressure"]
    ):
        differences.append("state")

    if expected["state_known"] and actual["state_known"]:
        for field, label in (
            ("balls_remaining", "balls remaining"),
            ("wickets_down", "wickets"),
            ("target", "target"),
            ("runs_needed", "runs needed"),
        ):
            if expected[field] != actual[field]:
                differences.append(label)
    if not differences:
        return None
    return {
        "fields_differing": list(dict.fromkeys(differences)),
        "raw_recount": expected,
        "processed": actual,
    }


def reconcile_top10_batters(
    raw: dict[tuple[int, str, str], dict[str, int]],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        row for row in report.get("batter_table", [])
        if row.get("state") == "Batting pressure" and row.get("rank") not in (None, "")
    ]
    rows.sort(key=lambda row: int(row["rank"]))
    output = []
    for row in rows[:10]:
        player_id = int(row["player_id"])
        raw_row = raw.get((player_id, "Batter", "Batting pressure"))
        raw_balls = int(raw_row.get("balls", 0)) if raw_row else None
        raw_runs = int(raw_row.get("runs", 0)) if raw_row else None
        raw_dismissals = int(raw_row.get("dismissals", 0)) if raw_row else None
        report_balls = int(row.get("sample_balls") or 0)
        report_runs = int(row.get("runs") or 0)
        report_dismissals = int(row.get("dismissals") or 0)
        matches = raw_row is not None and (
            raw_balls == report_balls
            and raw_runs == report_runs
            and raw_dismissals == report_dismissals
        )
        output.append({
            "rank": row.get("rank"),
            "player_id": player_id,
            "player": row.get("player"),
            "raw_balls": raw_balls,
            "leaderboard_balls": report_balls,
            "raw_runs": raw_runs,
            "leaderboard_runs": report_runs,
            "raw_dismissals": raw_dismissals,
            "leaderboard_dismissals": report_dismissals,
            "status": "PASS" if matches else "FAIL",
        })
    return output


def report_row_keys(report: dict[str, Any]) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    keys: list[tuple[int, str, str]] = []
    duplicates: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str, str]] = set()
    for role, table_name in (("Batter", "batter_table"), ("Bowler", "bowler_table")):
        for row in report.get(table_name, []):
            key = (int(row["player_id"]), role, str(row["state"]))
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            keys.append(key)
    return keys, duplicates


def audit_duplicate_stat_vectors(
    raw: dict[tuple[int, str, str], dict[str, int]],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    signatures: dict[tuple[Any, ...], list[tuple[tuple[int, str, str], dict[str, Any]]]] = defaultdict(list)
    fields_by_role = {
        "Batter": ("deliveries", "runs", "sample_balls", "dismissals", "fours", "sixes", "boundary_events", "dots", "matches", "innings"),
        "Bowler": ("deliveries", "runs", "sample_balls", "credited_wickets", "dots", "boundaries_conceded", "matches", "innings"),
    }
    for role, table_name in (("Batter", "batter_table"), ("Bowler", "bowler_table")):
        fields = fields_by_role[role]
        for row in report.get(table_name, []):
            player_id = int(row["player_id"])
            state = str(row["state"])
            signature = (role, state, *(row.get(field) for field in fields))
            signatures[signature].append(((player_id, role, state), row))

    duplicate_rows = []
    for signature, entries in signatures.items():
        player_ids = sorted({key[0] for key, _ in entries})
        if len(player_ids) < 2:
            continue
        role, state = signature[:2]
        fields = fields_by_role[role]
        raw_matches = True
        for key, report_row in entries:
            raw_row = raw.get(key)
            if raw_row is None:
                raw_matches = False
                continue
            for field in fields:
                if field == "sample_balls":
                    raw_value = raw_row.get("balls" if role == "Batter" else "legal_balls", 0)
                elif field == "boundary_events" and role == "Batter":
                    raw_value = int(raw_row.get("fours", 0)) + int(raw_row.get("sixes", 0))
                elif field == "boundaries_conceded" and role == "Bowler":
                    raw_value = raw_row.get("boundaries", 0)
                else:
                    raw_value = raw_row.get(field, 0)
                if not close(report_row.get(field), raw_value):
                    raw_matches = False
        duplicate_rows.append({
            "role": role,
            "state": state,
            "player_count": len(player_ids),
            "player_ids": ",".join(str(player_id) for player_id in player_ids),
            "players": " | ".join(str(row.get("player") or "") for _, row in entries),
            "raw_stat_vector": json.dumps(dict(zip(fields, signature[2:])), ensure_ascii=False, sort_keys=True),
            "raw_values_match_for_each_id": raw_matches,
            "status": "PASS" if raw_matches else "FAIL",
        })
    return duplicate_rows


def main() -> None:
    matches, groups, names, raw_totals = load_raw()
    invalid_ids = {
        player_id for player_id, variants in names.items()
        if len(variants) != 1 or any(
            not name.strip()
            or name.casefold() in {"unknown", "unknown player", "unknown batter", "unknown bowler"}
            for name in variants
        )
    }
    valid_ids = {player_id for player_id in names if player_id > 0 and player_id not in invalid_ids}
    raw_aggregates, expected_states, state_row_counts = player_aggregates_from_raw(matches, groups, valid_ids)
    raw_recent, raw_active = recent_form_from_raw(matches, groups, valid_ids)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    raw_recount_path = OUTPUT_DIR / "pressure_raw_recount.json"
    standalone_recount = json.loads(raw_recount_path.read_text(encoding="utf-8")) if raw_recount_path.exists() else {}
    conn = sqlite3.connect(str(DB_PATH))
    db_totals = conn.execute("SELECT COUNT(*), COALESCE(SUM(runs),0), COALESCE(SUM(legal),0) FROM deliveries").fetchone()
    raw_total_runs = conn.execute("SELECT COALESCE(SUM(runs),0) FROM deliveries").fetchone()[0]
    db_states = {
        (int(row[0]), int(row[1]), int(row[2])): {
            "state_known": int(row[3] or 0),
            "pressure": int(row[4] or 0),
            "bowling_pressure": int(row[5] or 0),
            "balls_remaining": int(row[6]) if row[6] is not None else None,
            "wickets_down": int(row[7]) if row[7] is not None else None,
            "target": int(row[8]) if row[8] is not None else None,
            "score_before": int(row[9]) if row[9] is not None else None,
            "runs_needed": int(row[8]) - int(row[9]) if row[8] is not None and row[9] is not None else None,
        }
        for row in conn.execute(
            """SELECT d.match_id,d.innings,d.seq,d.state_known,d.pressure,d.bowling_pressure,
                      d.balls_remaining,d.wickets_lost,d.target,d.score_before
               FROM deliveries d JOIN matches m ON m.match_id=d.match_id
               WHERE d.innings=2 AND m.match_format='T20'"""
        )
    }
    flag_mismatches = []
    for key, expected in expected_states.items():
        actual = db_states.get(key)
        difference = delivery_state_difference(expected, actual)
        if difference:
            flag_mismatches.append({"match_id": key[0], "innings": key[1], "seq": key[2], **difference})
    db_player_rows = db_aggregates(conn)
    random_rows = compare_sample(
        raw_aggregates, db_player_rows, report, raw_recent, raw_active, state_row_counts,
        sample_size=10,
    )
    all_player_checks = compare_sample(
        raw_aggregates, db_player_rows, report, raw_recent, raw_active, state_row_counts,
        sample_size=None,
    )
    conn.close()

    report_state_map = {str(row.get("state")): row for row in report.get("state_table", [])}
    state_count_mismatches = []
    for expected in state_row_counts:
        actual = report_state_map.get(str(expected["state"]))
        differences = {
            field: {"raw_recomputed": expected[field], "report": actual.get(field) if actual else None}
            for field in ("delivery_rows", "matches", "decided_chases", "legal_balls", "players")
            if actual is None or int(actual.get(field) or 0) != int(expected[field])
        }
        if differences:
            state_count_mismatches.append({"state": expected["state"], "mismatches": differences})

    raw_flag_counts = {
        "batting_pressure": sum(int(row["pressure"]) for row in expected_states.values()),
        "bowling_pressure": sum(int(row["bowling_pressure"]) for row in expected_states.values()),
    }
    raw_flag_counts["both_pressure_flags"] = raw_flag_counts["batting_pressure"] + raw_flag_counts["bowling_pressure"]
    database_flag_counts = {
        "batting_pressure": sum(row["pressure"] for row in db_states.values()),
        "bowling_pressure": sum(row["bowling_pressure"] for row in db_states.values()),
    }
    database_flag_counts["both_pressure_flags"] = database_flag_counts["batting_pressure"] + database_flag_counts["bowling_pressure"]
    raw_delivery_state_count_match = len(expected_states) == len(db_states)

    report_keys, duplicate_report_keys = report_row_keys(report)
    report_key_set = set(report_keys)
    raw_key_set = set(raw_aggregates)
    missing_report_keys = sorted(raw_key_set - report_key_set)
    extra_report_keys = sorted(report_key_set - raw_key_set)
    all_player_failures = [row for row in all_player_checks if row["status"] != "PASS"]
    top10_rows = reconcile_top10_batters(raw_aggregates, report)
    duplicate_stat_rows = audit_duplicate_stat_vectors(raw_aggregates, report)
    duplicate_stat_path = OUTPUT_DIR / "pressure_duplicate_player_stats_audit.csv"
    duplicate_stat_fields = list(duplicate_stat_rows[0]) if duplicate_stat_rows else [
        "role", "state", "player_count", "player_ids", "players", "raw_stat_vector",
        "raw_values_match_for_each_id", "status",
    ]
    with duplicate_stat_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=duplicate_stat_fields)
        writer.writeheader()
        writer.writerows(duplicate_stat_rows)
    duplicate_stats_match_raw = all(row["status"] == "PASS" for row in duplicate_stat_rows)
    top10_path = OUTPUT_DIR / "pressure_top10_batter_reconciliation.csv"
    top10_fields = list(top10_rows[0]) if top10_rows else [
        "rank", "player_id", "player", "raw_balls", "leaderboard_balls", "raw_runs",
        "leaderboard_runs", "raw_dismissals", "leaderboard_dismissals", "status",
    ]
    with top10_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=top10_fields)
        writer.writeheader()
        writer.writerows(top10_rows)

    # Reconcile the user's supplied batter values as a separate reference check.
    supplied_top10 = {
        "Rinku Singh": (94, 239, 1),
        "Tristan Stubbs": (50, 123, 3),
        "Rashid Khan": (65, 149, 5),
        "David Miller": (58, 140, 3),
        "Ashutosh Sharma": (33, 76, 2),
        "Sherfane Rutherford": (52, 106, 4),
        "Naman Dhir": (40, 80, 2),
        "Dhruv Jurel": (50, 89, 3),
        "Rahul Tewatia": (76, 145, 9),
        "Ramandeep Singh": (38, 74, 3),
    }
    raw_batting_rows = {
        int(row["player_id"]): row
        for row in report.get("batter_table", [])
        if row.get("state") == "Batting pressure"
    }
    source_names_to_ids = {
        name: next((player_id for player_id, variants in names.items() if name in variants), None)
        for name in supplied_top10
    }
    supplied_reference_rows = []
    for name, (expected_balls, expected_runs, expected_outs) in supplied_top10.items():
        player_id = source_names_to_ids[name]
        raw_row = raw_aggregates.get((player_id, "Batter", "Batting pressure")) if player_id is not None else None
        computed_balls = int(raw_row.get("balls", 0)) if raw_row else None
        computed_runs = int(raw_row.get("runs", 0)) if raw_row else None
        computed_outs = int(raw_row.get("dismissals", 0)) if raw_row else None
        matches_reference = (computed_balls, computed_runs, computed_outs) == (expected_balls, expected_runs, expected_outs)
        supplied_reference_rows.append({
            "player_id": player_id,
            "player": name,
            "reference_balls": expected_balls,
            "raw_balls": computed_balls,
            "reference_runs": expected_runs,
            "raw_runs": computed_runs,
            "reference_dismissals": expected_outs,
            "raw_dismissals": computed_outs,
            "status": "PASS" if matches_reference else "REFERENCE MISMATCH",
        })
    supplied_reference_path = OUTPUT_DIR / "pressure_supplied_batter_reference_reconciliation.csv"
    with supplied_reference_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(supplied_reference_rows[0]) if supplied_reference_rows else ["player", "status"])
        writer.writeheader()
        writer.writerows(supplied_reference_rows)

    # The 45,385 value is the number of T20 chase rows checked, never a flag count.
    try:
        tristan_id = next(player_id for player_id, variants in names.items() if "Tristan Stubbs" in variants)
    except StopIteration:
        tristan_id = None
    tristan_keys = []
    if tristan_id is not None:
        for key in sorted(expected_states):
            source_row = groups.get((key[0], key[1]), [])[key[2] - 1]
            if as_int(source_row.get("striker_id"), -1) == tristan_id or as_int(source_row.get("dismissed_player_id"), -1) == tristan_id:
                tristan_keys.append(key)
    tristan_differences = [
        {"match_id": key[0], "innings": key[1], "seq": key[2], **delivery_state_difference(expected_states[key], db_states.get(key))}
        for key in tristan_keys
        if delivery_state_difference(expected_states[key], db_states.get(key))
    ]
    tristan_diff_report = {
        "player": "Tristan Stubbs",
        "player_id": tristan_id,
        "delivery_rows_checked": len(tristan_keys),
        "difference_count": len(tristan_differences),
        "first_delivery_difference": tristan_differences[0] if tristan_differences else None,
        "conclusion": "No delivery-level difference found for this player." if not tristan_differences else "Inspect the first delivery difference and its named fields.",
    }
    (OUTPUT_DIR / "pressure_tristan_first_diff.json").write_text(
        json.dumps(tristan_diff_report, indent=2), encoding="utf-8"
    )
    flag_diff_path = OUTPUT_DIR / "pressure_flag_diff.csv"
    diff_rows = [
        {
            "match_id": row["match_id"],
            "innings": row["innings"],
            "seq": row["seq"],
            "fields_differing": "; ".join(row["fields_differing"]),
            "raw_recount": json.dumps(row["raw_recount"], sort_keys=True),
            "processed": json.dumps(row["processed"], sort_keys=True),
        }
        for row in flag_mismatches
    ]
    with flag_diff_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["match_id", "innings", "seq", "fields_differing", "raw_recount", "processed"])
        writer.writeheader()
        writer.writerows(diff_rows)

    margin_checks = []
    margin_rows_checked = 0
    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        result = str(meta.get("result") or "")
        match = re.search(r"won\s+by\s+(\d+)\s+runs?", result, flags=re.IGNORECASE)
        if not match or (match_id, 1) not in groups or (match_id, 2) not in groups:
            continue
        margin_rows_checked += 1
        first_score = sum(team_run(row) for row in groups[(match_id, 1)])
        second_score = sum(team_run(row) for row in groups[(match_id, 2)])
        reported = int(match.group(1))
        computed = first_score - second_score
        if computed != reported:
            margin_checks.append({"match_id": match_id, "reported_run_margin": reported, "computed_margin": computed, "first_innings_count_formula": first_score, "second_innings_count_formula": second_score, "status": "Not reproducible from the supplied count-based extras formula"})

    row_count_match = int(db_totals[0]) == raw_totals["delivery_rows"]
    run_total_match = int(db_totals[1]) == raw_totals["runs"] == int(raw_total_runs)
    legal_total_match = int(db_totals[2]) == raw_totals["legal_balls"]
    flag_match = not flag_mismatches and raw_delivery_state_count_match and raw_flag_counts == database_flag_counts
    sample_match = len(random_rows) == 10 and all(row["status"] == "PASS" for row in random_rows)
    all_player_rows_match = (
        not duplicate_report_keys
        and not missing_report_keys
        and not extra_report_keys
        and len(all_player_checks) == len(report_keys)
        and not all_player_failures
    )
    top10_match = len(top10_rows) == 10 and all(row["status"] == "PASS" for row in top10_rows)
    id_audit = report.get("player_id_audit", {})
    report_excluded = set(
        report.get("excluded_player_ids", {}).get("multiple_source_names", [])
        + report.get("excluded_player_ids", {}).get("unknown_or_blank_name", [])
    )
    id_exclusions_match = report_excluded == invalid_ids and int(id_audit.get("excluded_unknown_or_multi_name_ids", -1)) == len(invalid_ids)
    distinct_id_match = int(id_audit.get("distinct_source_player_ids", -1)) == len(names)
    valid_id_match = int(id_audit.get("eligible_source_player_ids", -1)) == len(valid_ids)
    id_check = id_exclusions_match and distinct_id_match and valid_id_match
    standalone_counts = standalone_recount.get("pressure_flags", {})
    standalone_state_rows = [
        {field: row.get(field) for field in ("state", "delivery_rows", "matches", "decided_chases", "legal_balls", "players")}
        for row in standalone_recount.get("state_table", [])
    ]
    user_flag_reference = {"batting_pressure": 6699, "bowling_pressure": 38, "both_pressure_flags": 6737}
    supplied_flag_reference_match = user_flag_reference == raw_flag_counts
    reference_state_rows = [
        {field: row.get(field) for field in ("state", "delivery_rows", "matches", "decided_chases", "legal_balls", "players")}
        for row in state_row_counts
    ]
    computed_state_rows = [
        {field: report_state_map.get(row["state"], {}).get(field) for field in ("state", "delivery_rows", "matches", "decided_chases", "legal_balls", "players")}
        for row in state_row_counts
    ]
    standalone_match = (
        int(standalone_counts.get("batting_pressure", -1)) == raw_flag_counts["batting_pressure"]
        and int(standalone_counts.get("bowling_pressure", -1)) == raw_flag_counts["bowling_pressure"]
        and int(standalone_counts.get("both_pressure_flags", -1)) == raw_flag_counts["both_pressure_flags"]
        and standalone_state_rows == reference_state_rows
    )
    raw_state_json = json.dumps(reference_state_rows, sort_keys=True)
    computed_state_json = json.dumps(computed_state_rows, sort_keys=True)
    duplicate_key_count = len(duplicate_report_keys)
    random_pass_count = sum(row["status"] == "PASS" for row in random_rows)
    top10_pass_count = sum(row["status"] == "PASS" for row in top10_rows)
    all_player_pass_count = len(all_player_checks) - len(all_player_failures)
    log = [
        {"check": "Raw delivery row count", "reference": raw_totals["delivery_rows"], "computed": int(db_totals[0]), "status": "PASS" if row_count_match else "FAIL"},
        {"check": "Raw runs column sum", "reference": raw_totals["runs"], "computed": int(db_totals[1]), "status": "PASS" if run_total_match else "FAIL"},
        {"check": "Known legal-ball count", "reference": raw_totals["legal_balls"], "computed": int(db_totals[2]), "status": "PASS" if legal_total_match else "FAIL"},
        {"check": "Batting-pressure delivery flags", "reference": raw_flag_counts["batting_pressure"], "computed": database_flag_counts["batting_pressure"], "status": "PASS" if database_flag_counts["batting_pressure"] == raw_flag_counts["batting_pressure"] else "FAIL"},
        {"check": "Bowling-pressure delivery flags", "reference": raw_flag_counts["bowling_pressure"], "computed": database_flag_counts["bowling_pressure"], "status": "PASS" if database_flag_counts["bowling_pressure"] == raw_flag_counts["bowling_pressure"] else "FAIL"},
        {"check": "Combined distinct pressure flags", "reference": raw_flag_counts["both_pressure_flags"], "computed": database_flag_counts["both_pressure_flags"], "status": "PASS" if database_flag_counts["both_pressure_flags"] == raw_flag_counts["both_pressure_flags"] else "FAIL"},
        {"check": "T20 second-innings delivery states checked", "reference": len(expected_states), "computed": len(db_states), "status": "PASS" if raw_delivery_state_count_match else "FAIL"},
        {"check": "Delivery-by-delivery state differences", "reference": 0, "computed": len(flag_mismatches), "status": "PASS" if not flag_mismatches else "FAIL"},
        {"check": "Standalone raw-only recount agrees with validator recount", "reference": {"pressure_flags": raw_flag_counts, "state_table": reference_state_rows}, "computed": {"pressure_flags": standalone_counts, "state_table": standalone_state_rows}, "status": "PASS" if standalone_match else "FAIL"},
        {"check": "State table totals (state, delivery rows, matches, decided chases, legal balls, players)", "reference": raw_state_json, "computed": computed_state_json, "status": "PASS" if not state_count_mismatches else "FAIL"},
        {"check": "Leaderboard raw figures, derived metrics, recent form and ranks", "reference": len(raw_aggregates), "computed": f"{all_player_pass_count} of {len(all_player_checks)} rows match", "status": "PASS" if all_player_rows_match else "FAIL"},
        {"check": "Top 10 batting-pressure leaders match raw balls, runs and dismissals", "reference": 10, "computed": f"{top10_pass_count} of {len(top10_rows)} match", "status": "PASS" if top10_match else "FAIL"},
        {"check": "Random 10 leaderboard output rows recomputed from raw", "reference": 10, "computed": f"{random_pass_count} of {len(random_rows)} match", "status": "PASS" if sample_match else "FAIL"},
        {"check": "Leaderboard player_id/state keys have no duplicates", "reference": 0, "computed": duplicate_key_count, "status": "PASS" if duplicate_key_count == 0 else "FAIL"},
        {"check": "Repeated stat vectors equal each player's raw figures", "reference": "0 unexplained duplicate vectors", "computed": f"{len(duplicate_stat_rows)} duplicate vectors; {sum(row['status'] != 'PASS' for row in duplicate_stat_rows)} unexplained", "status": "PASS" if duplicate_stats_match_raw else "FAIL"},
        {"check": "Unknown or multi-name player IDs excluded", "reference": f"{len(invalid_ids)} excluded of {len(names)} source IDs", "computed": f"{int(id_audit.get('excluded_unknown_or_multi_name_ids', -1))} excluded of {int(id_audit.get('distinct_source_player_ids', -1))} source IDs", "status": "PASS" if id_check else "FAIL"},
        {"check": "Distinct eligible source player IDs (959 is not an exclusion count)", "reference": len(valid_ids), "computed": int(id_audit.get("eligible_source_player_ids", -1)), "status": "PASS" if valid_id_match else "FAIL"},
        {"check": "Supplied 6,737 pressure-flag reference reproduced", "reference": user_flag_reference, "computed": raw_flag_counts, "status": "PASS" if supplied_flag_reference_match else "REFERENCE MISMATCH"},
        {"check": "Supplied ten-batter raw figures reproduced", "reference": "10 supplied player rows", "computed": f"{sum(row['status'] == 'PASS' for row in supplied_reference_rows)} match; {sum(row['status'] != 'PASS' for row in supplied_reference_rows)} differ", "status": "PASS" if all(row["status"] == "PASS" for row in supplied_reference_rows) else "REFERENCE MISMATCH"},
        {"check": "Source run-margin reconciliation under count-based extras rule", "reference": margin_rows_checked, "computed": f"{margin_rows_checked-len(margin_checks)} reproduced; {len(margin_checks)} source margins differ", "status": "SOURCE LIMITATION" if margin_checks else "PASS"},
    ]
    core_checks = [
        row for row in log
        if row["check"] not in {
            "Supplied 6,737 pressure-flag reference reproduced",
            "Supplied ten-batter raw figures reproduced",
            "Source run-margin reconciliation under count-based extras rule",
        }
    ]
    core_pass = all(row["status"] == "PASS" for row in core_checks)
    validation = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Raw CSV recomputation, cross-checked against a separate standard-library-only raw recount script; no dashboard state functions are imported.",
        "random_seed": SAMPLE_SEED,
        "random_player_rows_requested": 10,
        "random_player_rows_checked": len(random_rows),
        "raw_totals": raw_totals,
        "database_totals": {"delivery_rows": int(db_totals[0]), "runs": int(db_totals[1]), "known_legal_balls": int(db_totals[2])},
        "raw_pressure_flag_totals": raw_flag_counts,
        "database_pressure_flag_totals": database_flag_counts,
        "supplied_pressure_flag_reference": user_flag_reference,
        "pressure_delivery_rows_checked": len(expected_states),
        "pressure_delivery_recount": state_row_counts,
        "state_count_mismatches": state_count_mismatches,
        "pressure_flag_mismatches": len(flag_mismatches),
        "flag_mismatch_examples": flag_mismatches[:100],
        "tristan_first_delivery_diff": tristan_diff_report,
        "top10_batter_raw_reconciliation": top10_rows,
        "duplicate_player_stat_vectors": duplicate_stat_rows,
        "supplied_batter_reference_reconciliation": supplied_reference_rows,
        "all_leaderboard_rows_checked": len(all_player_checks),
        "all_leaderboard_row_failures": all_player_failures,
        "leaderboard_key_audit": {
            "raw_player_state_keys": len(raw_key_set),
            "leaderboard_player_state_keys": len(report_key_set),
            "duplicate_keys": duplicate_report_keys,
            "missing_rows": missing_report_keys,
            "extra_rows": extra_report_keys,
        },
        "random_player_row_checks": random_rows,
        "source_run_margin_reconciliation": {"checked_rows": margin_rows_checked, "mismatched_rows": len(margin_checks), "unreproducible_rows": margin_checks},
        "excluded_player_ids": {
            "count": len(invalid_ids),
            "ids": sorted(invalid_ids),
            "distinct_source_player_ids": len(names),
            "eligible_player_ids": len(valid_ids),
            "reported_exclusion_count": id_audit.get("excluded_unknown_or_multi_name_ids"),
        },
        "standalone_raw_recount": standalone_recount,
        "validation_log": log,
        "overall_status": (
            "FAIL"
            if not core_pass
            else "PASS WITH REFERENCE DISAGREEMENT AND SOURCE LIMITATIONS"
            if margin_checks or not supplied_flag_reference_match or any(row["status"] != "PASS" for row in supplied_reference_rows)
            else "PASS"
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    with VALIDATION_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["check", "reference", "computed", "status"])
        writer.writeheader()
        writer.writerows(log)
    exception_rows = [
        {"kind": "state_flag", **row} for row in flag_mismatches
    ] + [
        {"kind": "state_count", **row} for row in state_count_mismatches
    ] + [
        {"kind": "random_player_state", "player_id": row["player_id"], "role": row["role"], "state": row["state"], "mismatches": json.dumps(row["mismatches"], ensure_ascii=False)}
        for row in random_rows if row["status"] != "PASS"
    ] + [
        {"kind": "result_run_margin", **row} for row in margin_checks
    ]
    columns = sorted({key for row in exception_rows for key in row}) if exception_rows else ["kind", "status"]
    with EXCEPTIONS_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(exception_rows)
    if REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        report["validation"] = validation
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "overall_status": validation["overall_status"],
        "raw_pressure_flags": raw_flag_counts,
        "database_pressure_flags": database_flag_counts,
        "pressure_delivery_rows_checked": len(expected_states),
        "state_flag_mismatches": len(flag_mismatches),
        "tristan_first_delivery_diff": tristan_diff_report,
        "top10_batter_passes": f"{top10_pass_count}/{len(top10_rows)}",
        "random_output_rows_passes": f"{random_pass_count}/{len(random_rows)}",
        "leaderboard_row_failures": len(all_player_failures),
        "leaderboard_duplicate_keys": duplicate_key_count,
        "leaderboard_duplicate_stat_vectors": len(duplicate_stat_rows),
        "validation_log": str(VALIDATION_CSV),
        "output": str(VALIDATION_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()
